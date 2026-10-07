"use client";

import { useState } from "react";
import type { ExtraProps } from "react-markdown";

type Cell = string;
type Row = Cell[];

// Walk a hast subtree and collect its text; inline markup inside a cell is
// flattened on purpose — sorting and CSV need plain cells.
function textOf(node: unknown): string {
  if (!node || typeof node !== "object") return "";
  const n = node as { type?: string; value?: string; children?: unknown[] };
  if (n.type === "text") return n.value ?? "";
  return (n.children ?? []).map(textOf).join("");
}

// A GFM table in hast: table > (thead > tr > th*) (tbody > tr > td*)*.
function parseTable(node: ExtraProps["node"]): { header: Row; rows: Row[] } {
  const header: Row = [];
  const rows: Row[] = [];
  const sections = (node?.children ?? []) as Array<{
    type?: string;
    tagName?: string;
    children?: unknown[];
  }>;
  for (const section of sections) {
    if (section.type !== "element") continue;
    const trs = (section.children ?? []) as Array<{
      type?: string;
      tagName?: string;
      children?: unknown[];
    }>;
    for (const tr of trs) {
      if (tr.type !== "element" || tr.tagName !== "tr") continue;
      const cells = (
        (tr.children ?? []) as Array<{ type?: string; tagName?: string }>
      )
        .filter(
          (c) =>
            c.type === "element" && (c.tagName === "th" || c.tagName === "td"),
        )
        .map((c) => textOf(c).trim());
      if (section.tagName === "thead" && header.length === 0)
        header.push(...cells);
      else rows.push(cells);
    }
  }
  // Ragged rows from the model render rather than throw: pad to the widest.
  const width = Math.max(header.length, ...rows.map((r) => r.length), 0);
  while (header.length < width) header.push("");
  for (const r of rows) while (r.length < width) r.push("");
  return { header, rows };
}

// "$1,850", "12%", "3.5" count as numbers; "none" does not. Placeholders a
// model puts in a figures column ("—", "N/A", blank) are not numbers either,
// but they must not turn the whole column textual: a column is numeric when
// every non-placeholder cell parses, and placeholders sort last.
const PLACEHOLDER = /^(?:[-—–]+|n\/?a|none|null|\?)$/i;

function asNumber(cell: Cell): number | null {
  const stripped = cell.replace(/[$,%\s]/g, "");
  if (!stripped) return null;
  const n = Number(stripped);
  return Number.isFinite(n) ? n : null;
}

function isPlaceholder(cell: Cell): boolean {
  return !cell.trim() || PLACEHOLDER.test(cell.trim());
}

function columnIsNumeric(rows: Row[], col: number): boolean {
  const real = rows.filter((r) => !isPlaceholder(r[col] ?? ""));
  return real.length > 0 && real.every((r) => asNumber(r[col]) !== null);
}

// Cells are model output, and an uploaded file can author model output (the
// invariant behind Markdown.tsx's image guard). In a spreadsheet a cell that
// starts with = + - @ or a control character is a formula, so an export must
// not hand one over verbatim: a leading apostrophe makes it text. Signed
// figures ("-5", "-$1,850") parse as numbers and are left alone.
function inert(c: Cell): Cell {
  return /^[=+\-@\t\r]/.test(c.trim()) && asNumber(c) === null ? `'${c}` : c;
}

// For the clipboard: spreadsheets split pasted text on tabs without being
// asked (Sheets never splits pasted commas), so a copy is tab-separated. A
// tab or newline inside a cell would break the grid; collapse it to a space.
function toTsv(header: Row, rows: Row[]): string {
  const flat = (c: Cell) => inert(c.replace(/[\t\n\r]+/g, " "));
  return [header, ...rows].map((r) => r.map(flat).join("\t")).join("\n");
}

// For the download: RFC 4180 CSV, the file format every spreadsheet imports.
// Quote a cell holding a comma, a quote or a line break; double quotes.
function toCsv(header: Row, rows: Row[]): string {
  const q = (raw: Cell) => {
    const c = inert(raw);
    return /[",\r\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c;
  };
  return [header, ...rows].map((r) => r.map(q).join(",")).join("\n");
}

type Sort = { col: number; dir: 1 | -1 } | null;

// Every Markdown table in a reply renders through this: the Markdown in
// `content` stays the source of truth, so nothing here is persisted.
export function DataTable({ node }: ExtraProps) {
  // Not memoized: react-markdown rebuilds the tree on every render, so the
  // node is never the same object twice and the parse is cheap beside it.
  const { header, rows } = parseTable(node);
  const [sort, setSort] = useState<Sort>(null);
  const [copied, setCopied] = useState(false);

  // Computed per render, like the parse above (a memo on a per-render input
  // would never hit).
  const sorted = (() => {
    if (!sort) return rows;
    const numeric = columnIsNumeric(rows, sort.col);
    return [...rows].sort((a, b) => {
      const x = a[sort.col] ?? "";
      const y = b[sort.col] ?? "";
      if (numeric) {
        const nx = asNumber(x);
        const ny = asNumber(y);
        // Placeholders go last in either direction.
        if (nx === null || ny === null)
          return (nx === null ? 1 : 0) - (ny === null ? 1 : 0);
        return (nx - ny) * sort.dir;
      }
      return x.localeCompare(y, undefined, { sensitivity: "base" }) * sort.dir;
    });
  })();

  function toggleSort(col: number) {
    setSort((s) =>
      s && s.col === col ? { col, dir: s.dir === 1 ? -1 : 1 } : { col, dir: 1 },
    );
  }

  async function copyTable() {
    // The clipboard can refuse (permission, insecure context); a click handler
    // must not leave an unhandled rejection — the download button remains.
    try {
      await navigator.clipboard.writeText(toTsv(header, sorted));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  function downloadCsv() {
    // The byte-order mark is what makes Excel read the file as UTF-8 rather
    // than ANSI (download only; the clipboard needs none).
    const blob = new Blob(["\ufeff", toCsv(header, sorted)], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "table.csv";
    a.click();
    // Revoking synchronously can cancel the download in WebKit; defer it.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (header.length === 0 && rows.length === 0) return null;

  return (
    <div className="not-prose my-2 text-sm">
      <div className="overflow-x-auto rounded-md border border-black/10 dark:border-white/10">
        <table className="w-full border-collapse">
          <thead className="bg-black/5 dark:bg-white/10">
            <tr>
              {header.map((h, i) => (
                <th
                  key={i}
                  scope="col"
                  aria-sort={
                    sort?.col === i
                      ? sort.dir === 1
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                  className="px-2 py-1 text-left font-semibold"
                >
                  <button
                    type="button"
                    onClick={() => toggleSort(i)}
                    className="inline-flex items-center gap-1 hover:underline"
                  >
                    {h}
                    {sort?.col === i ? (
                      <span aria-hidden="true">
                        {sort.dir === 1 ? "▲" : "▼"}
                      </span>
                    ) : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, ri) => (
              <tr
                key={ri}
                className="border-t border-black/10 dark:border-white/10"
              >
                {r.map((c, ci) => (
                  <td
                    key={ci}
                    className="px-2 py-1 align-top whitespace-pre-wrap"
                  >
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-1 flex gap-3 text-xs text-black/50 dark:text-white/50">
        <button type="button" onClick={copyTable} className="hover:underline">
          {copied ? "Copied" : "Copy table"}
        </button>
        <button type="button" onClick={downloadCsv} className="hover:underline">
          Download CSV
        </button>
      </div>
    </div>
  );
}
