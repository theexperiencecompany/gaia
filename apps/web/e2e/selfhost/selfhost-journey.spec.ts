import { execFileSync } from "node:child_process";
import path from "node:path";
import type {
  FileData,
  InviteCreatedResponse,
  ReadinessResponse,
  TodoListResponse,
} from "@gaia/shared/api/generated";
import {
  type Browser,
  expect,
  type Page,
  type Response,
  request,
  test,
} from "@playwright/test";

/**
 * The self-host journey on a stack `gaia up --code-sandbox` booted from this
 * checkout, with the scripted LLM stub (tools/llm-stub) as the `custom`
 * provider. Serial: each step builds on the instance state the last one left.
 */

const REPO_ROOT = process.env.GAIA_REPO_ROOT;
const STUB_BASE_URL = process.env.LLM_STUB_BASE_URL;
const STUB_MODEL = "gaia-e2e-stub";
const COMPOSER_PLACEHOLDER = "What can I do for you today?";
const CHAT_STREAM_PATH = "/chat-stream";

const ADMIN = {
  email: "admin@selfhost.example",
  password: "admin-e2e-password",
};
const MEMBER = {
  email: "member@selfhost.example",
  password: "member-e2e-password",
};

// 1x1 transparent PNG.
const PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

function requireEnv(name: string, value: string | undefined): string {
  if (!value) throw new Error(`${name} must be set by the selfhost-e2e lane`);
  return value;
}

/** Freeze or thaw the stack's MongoDB through the lane's concept script. */
function mongo(action: "pause" | "unpause"): void {
  const root = requireEnv("GAIA_REPO_ROOT", REPO_ROOT);
  execFileSync(
    "bash",
    [path.join(root, "scripts/ci/selfhost.sh"), "mongo", action],
    { stdio: "inherit" },
  );
}

async function signUp(page: Page, email: string, password: string) {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
}

/** Send one chat message and return the whole streamed response body. */
async function sendChat(page: Page, message: string): Promise<string> {
  await page.goto("/c");
  const composer = page.getByPlaceholder(COMPOSER_PLACEHOLDER, {
    exact: false,
  });
  await expect(composer).toBeVisible();
  const stream = page.waitForResponse(
    (response: Response) =>
      response.url().includes(CHAT_STREAM_PATH) &&
      response.request().method() === "POST",
  );
  await composer.fill(message);
  await composer.press("Enter");
  const response = await stream;
  expect(response.status()).toBe(200);
  return response.text();
}

async function newPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext();
  return context.newPage();
}

test.describe.configure({ mode: "serial" });

test.describe("self-host journey", () => {
  let adminPage: Page;
  let inviteToken: string;

  test.beforeAll(async ({ browser }) => {
    adminPage = await newPage(browser);
  });

  test("the first signup becomes the admin and configures the stub provider", async () => {
    await adminPage.goto("/signup");
    await expect(
      adminPage.getByText(
        "Set up the administrator account for this GAIA instance.",
      ),
    ).toBeVisible();
    await signUp(adminPage, ADMIN.email, ADMIN.password);
    await expect(adminPage).toHaveURL(/\/setup/);

    const saved = await adminPage.request.put(
      "/api/v1/setup/providers/custom",
      {
        data: {
          base_url: requireEnv("LLM_STUB_BASE_URL", STUB_BASE_URL),
          model: STUB_MODEL,
          api_key: "stub",
        },
      },
    );
    expect(saved.status()).toBe(200);

    await adminPage.goto("/setup");
    await expect(adminPage).toHaveURL(/\/c/);
  });

  test("a chat message gets the stub's reply", async () => {
    const reply = "Hello from the self-host stub.";
    await sendChat(adminPage, `[[say:${reply}]]`);
    await expect(adminPage.getByText(reply).first()).toBeVisible();
  });

  test("a scripted tool call creates a todo", async () => {
    const title = "selfhost-e2e todo";
    await sendChat(
      adminPage,
      `[[tool:create_todo {"title":"${title}"}]] [[say:Todo added.]]`,
    );
    await expect(adminPage.getByText("Todo added.").first()).toBeVisible();

    const todos = await adminPage.request.get("/api/v1/todos");
    expect(todos.status()).toBe(200);
    const body = (await todos.json()) as TodoListResponse;
    expect(body.data.map((todo) => todo.title)).toContain(title);
  });

  test("an uploaded image is served from /api/v1/blobs", async () => {
    const uploaded = await adminPage.request.post("/api/v1/upload", {
      multipart: {
        file: { name: "pixel.png", mimeType: "image/png", buffer: PIXEL_PNG },
      },
    });
    expect(uploaded.status()).toBe(201);
    const file = (await uploaded.json()) as FileData;
    const blobUrl = new URL(file.url, adminPage.url());
    expect(blobUrl.pathname).toMatch(/^\/api\/v1\/blobs\//);

    const served = await adminPage.request.get(blobUrl.pathname);
    expect(served.status()).toBe(200);
    expect(served.headers()["content-type"]).toContain("image/png");
    expect(Buffer.from(await served.body()).equals(PIXEL_PNG)).toBe(true);
  });

  test("an invite admits one member and is refused on reuse", async ({
    browser,
    baseURL,
  }) => {
    const created = await adminPage.request.post("/api/v1/members/invites");
    expect(created.status()).toBe(201);
    inviteToken = ((await created.json()) as InviteCreatedResponse).token;

    const memberPage = await newPage(browser);
    await memberPage.goto(`/signup?invite=${encodeURIComponent(inviteToken)}`);
    await expect(
      memberPage.getByText("Join this GAIA instance."),
    ).toBeVisible();
    await signUp(memberPage, MEMBER.email, MEMBER.password);
    await expect(memberPage).toHaveURL(/\/c/);

    const stranger = await request.newContext({ baseURL });
    const reused = await stranger.post("/api/v1/auth/signup", {
      data: {
        email: "second@selfhost.example",
        password: "second-e2e-password",
        invite: inviteToken,
      },
    });
    expect(reused.status()).toBe(403);
    await stranger.dispose();

    const members = await memberPage.request.get("/api/v1/members");
    expect(members.status()).toBe(403);
    const providers = await memberPage.request.put(
      "/api/v1/setup/providers/custom",
      { data: { model: "hijacked" } },
    );
    expect(providers.status()).toBe(403);
    await memberPage.goto("/settings");
    await memberPage.screenshot({
      path: test.info().outputPath("member-settings.png"),
      fullPage: true,
    });
  });

  test("/health/ready reports a paused MongoDB and recovers", async () => {
    const ready = await adminPage.request.get("/health/ready");
    expect(ready.status()).toBe(200);
    expect(((await ready.json()) as ReadinessResponse).status).toBe("ready");

    mongo("pause");
    try {
      await expect
        .poll(
          async () => (await adminPage.request.get("/health/ready")).status(),
          {
            timeout: 60_000,
          },
        )
        .toBe(503);
      const down = (await (
        await adminPage.request.get("/health/ready")
      ).json()) as ReadinessResponse;
      expect(down.status).toBe("not_ready");
      expect(
        down.dependencies.find((dependency) => dependency.name === "mongodb")
          ?.ok,
      ).toBe(false);
    } finally {
      mongo("unpause");
    }
    await expect
      .poll(
        async () => (await adminPage.request.get("/health/ready")).status(),
        {
          timeout: 120_000,
        },
      )
      .toBe(200);
  });

  test("code runs in the local sandbox and returns its real output", async () => {
    // 6*7*1000003 = 42000126: the result appears nowhere in the command text.
    const streamed = await sendChat(
      adminPage,
      `[[tool:bash {"command":"echo $((6*7*1000003))"}]] [[say:Code ran.]]`,
    );
    await expect(adminPage.getByText("Code ran.").first()).toBeVisible();
    expect(streamed).toContain("42000126");
  });
});
