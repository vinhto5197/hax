// Time-of-day greetings from the viewer's clock; one is picked per visit to
// the new-chat screen. {name} is optional so a nameless account reads the
// same line without the suffix.
const RANGES: Array<{ from: number; to: number; lines: string[] }> = [
  {
    from: 5,
    to: 12,
    lines: [
      "Good morning{, name}",
      "Early bird gets the worm{, name}",
      "Happy {weekday}{, name}",
    ],
  },
  {
    from: 12,
    to: 18,
    lines: [
      "Good afternoon{, name}",
      "Pushing through the day{, name}?",
      "Happy {weekday}{, name}",
    ],
  },
  {
    from: 18,
    to: 23,
    lines: [
      "Good evening{, name}",
      "Winding down{, name}?",
      "How was your {weekday}{, name}?",
    ],
  },
  {
    from: 23,
    to: 5,
    lines: [
      "Staying up late{, name}?",
      "Burning the midnight oil{, name}?",
      "Still at it{, name}?",
    ],
  },
];

export function pickGreeting(
  name: string | null,
  now = new Date(),
  pick = Math.random,
): string {
  const h = now.getHours();
  // A range with from > to wraps past midnight; the half-open bounds keep
  // every hour in exactly one range.
  const range = RANGES.find((r) =>
    r.from < r.to ? h >= r.from && h < r.to : h >= r.from || h < r.to,
  )!;
  const line = range.lines[Math.floor(pick() * range.lines.length)];
  const first = name?.trim().split(/\s+/)[0] ?? "";
  const weekday = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
  }).format(now);
  return line
    .replace("{, name}", first ? `, ${first}` : "")
    .replace("{weekday}", weekday);
}
