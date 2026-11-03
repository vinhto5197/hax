import { describe, expect, it } from "vitest";

import { inert } from "./DataTable";

describe("inert", () => {
  it.each([
    ["=SUM(A1:A9)", "'=SUM(A1:A9)"],
    ["+1+1", "'+1+1"],
    ["@SUM(A1)", "'@SUM(A1)"],
    ["-2+3+cmd|' /C calc'!A0", "'-2+3+cmd|' /C calc'!A0"],
    ["  =1+1", "'  =1+1"],
    ["@handle", "'@handle"],
    ["-5°C", "'-5°C"],
    ["-", "'-"],
    ["=", "'="],
    ["\t=1+1", "'\t=1+1"],
  ])("neutralises the formula cell %j", (cell, expected) => {
    expect(inert(cell)).toBe(expected);
  });

  // A cell that parses as a signed number stays a number, even when it does
  // not read as one ("+1 555 0100" is a phone number, "- 5" has a space).
  it.each([
    "-5",
    "-$1,850",
    "+5",
    "-12%",
    "- 5",
    "+1 555 0100",
    '"=1"',
    "\tplain",
    "plain text",
    "a = b",
    "",
  ])("leaves %j unchanged", (cell) => {
    expect(inert(cell)).toBe(cell);
  });
});
