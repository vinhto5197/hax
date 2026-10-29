import { expect, test, type Locator, type Page } from "@playwright/test";
import { send } from "./chat";

// Sources: a `search:` question over the member's own documents, answered by
// the fake model's tool_use, with the "Sources" footer under the reply.
//
// Upload budget: the member may make 5 accepted uploads an hour (a code
// constant; Redis db 15 is flushed per run). This file makes exactly 2, and
// documents-lifecycle.member exactly 3; no other journey makes an accepted
// upload. A sixth would be a 429.
//
// The fake embeds every text as the same vector, so a search returns every
// chunk of the corpus in no defined order: the run starts with no documents
// (prepare.py truncates the database), and these two files, three chunks in
// all, are the whole corpus. Serial: the phone test reuses the first test's
// documents and reply.
test.describe.configure({ mode: "serial" });

const API_URL = "http://localhost:8001";
const WEB_ORIGIN = "http://localhost:3001";
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };
const ANSWER = "Here is what your documents say.";

const stamp = `${Date.now()}`;
const SHORT = {
  name: `orchard-notes-${stamp}.txt`,
  text: "Orchard notes: the quince tree by the north wall fruits in October.",
  phrase: "the quince tree by the north wall",
};
// Over 1600 characters (RAG_CHUNK_SIZE), so it splits into two chunks; the
// opening and closing sentences land in different chunks.
const LONG_OPENING = "Ledger opening: the cellar holds forty jars of plum jam.";
const LONG_CLOSING = "Ledger closing: the last crate of pears left on Friday.";
const LONG = {
  name: `pantry-ledger-${stamp}.txt`,
  text: [
    LONG_OPENING,
    ...Array.from(
      { length: 40 },
      (_, i) => `Shelf ${i + 1} is stacked with jars labelled by season.`,
    ),
    LONG_CLOSING,
  ].join("\n"),
};

let conversationPath = "";

function escape(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function panel(scope: Page | Locator) {
  return scope.locator("details");
}

function documentRow(scope: Page | Locator, filename: string) {
  // By tag, not role: a collapsed panel hides its rows from the role query.
  return panel(scope).locator("li").filter({ hasText: filename });
}

function chip(page: Page, filename: string) {
  return page
    .getByRole("main")
    .getByRole("button", { name: new RegExp(escape(filename)) });
}

async function uploadAndWaitReady(
  page: Page,
  files: { name: string; text: string }[],
) {
  for (const file of files) {
    await page.locator('input[type="file"]').setInputFiles({
      name: file.name,
      mimeType: "text/plain",
      buffer: Buffer.from(file.text, "utf-8"),
    });
    await expect(documentRow(page, file.name)).toBeVisible();
  }
  for (const file of files) {
    await expect(
      documentRow(page, file.name).getByText("Processing…"),
    ).toHaveCount(0, { timeout: 30_000 });
    await expect(
      documentRow(page, file.name).getByText("ready", { exact: true }),
    ).toBeVisible();
  }
}

// afterAll has no page fixture: a context of its own, signed in as the
// project's member.
test.afterAll(async ({ browser }, testInfo) => {
  const context = await browser.newContext({
    storageState: testInfo.project.use.storageState,
  });
  const listing = await context.request.get(`${API_URL}/api/documents`);
  expect(listing.status()).toBe(200);
  const ours = new Set([SHORT.name, LONG.name]);
  const docs = (await listing.json()) as { id: string; filename: string }[];
  for (const doc of docs.filter((d) => ours.has(d.filename))) {
    const deleted = await context.request.delete(
      `${API_URL}/api/documents/${doc.id}`,
      { headers: { Origin: WEB_ORIGIN } },
    );
    expect(deleted.status()).toBe(204);
  }
  await context.close();
});

test.describe("desktop", () => {
  test.use({ viewport: DESKTOP });

  test("row 8: a search question shows Searching documents…, then the reply with a Sources footer holding one chip per document, never two for the same file", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.goto("/chat");
    await uploadAndWaitReady(page, [SHORT, LONG]);

    await send(page, "search: what is kept in the pantry and orchard");
    const main = page.getByRole("main");
    await expect(main.getByText("Searching documents…")).toBeVisible();
    await expect(main.getByText(ANSWER, { exact: true })).toBeVisible();
    await expect(main.getByText("Searching documents…")).toHaveCount(0);
    await expect(main.getByText("Sources", { exact: true })).toBeVisible();

    // The long file contributes two passages, still one chip.
    await expect(chip(page, SHORT.name)).toHaveCount(1);
    await expect(chip(page, LONG.name)).toHaveCount(1);

    await expect(page).toHaveURL(/\/chat\/[^/]+$/);
    conversationPath = new URL(page.url()).pathname;

    // A committed reply keeps its footer after a reload.
    await page.reload();
    await expect(main.getByText(ANSWER, { exact: true })).toBeVisible();
    await expect(chip(page, SHORT.name)).toHaveCount(1);
    await expect(chip(page, LONG.name)).toHaveCount(1);
  });

  test("row 8: a source chip expands to its passages, both passages for the two-chunk file", async ({
    page,
  }) => {
    expect(conversationPath).not.toBe("");
    await page.goto(conversationPath);
    const main = page.getByRole("main");
    await expect(main.getByText(ANSWER, { exact: true })).toBeVisible();

    await expect(main.getByText(LONG_OPENING)).toHaveCount(0);
    await expect(main.getByText(LONG_CLOSING)).toHaveCount(0);
    await chip(page, LONG.name).click();
    await expect(main.getByText(LONG_OPENING).first()).toBeVisible();
    await expect(main.getByText(LONG_CLOSING).first()).toBeVisible();

    await expect(main.getByText(SHORT.phrase)).toHaveCount(0);
    await chip(page, SHORT.name).click();
    await expect(main.getByText(SHORT.phrase).first()).toBeVisible();
  });

  test("row 9: Show in panel on desktop reveals and flashes that document's row", async ({
    page,
  }) => {
    expect(conversationPath).not.toBe("");
    await page.goto(conversationPath);
    const main = page.getByRole("main");
    await expect(main.getByText(ANSWER, { exact: true })).toBeVisible();

    // Collapse the panel, so revealing the row is observable.
    await panel(page).locator("summary").getByText("Documents").click();
    await expect(panel(page)).not.toHaveAttribute("open");
    const row = documentRow(page, SHORT.name);
    await expect(row).toBeHidden();
    const before = await row.evaluate((el) => el.outerHTML);

    await chip(page, SHORT.name).click();
    await main.getByRole("button", { name: "Show in panel" }).first().click();

    await expect(panel(page)).toHaveAttribute("open", "");
    await expect(row).toBeVisible();
    await expect(row).toBeInViewport();
    await expect
      .poll(() => row.evaluate((el) => el.outerHTML), { timeout: 3_000 })
      .not.toBe(before);
  });
});

test.describe("phone", () => {
  test.use({ viewport: PHONE });

  test("row 47: Show in panel on a phone-width viewport opens the drawer and reveals the row", async ({
    page,
  }) => {
    expect(conversationPath).not.toBe("");
    await page.goto(conversationPath);
    const main = page.getByRole("main");
    await expect(main.getByText(ANSWER, { exact: true })).toBeVisible();
    const drawer = page.getByRole("dialog", { name: "Menu" });
    await expect(drawer).toHaveCount(0);

    await chip(page, SHORT.name).click();
    await main.getByRole("button", { name: "Show in panel" }).first().click();

    await expect(drawer).toBeVisible();
    const row = documentRow(drawer, SHORT.name);
    await expect(row).toBeVisible();
    await expect(row).toBeInViewport();
  });
});
