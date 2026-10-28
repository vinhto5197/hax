"use client";

import { useId } from "react";

import type { components } from "@/lib/openapi";

// The one place the offered models are listed; "" is the server default (env
// LLM_MODEL). The Default label deliberately names no model — that's
// server-owned config and a name here would go stale. The ids are typed
// against the API's allowlist, so an id removed or renamed in the API fails
// `tsc` rather than a request; an id added to the API still type-checks and
// is simply not offered until it is listed here. A hint is read before
// choosing (the option's title and the line beside the select), so it names a
// trade-off, never a price; Default's hint names no model for the same reason
// as its label.
type ModelId = NonNullable<components["schemas"]["ChatRequest"]["model"]>;
const MODEL_OPTIONS = [
  { value: "", label: "Default", hint: "Fast and inexpensive" },
  { value: "claude-haiku-4-5", label: "Haiku", hint: "Fastest, cheapest" },
  {
    value: "claude-sonnet-4-6",
    label: "Sonnet",
    hint: "Stronger reasoning, slower",
  },
  {
    value: "claude-opus-4-8",
    label: "Opus",
    hint: "Strongest, slowest, costs the most",
  },
] as const satisfies readonly {
  value: "" | ModelId;
  label: string;
  hint: string;
}[];

export function ModelSelect({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const hintId = useId();
  const hint = MODEL_OPTIONS.find((option) => option.value === value)?.hint;
  return (
    <div className="flex min-w-0 flex-col gap-0.5 sm:flex-row sm:items-center sm:gap-2">
      <label className="flex items-center">
        <span className="sr-only">Model</span>
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          aria-describedby={hint ? hintId : undefined}
          className="rounded-control bg-transparent px-2 py-1 text-small text-ink-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {MODEL_OPTIONS.map((option) => (
            <option
              key={option.value}
              value={option.value}
              title={option.hint}
              className="bg-surface-1 text-ink"
            >
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {hint && (
        <span
          id={hintId}
          className="truncate px-2 text-caption text-ink-3 sm:px-0"
        >
          {hint}
        </span>
      )}
    </div>
  );
}
