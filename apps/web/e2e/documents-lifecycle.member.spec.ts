import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

// A document's whole life in the panel, against the real API, the worker and
// the S3 stand-in, with the fake model's embeddings.
//
// Upload budget: the member may make 5 accepted uploads an hour (a code
// constant; Redis db 15 is flushed per run). This file makes exactly 3 (a
// ready file reused for download, order and delete; a non-UTF-8 file; a
// slow-embed file), and sources.member exactly 2; no other journey makes an
// accepted upload. A sixth would be a 429.
//
// Serial, in this order: each step builds on the documents of the one before.
test.describe.configure({ mode: "serial" });

const API_URL = "http://localhost:8001";
const WEB_ORIGIN = "http://localhost:3001";
const DESKTOP = { width: 1280, height: 800 };

const stamp = `${Date.now()}`;
const READY = {
  name: `lifecycle-ready-${stamp}.txt`,
  bytes: Buffer.from("Lifecycle notes: the bread rises overnight.\n", "utf-8"),
};
const BROKEN = {
  name: `lifecycle-broken-${stamp}.txt`,
  bytes: Buffer.from(
    Array.from({ length: 64 }, () => [0xff, 0xfe, 0xfd]).flat(),
  ),
};
// The marker makes the fake's embeddings wait 8 s, holding this one in flight.
const SLOW = {
  name: `lifecycle-slow-${stamp}.txt`,
  bytes: Buffer.from(
    "slow-embed: this document stays in flight a while.\n",
    "utf-8",
  ),
};
const ALL = [READY, BROKEN, SLOW];

test.use({ viewport: DESKTOP });

function panel(page: Page) {
  return page.locator("details");
}

function rows(page: Page) {
  return panel(page).getByRole("listitem");
}

function row(page: Page, filename: string) {
  return rows(page).filter({ hasText: filename });
}

async function upload(page: Page, file: { name: string; bytes: Buffer }) {
  await page.locator('input[type="file"]').setInputFiles({
    name: file.name,
    mimeType: "text/plain",
    buffer: file.bytes,
  });
}

async function waitSettled(page: Page, filename: string) {
  await expect(row(page, filename)).toBeVisible();
  await expect(row(page, filename).getByText("Processing…")).toHaveCount(0, {
    timeout: 30_000,
  });
}

function isListRequest(url: string, method: string) {
  return method === "GET" && new URL(url).pathname === "/api/documents";
}

// afterAll has no page fixture: a context of its own, signed in as the
// project's member.
test.afterAll(async ({ browser }, testInfo) => {
  const context = await browser.newContext({
    storageState: testInfo.project.use.storageState,
  });
  const listing = await context.request.get(`${API_URL}/api/documents`);
  expect(listing.status()).toBe(200);
  const ours = new Set(ALL.map((f) => f.name));
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

test("rows 35, 69, 36: uploading shows Uploading…, then a pending row reading Processing… with the hint Usually under a minute, which turns ready within 30 s, and the panel then stops polling", async ({
  page,
}) => {
  // Hold the upload 1 s so the brief Uploading… state is certainly seen.
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await new Promise((resolve) => setTimeout(resolve, 1_000));
    await route.continue();
  });
  await page.goto("/chat");
  const summary = panel(page).locator("summary");
  await expect(summary.getByRole("button", { name: "+ Upload" })).toBeVisible();

  await upload(page, READY);
  await expect(panel(page).getByText("Uploading…")).toBeVisible();

  const pending = row(page, READY.name);
  await expect(pending).toBeVisible();
  await expect(pending.getByText("Processing…")).toBeVisible();
  await expect(pending.getByTitle("Usually under a minute")).toBeVisible();
  await expect(panel(page).getByText("Uploading…")).toHaveCount(0);
  await expect(summary.getByRole("button", { name: "+ Upload" })).toBeVisible();

  // Same page, no navigation: the upload answers 'pending', so only a poll
  // of the list can bring 'ready' here.
  let listRequests = 0;
  page.on("request", (request) => {
    if (isListRequest(request.url(), request.method())) listRequests += 1;
  });
  await expect(pending.getByText("ready", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(pending.getByText("Processing…")).toHaveCount(0);
  expect(listRequests).toBeGreaterThan(0);

  // Nothing else is in flight, so nothing should poll in the next 6 s.
  const polledBeforeSettling = listRequests;
  await page.waitForTimeout(6_000);
  expect(listRequests).toBe(polledBeforeSettling);
});

test("row 37: a non-UTF-8 .txt ends failed, and tapping it shows the file is not valid UTF-8 text", async ({
  page,
}) => {
  await page.goto("/chat");
  await upload(page, BROKEN);
  await waitSettled(page, BROKEN.name);

  const failed = row(page, BROKEN.name);
  await expect(
    failed.getByText("the file is not valid UTF-8 text"),
  ).toHaveCount(0);
  // The filename is the download button; the status is what a tap opens.
  await failed.getByRole("button", { name: /failed/i }).click();
  await expect(
    panel(page).getByText("the file is not valid UTF-8 text"),
  ).toBeVisible();
});

test("row 38: with one failed, one in flight and one ready, the panel orders them failed, in flight, ready", async ({
  page,
}) => {
  await page.goto("/chat");
  await upload(page, SLOW);
  await expect(row(page, SLOW.name).getByText("Processing…")).toBeVisible();

  const names = async () =>
    (await rows(page).allTextContents())
      .map((text) => ALL.find((f) => text.includes(f.name))?.name)
      .filter((name) => name !== undefined);
  await expect.poll(names).toEqual([BROKEN.name, SLOW.name, READY.name]);
  // Still in flight when the order was read.
  await expect(row(page, SLOW.name).getByText("Processing…")).toBeVisible();
});

test("row 41: Download <filename> downloads the uploaded bytes", async ({
  page,
}) => {
  await page.goto("/chat");
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: `Download ${READY.name}` }).click();
  const download = await downloading;
  const saved = await readFile((await download.path())!);
  expect(saved.equals(READY.bytes)).toBe(true);
});

test("row 40: Delete <filename> with its confirm accepted removes the row", async ({
  page,
}) => {
  await page.goto("/chat");
  await expect(row(page, READY.name)).toBeVisible();

  let confirmed = false;
  page.once("dialog", (dialog) => {
    confirmed = dialog.type() === "confirm";
    void dialog.accept();
  });
  await page.getByRole("button", { name: `Delete ${READY.name}` }).click();

  await expect(row(page, READY.name)).toHaveCount(0);
  expect(confirmed).toBe(true);
  await page.reload();
  await expect(row(page, BROKEN.name)).toBeVisible();
  await expect(row(page, READY.name)).toHaveCount(0);
});
