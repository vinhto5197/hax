import { describe, expect, it } from "vitest";

import { inert } from "./DataTable";

describe("inert", () => {
  it.each([
    ["=SUM(A1:A9)", "'=SUM(A1:A9)"],
    ["+1+1", "'+1+1"],
    ["@SUM(A1)", "'@SUM(A1)"],
    ["-2+3+cmd|' /C calc'!A0", "'-2+3+cmd|' /C calc'!A0"],
    ["  =1+1", "'  =1+1"],
  ])("neutralises the formula cell %j", (cell, expected) => {
    expect(inert(cell)).toBe(expected);
  });

  it.each(["-5", "-$1,850", "+5", "plain text", "a = b", ""])(
    "leaves %j unchanged",
    (cell) => {
      expect(inert(cell)).toBe(cell);
    },
  );
});
