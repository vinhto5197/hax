import { expect, test, type Page } from "@playwright/test";

const PHONE = { width: 390, height: 844 };
// The hints ModelSelect.tsx lists, in option order.
const HINTS = [
  "Fast and inexpensive",
  "Fastest, cheapest",
  "Stronger reasoning, slower",
  "Strongest, slowest, costs the most",
];

function picker(page: Page) {
  return page.getByRole("combobox");
}

test("each model option carries its hint, and the chosen one describes the picker", async ({
  page,
}) => {
  await page.goto("/chat");
  const options = picker(page).locator("option");
  await expect(options).toHaveCount(HINTS.length);
  for (let i = 0; i < HINTS.length; i++) {
    await expect(options.nth(i)).toHaveAttribute("title", HINTS[i]);
  }

  await expect(picker(page)).toHaveAccessibleDescription(HINTS[0]);
  await picker(page).selectOption("claude-opus-4-8");
  await expect(picker(page)).toHaveAccessibleDescription(HINTS[3]);
  await expect(page.getByText(HINTS[3], { exact: true })).toBeVisible();
  await expect(page.getByText(HINTS[0], { exact: true })).toHaveCount(0);
});

test("on a desktop the chosen option's hint sits beside the picker", async ({
  page,
}) => {
  await page.goto("/chat");
  const hint = page.getByText(HINTS[0], { exact: true });
  await expect(hint).toBeVisible();
  const select = (await picker(page).boundingBox())!;
  const line = (await hint.boundingBox())!;
  expect(line.x).toBeGreaterThanOrEqual(select.x + select.width - 1);
  expect(line.y).toBeLessThan(select.y + select.height);
  expect(line.y + line.height).toBeGreaterThan(select.y);
});

test.describe("phone", () => {
  test.use({ viewport: PHONE });

  test("at 390x844 the chosen option's hint is a caption below the picker", async ({
    page,
  }) => {
    await page.goto("/chat");
    const hint = page.getByText(HINTS[0], { exact: true });
    await expect(hint).toBeVisible();
    const select = (await picker(page).boundingBox())!;
    const line = (await hint.boundingBox())!;
    expect(line.y).toBeGreaterThanOrEqual(select.y + select.height - 1);
    expect(line.x + line.width).toBeLessThanOrEqual(PHONE.width);
  });
});
