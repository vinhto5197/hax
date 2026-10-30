import { expect, test } from "@playwright/test";

// The labels and hints ModelSelect.tsx offers. Nothing here sends a message
// or uploads, so the picker's choice never reaches the API.
const HINTS = [
  ["Default", "Fast and inexpensive"],
  ["Haiku", "Fastest, cheapest"],
  ["Sonnet", "Stronger reasoning, slower"],
  ["Opus", "Strongest, slowest, costs the most"],
] as const;

test("every model option carries a hint, and the chosen one shows beside the picker", async ({
  page,
}) => {
  await page.goto("/chat");
  const picker = page.getByRole("combobox");
  const options = picker.locator("option");
  await expect(options).toHaveCount(HINTS.length);
  for (let i = 0; i < HINTS.length; i++) {
    await expect(options.nth(i)).toHaveAttribute("title", /\S/);
  }

  for (const [label, hint] of HINTS) {
    await picker.selectOption({ label });
    await expect(page.getByText(hint, { exact: true })).toBeVisible();
    await expect(picker).toHaveAccessibleDescription(hint);
  }
});

test("on a phone the hint is a caption below the picker", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/chat");
  const picker = page.getByRole("combobox");
  const [, hint] = HINTS[0];
  const caption = page.getByText(hint, { exact: true });
  await expect(caption).toBeVisible();

  const pickerBox = await picker.boundingBox();
  const captionBox = await caption.boundingBox();
  expect(pickerBox).not.toBeNull();
  expect(captionBox).not.toBeNull();
  expect(captionBox!.y).toBeGreaterThanOrEqual(
    pickerBox!.y + pickerBox!.height,
  );
});
