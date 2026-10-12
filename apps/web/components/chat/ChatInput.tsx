"use client";

import {
  type KeyboardEvent,
  type SubmitEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { ModelSelect } from "@/components/chat/ModelSelect";

interface ChatInputProps {
  onSend: (text: string) => Promise<void>;
  disabled: boolean;
  // The model choice belongs to the composer: given a handler, the picker
  // sits in the frame's bottom row; a visitor's composer passes none.
  model?: string;
  onModelChange?: (value: string) => void;
}

export function ChatInput({
  onSend,
  disabled,
  model,
  onModelChange,
}: ChatInputProps) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // A disabled input drops focus, so after a turn streams (disabled while it
  // runs) the keyboard would land nowhere; take it back as soon as the
  // composer re-enables, and on first mount.
  useEffect(() => {
    if (!disabled) inputRef.current?.focus();
  }, [disabled]);

  // The composer grows with its content up to the CSS max-height, after which
  // it scrolls; measured from scrollHeight because a textarea cannot size to
  // its content in every browser yet.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    const max = parseFloat(getComputedStyle(el).maxHeight);
    const wanted = el.scrollHeight;
    el.style.height = `${Math.min(wanted, max)}px`;
    // The bar appears only once the cap is hit; before that a textarea would
    // still draw one for the rounding between scrollHeight and height.
    el.style.overflowY = wanted > max ? "auto" : "hidden";
  }, [input]);

  // Enter sends, Shift+Enter breaks the line; an IME composition's Enter is
  // left to the IME.
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    )
      return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();

    const prompt = input.trim();
    if (!prompt || disabled) return;

    setInput("");
    await onSend(prompt);
  }

  return (
    // Two rows inside one frame: the text, then the secondary controls on the
    // left and send on the right, so the picker reads as part of the composer.
    <form
      onSubmit={handleSubmit}
      className="flex flex-col rounded-control border border-border-control bg-surface-1 p-1.5 focus-within:border-accent"
    >
      <textarea
        ref={inputRef}
        rows={1}
        className="block max-h-[40vh] w-full resize-none bg-transparent py-1.5 pr-1 pl-2 text-body text-ink outline-hidden"
        placeholder="Type your prompt..."
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
      />
      <div className="flex items-center justify-between gap-2">
        {onModelChange ? (
          <ModelSelect
            value={model ?? ""}
            onChange={onModelChange}
            disabled={disabled}
          />
        ) : (
          <span />
        )}
        <button
          type="submit"
          aria-label="Send"
          title="Send"
          className="flex size-8 shrink-0 items-center justify-center rounded-control bg-accent text-accent-ink disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-3"
          disabled={disabled || !input.trim()}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M13 3v5a2 2 0 0 1-2 2H4" />
            <path d="M6.5 7.5 4 10l2.5 2.5" />
          </svg>
        </button>
      </div>
    </form>
  );
}
