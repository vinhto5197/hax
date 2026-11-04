import { describe, expect, it } from "vitest";

import { inert, toTsv } from "./DataTable";

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

// Spreadsheets read a pasted field that starts with a double quote as a
// quoted field: they drop the quotes, and an unclosed one swallows the tabs
// and line breaks after it, even after leading spaces (probed in Google
// Sheets, 2026-11-03).
describe("toTsv", () => {
  it.each([
    ['"Acme" Ltd', '"""Acme"" Ltd"'],
    ['"Acme, Ltd"', '"""Acme, Ltd"""'],
    ['"Acme Ltd', '"""Acme Ltd"'],
    ['  "Acme Ltd', '"  ""Acme Ltd"'],
  ])(
    "quotes the quote-led cell %j so it pastes as itself",
    (cell, expected) => {
      expect(toTsv(["cell"], [[cell]])).toBe(`cell\n${expected}`);
    },
  );

  it.each(['Acme "Ltd"', "plain", "'=1+1"])("leaves %j as it is", (cell) => {
    expect(toTsv(["cell"], [[cell]])).toBe(`cell\n${cell}`);
  });

  it("keeps an unclosed quote inside its own cell and row", () => {
    expect(
      toTsv(
        ["case", "cell", "next"],
        [
          ["C", '"Acme Ltd', "C-after"],
          ["D", "x", "D-after"],
        ],
      ),
    ).toBe('case\tcell\tnext\nC\t"""Acme Ltd"\tC-after\nD\tx\tD-after');
  });

  it("quotes a quote-led formula-looking cell, so it pastes as its literal text", () => {
    expect(toTsv(["cell"], [['"=1"']])).toBe('cell\n"""=1"""');
  });

  it.each([
    ["a tab", "a\tb"],
    ["a newline", "a\nb"],
    ["a carriage return", "a\rb"],
  ])("turns %s inside a cell into a single space", (_, cell) => {
    expect(toTsv(["cell"], [[cell]])).toBe("cell\na b");
  });

  it("keeps the table shape when cells hold tabs and newlines", () => {
    const rows = toTsv(["h1", "h2"], [["x\ty", "p\nq"]]).split("\n");
    expect(rows).toHaveLength(2);
    expect(rows[1].split("\t")).toEqual(["x y", "p q"]);
  });

  it("neutralises a formula-looking body cell in the copied text", () => {
    expect(toTsv(["ok"], [["=1+1"]])).toBe("ok\n'=1+1");
  });
});
