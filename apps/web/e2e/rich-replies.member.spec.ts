import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { send } from "./chat";

// Rich replies from the fake model's `table:` and `code:` prompts: a Markdown
// table rendered as a sortable data table with copy and CSV download, and a
// highlighted code block beside a remote image whose src is stripped.
const ROWS = [
  ["Apples", "10"],
  ["Pears", "9"],
  ["Plums", "—"],
  ["Figs", "100"],
] as const;

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

async function askForTable(page: Page) {
  await page.goto("/chat");
  await send(page, "table: fruit counts");
  const table = page.getByRole("main").getByRole("table");
  await expect(table).toBeVisible();
  await expect(table.getByText("Figs", { exact: true })).toBeVisible();
  return table;
}

function lines(text: string) {
  return text.split(/\r?\n/).filter((line) => line.trim() !== "");
}

test("row 10: a table reply renders as a table; sorting Count ascending gives 9, 10, 100 with the dash last, and descending keeps the dash last", async ({
  page,
}) => {
  const table = await askForTable(page);
  const counts = table.locator("tbody tr td:nth-child(2)");
  await expect(counts).toHaveText(["10", "9", "—", "100"]);

  const header = table
    .getByRole("columnheader", { name: /Count/ })
    .getByRole("button", { name: "Count" });
  await header.click();
  await expect(counts).toHaveText(["9", "10", "100", "—"]);

  await header.click();
  await expect(counts).toHaveText(["100", "10", "9", "—"]);
});

test("row 10: Copy table puts tab-separated text on the clipboard and reads Copied", async ({
  page,
}) => {
  await askForTable(page);
  const main = page.getByRole("main");
  await main.getByRole("button", { name: "Copy table" }).click();
  await expect(main.getByRole("button", { name: "Copied" })).toBeVisible();

  const copied = lines(
    await page.evaluate(() => navigator.clipboard.readText()),
  );
  expect(copied).toEqual([
    "Item\tCount",
    ...ROWS.map(([item, count]) => `${item}\t${count}`),
  ]);
});

test("row 10: Download CSV downloads a file whose text holds the four rows", async ({
  page,
}) => {
  await askForTable(page);
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("main")
    .getByRole("button", { name: "Download CSV" })
    .click();
  const download = await downloading;
  const csv = lines(await readFile((await download.path())!, "utf-8"));

  expect(csv).toHaveLength(5);
  expect(csv[0]).toMatch(/Item.*Count/);
  ROWS.forEach(([item, count], i) => {
    expect(csv[i + 1]).toContain(item);
    expect(csv[i + 1]).toContain(count);
  });
});

test("row 12: a code reply shows a highlighted code block and an image whose src never points at example.com, and nothing is requested from example.com", async ({
  page,
}) => {
  const remote: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).hostname.endsWith("example.com")) {
      remote.push(request.url());
    }
  });

  await page.goto("/chat");
  await send(page, "code: a greeting function");
  const main = page.getByRole("main");
  const block = main.locator("pre").filter({ hasText: "def greet(name):" });
  await expect(block).toBeVisible();
  await expect(block).toContainText('return f"Hello, {name}"');
  await expect(
    block.locator('[class^="hljs-"], [class*=" hljs-"]').first(),
  ).toBeAttached();

  const image = main.locator('img[alt="chart"]');
  await expect(image).toHaveCount(1);
  expect((await image.getAttribute("src")) ?? "").not.toContain("example.com");
  await expect(main.locator('img[src*="example.com"]')).toHaveCount(0);

  // Give a stray fetch time to start before asserting none did.
  await page.waitForTimeout(1_000);
  expect(remote).toEqual([]);
});
