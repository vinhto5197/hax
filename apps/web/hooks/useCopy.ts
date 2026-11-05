import { useState } from "react";

// `copied` flashes true for 1.5 s after a successful write. The clipboard can
// refuse (permission, insecure context); `copy` never rejects, so a click
// handler leaves no unhandled rejection.
export function useCopy(): [boolean, (text: string) => Promise<void>] {
  const [copied, setCopied] = useState(false);

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return [copied, copy];
}
