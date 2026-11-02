import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewChat } from "@/components/chat/NewChat";
import { pickGreeting } from "@/lib/greeting";

// Local-time constructor so getHours() is 9 regardless of the runner's zone;
// only Date is faked, so React's scheduling keeps real timers.
const morning = new Date(2026, 9, 21, 9, 0);
// A member: no example chips (a non-empty list marks the visitor's screen).
const member = { name: "Ada Lovelace", chips: [], onSend: async () => {} };

describe("NewChat greeting", () => {
  let expected: string;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(morning);
    vi.spyOn(Math, "random").mockReturnValue(0);
    expected = pickGreeting(member.name, morning, () => 0);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("server HTML holds only a no-break space in the heading, no greeting", () => {
    const html = renderToString(<NewChat {...member} />);
    const heading = html.match(/<h1[^>]*>([^<]*)<\/h1>/);
    expect(heading).not.toBeNull();
    expect(heading![1]).toBe(" ");
    expect(html).not.toContain(expected);
  });

  it("a client render shows the greeting", () => {
    render(<NewChat {...member} />);
    expect(
      screen.getByRole("heading", { level: 1, name: expected }),
    ).toBeInTheDocument();
  });
});
