"use client";

import type { components } from "@/lib/openapi";

// The one place the offered models are listed; "" is the server default (env
// LLM_MODEL). The Default label deliberately names no model — that's
// server-owned config and a name here would go stale. The ids are typed
// against the API's allowlist, so an id removed or renamed in the API fails
// `tsc` rather than a request; an id added to the API still type-checks and
// is simply not offered until it is listed here.
type ModelId = NonNullable<components["schemas"]["ChatRequest"]["model"]>;
const MODEL_OPTIONS = [
  { value: "", label: "Default" },
  { value: "claude-haiku-4-5", label: "Haiku" },
  { value: "claude-sonnet-4-6", label: "Sonnet" },
  { value: "claude-opus-4-8", label: "Opus" },
] as const satisfies readonly { value: "" | ModelId; label: string }[];

export function ModelSelect({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-center gap-1 text-caption text-ink-3">
      <span className="sr-only">Model</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="rounded-control bg-transparent px-2 py-1 text-small text-ink-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {MODEL_OPTIONS.map((option) => (
          <option
            key={option.value}
            value={option.value}
            className="bg-surface-1 text-ink"
          >
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
