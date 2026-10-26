import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatInput, PROMPT_MAX_LENGTH } from "@/components/chat/ChatInput";

describe("ChatInput composer", () => {
  it("names the textarea 'Message' and keeps its placeholder", () => {
    render(<ChatInput onSend={async () => {}} disabled={false} />);
    const textbox = screen.getByRole("textbox", { name: "Message" });
    expect(textbox).toHaveAttribute("placeholder", "Type your prompt...");
  });

  it("caps the textarea at the API's 20000-character prompt limit", () => {
    render(<ChatInput onSend={async () => {}} disabled={false} />);
    const textbox = screen.getByRole("textbox", { name: "Message" });
    // The literal is ChatRequest.prompt's max_length; it is asserted apart
    // from the constant so a drift on either side fails here.
    expect(PROMPT_MAX_LENGTH).toBe(20000);
    expect(textbox).toHaveAttribute("maxlength", "20000");
  });
});
