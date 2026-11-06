import { expect, test, type Page } from "@playwright/test";

// Every refusal here comes from apps/api/routers/documents.py before the
// upload limiter or storage is touched, so none spends one of the member's
// five uploads an hour (sources and documents-lifecycle spend them all). The
// empty panel holds whatever the order: those journeys delete their uploads.
const EMPTY =
  "No documents yet. Upload a .txt, .md, .pdf or .docx to chat over it.";
const HELP = /^PDF, Word \(\.docx\), \.txt or \.md\./;

function panel(page: Page) {
  return page.locator("details");
}

function fileInput(page: Page) {
  return page.locator('input[type="file"]');
}

test("the documents panel shows its empty state, help text and count, and collapses by its summary", async ({
  page,
}) => {
  await page.goto("/chat");
  const summary = panel(page).locator("summary");
  await expect(panel(page)).toHaveAttribute("open", "");
  await expect(summary.getByText("Documents")).toBeVisible();
  await expect(summary.getByText("0", { exact: true })).toBeVisible();
  await expect(page.getByText(HELP)).toBeVisible();
  await expect(page.getByText(EMPTY)).toBeVisible();

  await summary.getByText("Documents").click();
  await expect(panel(page)).not.toHaveAttribute("open");
  await expect(page.getByText(EMPTY)).toBeHidden();
  await expect(page.getByText(HELP)).toBeHidden();

  await summary.getByText("Documents").click();
  await expect(panel(page)).toHaveAttribute("open", "");
  await expect(page.getByText(EMPTY)).toBeVisible();
});

function documentsSkeleton(page: Page) {
  return panel(page).locator('[data-skeleton="documents"]');
}

// The list request is held open until the assertions have run, so "while
// loading" is a state the test controls, not a race it hopes to win.
test("the documents panel shows skeleton rows, no count and no empty line while its list loads", async ({
  page,
}) => {
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") await held;
    await route.fallback();
  });
  const requested = page.waitForRequest(
    (r) => r.method() === "GET" && r.url().endsWith("/api/documents"),
  );

  await page.goto("/chat");
  await requested;
  const summary = panel(page).locator("summary");
  const skeleton = documentsSkeleton(page);
  await expect(skeleton).toBeVisible();
  await expect(skeleton.locator("[data-skeleton-row]")).toHaveCount(3);
  await expect(summary.getByText("0", { exact: true })).toHaveCount(0);
  await expect(page.getByText(EMPTY)).toHaveCount(0);

  release();
  await expect(skeleton).toHaveCount(0);
  await expect(page.getByText(EMPTY)).toBeVisible();
  await expect(summary.getByText("0", { exact: true })).toBeVisible();
});

test("a failed documents list clears the skeleton and shows neither a count nor the empty line", async ({
  page,
}) => {
  await page.route("**/api/documents", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ status: 500, json: { detail: "boom" } })
      : route.fallback(),
  );
  const failed = page.waitForResponse(
    (r) =>
      r.request().method() === "GET" &&
      r.url().endsWith("/api/documents") &&
      r.status() === 500,
  );

  await page.goto("/chat");
  await failed;
  const summary = panel(page).locator("summary");
  await expect(documentsSkeleton(page)).toHaveCount(0);
  await expect(page.getByText(EMPTY)).toHaveCount(0);
  await expect(summary.getByText("0", { exact: true })).toHaveCount(0);
  await expect(summary.getByRole("button", { name: "+ Upload" })).toBeVisible();
});

test.describe("on a short screen", () => {
  test.use({ viewport: { width: 1280, height: 480 } });

  test("the documents panel starts closed", async ({ page }) => {
    await page.goto("/chat");
    // At 500 px tall or less the sidebar lives in the drawer.
    await page.getByRole("button", { name: "Open menu" }).click();
    const drawer = page.getByRole("dialog", { name: "Menu" });
    const summary = drawer.locator("summary");
    await expect(summary.getByText("Documents")).toBeVisible();
    await expect(drawer.locator("details")).not.toHaveAttribute("open");
    await expect(drawer.getByText(EMPTY)).toBeHidden();
  });
});

const REFUSALS = [
  {
    label: "an unsupported type",
    file: { name: "tool.exe", size: 16 },
    message: "supported files: .txt, .md, .pdf, .docx",
  },
  {
    label: "a PDF over 5 MB",
    file: { name: "large.pdf", size: 5 * 1024 * 1024 + 1 },
    message: "file exceeds 5120 KB",
  },
  {
    label: "a text file over 256 KB",
    file: { name: "large.txt", size: 256 * 1024 + 1 },
    message: "file exceeds 256 KB",
  },
];

for (const { label, file, message } of REFUSALS) {
  test(`uploading ${label} is refused in the panel`, async ({ page }) => {
    await page.goto("/chat");
    await expect(page.getByText(EMPTY)).toBeVisible();

    await fileInput(page).setInputFiles({
      name: file.name,
      mimeType: "application/octet-stream",
      buffer: Buffer.alloc(file.size, "a"),
    });
    await expect(panel(page).getByText(message)).toBeVisible();
    await expect(page.getByText(EMPTY)).toBeVisible();
    const summary = panel(page).locator("summary");
    await expect(summary.getByText("0", { exact: true })).toBeVisible();
    const upload = summary.getByRole("button", { name: "+ Upload" });
    await expect(upload).toBeEnabled();
  });
}

// The refusal is stubbed, so the API's limiter never counts it. A 422's
// validation array reads "<field>: <msg>" joined by "; ", never the status.
test("an upload refused with a validation 422 shows each field and message", async ({
  page,
}) => {
  await page.route("**/api/documents", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          json: {
            detail: [
              { loc: ["body", "file"], msg: "Field required", type: "missing" },
              { loc: ["body"], msg: "Body is malformed", type: "value_error" },
            ],
          },
        })
      : route.fallback(),
  );
  await page.goto("/chat");
  await expect(page.getByText(EMPTY)).toBeVisible();

  await fileInput(page).setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("refused before it is stored"),
  });
  await expect(
    panel(page).getByText("file: Field required; Body is malformed", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(panel(page).getByText(/API 422/)).toHaveCount(0);
  await expect(page.getByText(EMPTY)).toBeVisible();
});

// The listing is stubbed: the e2e stack cannot store an upload, and this test
// is about geometry only. Each delete target spans its own row and no more.
test("document delete targets are 44 px wide and never overlap a neighbour", async ({
  page,
}) => {
  const docs = [1, 2, 3].map((n) => ({
    id: `00000000-0000-4000-8000-00000000000${n}`,
    filename: `notes-${n}.txt`,
    mime_type: "text/plain",
    size_bytes: 10,
    status: "ready",
    error: null,
    created_at: "2026-10-28T10:00:00Z",
    updated_at: "2026-10-28T10:00:00Z",
  }));
  await page.route("**/api/documents", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: docs })
      : route.fallback(),
  );
  await page.goto("/chat");
  const targets = page.getByRole("button", { name: /^Delete notes-/ });
  await expect(targets).toHaveCount(3);
  const boxes = [];
  for (let i = 0; i < 3; i++) boxes.push(await targets.nth(i).boundingBox());
  for (const box of boxes) expect(box!.width).toBeGreaterThanOrEqual(44);
  for (let i = 1; i < 3; i++) {
    expect(boxes[i]!.y).toBeGreaterThanOrEqual(
      boxes[i - 1]!.y + boxes[i - 1]!.height,
    );
  }
});
