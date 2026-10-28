import { expect, test, type Page } from "@playwright/test";

// Every refusal here comes from apps/api/routers/documents.py before the
// upload limiter or storage is touched; a file that passed validation would
// spend an upload slot and then fail at the unreachable storage.
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
