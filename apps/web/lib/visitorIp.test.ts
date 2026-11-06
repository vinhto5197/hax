import { describe, expect, it } from "vitest";

import { visitorIp } from "@/lib/visitorIp";

describe("visitorIp", () => {
  it("returns the first x-forwarded-for entry, the browser as the proxy saw it", () => {
    const h = new Headers({ "x-forwarded-for": "198.51.100.4, 10.0.0.1" });
    expect(visitorIp(h)).toBe("198.51.100.4");
  });

  it("trims whitespace around the first entry", () => {
    const h = new Headers({ "x-forwarded-for": " 198.51.100.4 , 10.0.0.1" });
    expect(visitorIp(h)).toBe("198.51.100.4");
  });

  it("returns an empty string when there is no x-forwarded-for header", () => {
    expect(visitorIp(new Headers())).toBe("");
  });

  it("returns a single address unchanged when there is no comma", () => {
    const h = new Headers({ "x-forwarded-for": "203.0.113.7" });
    expect(visitorIp(h)).toBe("203.0.113.7");
  });
});
