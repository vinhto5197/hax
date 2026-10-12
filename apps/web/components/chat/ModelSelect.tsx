"use client";

import type { components } from "@/lib/openapi";

// The one place the offered models are listed; "" is the server default (env
// LLM_MODEL). The Default label deliberately names no model — that's
// server-owned config and a name here would go stale. The ids are typed
// against the API's allowlist, so a change on either side fails `tsc` rather
// than a request.
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
    <label className="flex items-center gap-2 text-caption text-ink-3">
      Model
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="rounded-control border border-border-control bg-surface-1 px-2 py-1 text-small text-ink disabled:cursor-not-allowed disabled:opacity-50"
      >
        {MODEL_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
