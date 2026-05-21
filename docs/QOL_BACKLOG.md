# QOL backlog

Polish ideas noted during v0 development. Not in scope for current milestone — implement opportunistically when the milestone work pauses or as portfolio polish before the next round of demo screenshots.

Each entry includes a brief sketch of approach. Treat as starting points, not specs.

---

## Smooth typewriter streaming (decouple display from chunk arrival)

**Problem:** Anthropic API streams in bursty chunks (sometimes 2 words, sometimes 30). With chunky chunks, the chat feels jumpy — text appears in awkwardly large jumps rather than a fluid typewriter feel.

**Approach:** Separate the **receive buffer** (grows as chunks arrive) from the **visible content** (grows char-by-char on a render loop).

Pseudocode:

```ts
let received = "";
let visible = "";

onChunk((text) => { received += text; });

// requestAnimationFrame loop
function animate() {
  if (visible.length < received.length) {
    const next = Math.min(received.length, visible.length + charsPerFrame());
    visible = received.slice(0, next);
    setStreamingContent(visible);
  }
  requestAnimationFrame(animate);
}

function charsPerFrame() {
  // Adaptive: speed up if buffer is way ahead, slow down to target ~40 cps
  const ahead = received.length - visible.length;
  if (ahead > 500) return 8;        // catch-up mode
  if (ahead > 50) return 2;          // normal typewriter
  return ahead > 0 ? 1 : 0;          // sip
}
```

Tradeoffs:
- More responsive feel even when API chunks are large.
- Stream completion no longer matches model completion; if user closes browser mid-animation, content is lost from view despite being received. Mitigated by also writing `received` somewhere persistable.
- Adds complexity. Premature for v0; worth it once UX is the focal point.

---

## Markdown progressive rendering

**Problem:** Rendering raw `streamingContent` text means half-formed markdown shows broken syntax during streaming (e.g., `**bo` renders as literal asterisks before becoming `**bold**`).

**Approach:** Render markdown through a streaming-aware parser (e.g., `markdown-it`, `marked`, or `react-markdown` with a token cache). Re-parse on each update; treat unclosed inline syntax as not-yet-bold/italic rather than broken.

Most chat UIs handle this with a debounced full re-parse — fine for v0-scale messages.

---

## "Still receiving" indicator during extension-induced pauses

**Problem:** Some users have browser extensions that buffer fetch responses, releasing them in chunks rather than streaming. From the UI, this looks like the chat froze mid-response.

**Approach:** If `isLoading=true` and `streamingContent` hasn't grown in N seconds (>2s), show a subtle pulsing dot or "still thinking" hint. Avoids the "is this stuck?" feel.

Detection:

```ts
useEffect(() => {
  if (!isLoading) return;
  const lastUpdate = Date.now();
  const id = setInterval(() => {
    if (Date.now() - lastUpdate > 2000) setStaleHint(true);
  }, 500);
  return () => clearInterval(id);
}, [isLoading, streamingContent]);
```

---

## Code block + table rendering

**Problem:** Plain `{message.content}` rendering loses formatting. Code blocks aren't syntax-highlighted; tables collapse to raw markdown text.

**Approach:** Markdown component (`react-markdown` + `remark-gfm` + `rehype-highlight` or `prismjs`) — handles fenced code, tables, lists, links cleanly. Add a "Copy" button on code blocks.

Pairs naturally with the markdown progressive rendering above.

---

## Auto-scroll to bottom during streaming

**Problem:** Long responses push the latest content off-screen; user has to manually scroll.

**Approach:**
- Track whether the message list is already scrolled to bottom.
- During streaming, if it was at the bottom, keep scrolling to bottom as new content arrives.
- If user has scrolled up, don't auto-scroll (respect their intent).
- Add a "scroll to latest" floating button when scrolled up.

Standard chat UI pattern. Common gotcha: detect "at bottom" with some tolerance (within 50px) so smooth-scroll doesn't undo itself.

---

## Stop / regenerate / edit message actions

**Problem:** Once a chat is mid-stream, there's no way to abort. After a response, no way to retry or edit the prompt.

**Approach:**
- **Stop:** abort the `fetch` via AbortController; cancel `streamChat`.
- **Regenerate:** re-send the last user message.
- **Edit:** allow inline edit of the user message; truncate history to that point + resend.

Requires conversation-history state model (M1 territory). Cheapest version: just "stop" works with current stateless single-turn.

---

## Per-message timing indicator

**Problem:** Hard to gauge model speed / cost per response.

**Approach:** Capture wall-clock time from request-sent to stream-complete. Show in subtle UI element (e.g., "3.4s") below the assistant message. Easy to add, surprisingly nice for product feel.

Future: include token counts + cost (requires server to surface usage from Anthropic's response metadata).

---

## Submit on Enter, newline on Shift+Enter

**Problem:** Single-line input currently submits only via button click. Power users expect Enter to send.

**Approach:** Replace `<input>` with `<textarea>`; handle Enter / Shift+Enter in `onKeyDown`.

```tsx
onKeyDown={(e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSubmit(e);
  }
}}
```

Combine with auto-resize so the textarea grows up to ~5 lines, then scrolls.

---

## Tighter "Assistant is thinking" indicator

**Problem:** The current `<p>Assistant is thinking...</p>` is functional but not pretty. Sits at full text width, looks like a regular message.

**Approach:** Pulsing dot indicator (`...` animating, or three bouncing dots). Inline with the assistant's empty bubble shape, not as separate text. Disappears the moment streamingContent becomes non-empty.

---

## Empty state polish

**Problem:** First load shows "Start chatting by entering a prompt below." Functional but boring.

**Approach:** Suggested-prompt chips ("Tell me a story" / "Explain quantum computing"), small example of what the chat can do, project framing if portfolio-relevant. Click chips to populate input.

---

## Dark mode toggle

**Problem:** Theme follows OS preference via Tailwind's `dark:` classes. No way to override.

**Approach:** Add a toggle button somewhere unobtrusive. Persist preference in localStorage. Wrapping `<html>` with `class="dark"` or `class="light"` lets Tailwind's dark mode strategy switch to "selector" mode.
