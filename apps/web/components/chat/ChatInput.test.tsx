import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatInput } from "@/components/chat/ChatInput";

describe("ChatInput composer", () => {
  it("names the textarea 'Message' and keeps its placeholder", () => {
    render(<ChatInput onSend={async () => {}} disabled={false} />);
    const textbox = screen.getByRole("textbox", { name: "Message" });
    expect(textbox).toHaveAttribute("placeholder", "Type your prompt...");
  });
});
