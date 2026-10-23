import { describe, expect, it } from "vitest";

import { pickGreeting } from "@/lib/greeting";

// Local-time constructor so getHours() is 9 regardless of the runner's zone.
const morning = new Date(2026, 9, 21, 9, 0);
const first = () => 0;
const last = () => 0.99;
// Same Intl call as the implementation, so the test is locale-independent.
const weekday = new Intl.DateTimeFormat(undefined, { weekday: "long" }).format(
  morning,
);

describe("pickGreeting", () => {
  it("uses the first word of the trimmed name", () => {
    expect(pickGreeting("  Ada Lovelace ", morning, first)).toBe(
      "Good morning, Ada",
    );
  });

  it("drops the name suffix when there is no name", () => {
    expect(pickGreeting(null, morning, first)).toBe("Good morning");
    expect(pickGreeting("   ", morning, first)).toBe("Good morning");
  });

  it("fills the weekday token", () => {
    expect(pickGreeting("Ada", morning, last)).toBe(`Happy ${weekday}, Ada`);
  });

  it.each(["$&", "A$&b", "$1", "$$", "$`", "$'"])(
    "shows a name with replacement pattern %s literally",
    (name) => {
      expect(pickGreeting(name, morning, first)).toBe(`Good morning, ${name}`);
      expect(pickGreeting(name, morning, last)).toBe(
        `Happy ${weekday}, ${name}`,
      );
    },
  );

  it("does not substitute a {weekday} token inside the name", () => {
    expect(pickGreeting("{weekday}", morning, last)).toBe(
      `Happy ${weekday}, {weekday}`,
    );
  });
});
