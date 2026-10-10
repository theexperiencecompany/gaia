import { expect, type Request, test } from "@playwright/test";

const CODE = "e2e-connect-code";

/**
 * Bot connect links: opening one must not spend its single-use code (link
 * previews open it too), and pressing Continue must POST the code to the API.
 * The API is intercepted, so this proves the page and the form, not OAuth.
 */
test.describe("connect link", () => {
  test("opening the link spends nothing; Continue posts the code", async ({
    page,
  }) => {
    const posts: Request[] = [];
    await page.route("**/integrations/connect-link", async (route) => {
      posts.push(route.request());
      await route.fulfill({ status: 200, body: "intercepted" });
    });

    await page.goto(`/connect/${CODE}`);

    // The code moved into a cookie: the page analytics records is bare /connect.
    await expect(page).toHaveURL(/\/connect$/);
    await expect(
      page.getByRole("heading", { name: "Connect your integration" }),
    ).toBeVisible();
    expect(posts).toHaveLength(0);
    // The locale layout wraps every page in #app-root alongside its third-party
    // analytics scripts; this page holds a live code, so it renders outside it.
    await expect(page.locator("#app-root")).toHaveCount(0);

    await page.getByRole("button", { name: "Continue" }).click();

    await expect.poll(() => posts.length).toBe(1);
    expect(posts[0].method()).toBe("POST");
    expect(posts[0].postData()).toBe(`code=${CODE}`);
  });
});
