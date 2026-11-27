import { expect, test } from "@playwright/test";

/**
 * HeroUI v3 renders a chip as a 16px-radius, weight-500 box, and its `secondary`
 * variant ships no border at all — so the integration sidebar's tool pills painted
 * a bare `border-1`, whose colour fell through to the near-white gray-200 default.
 * That is the white ring this pins shut: read the computed styles from the real
 * page, so a rendering regression fails here rather than in a review screenshot.
 */
test("an integration's tool chips keep v2's bordered pill look", async ({
  page,
}) => {
  await page.goto("/integrations");

  // The icon rail sits before the main list in the DOM, so the first match opens
  // the integration's right sidebar.
  await page
    .getByRole("button", { name: /notion Icon Notion/ })
    .first()
    .click();

  const sidebar = page
    .getByRole("complementary")
    .filter({ hasText: "Available tools" });
  await expect(
    sidebar.getByRole("heading", { name: "Available tools" }),
  ).toBeVisible();

  const toolChip = sidebar.locator(".chip", {
    hasText: "Add Multiple Page Content",
  });
  await expect(toolChip).toBeVisible();

  const tool = await toolChip.evaluate((el) => {
    const s = getComputedStyle(el);
    return {
      radius: s.borderRadius,
      borderWidth: s.borderWidth,
      borderColor: s.borderColor,
      background: s.backgroundColor,
    };
  });
  expect(tool.radius).toBe("9999px");
  expect(tool.borderWidth).toBe("1px");
  expect(tool.borderColor).toBe("rgba(255, 255, 255, 0.15)");
  expect(tool.background).toBe("rgba(0, 0, 0, 0)");

  // The count badge sets no weight of its own, so it proves the shared chip rule
  // (v3 shipped 500).
  const countChip = sidebar
    .locator(".chip")
    .filter({ hasText: /^\d+$/ })
    .first();
  await expect(countChip).toHaveText(/^\d+$/);
  expect(
    await countChip.evaluate((el) => getComputedStyle(el).fontWeight),
  ).toBe("400");
});
