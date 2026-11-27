import { revalidatePath } from "next/cache";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PUBLIC_PAGE_ROUTES } from "@/lib/publicPages";

import { POST } from "./route";

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const TOKEN = "t0ken";

function post(body: string, token?: string): Promise<Response> {
  return POST(
    new Request("https://heygaia.io/api/public-pages/revalidate", {
      method: "POST",
      headers: token === undefined ? {} : { "X-Gaia-Internal": token },
      body,
    }),
  );
}

beforeEach(() => {
  vi.stubEnv("INTERNAL_API_TOKEN", TOKEN);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.mocked(revalidatePath).mockReset();
});

describe("POST /api/public-pages/revalidate", () => {
  it("clears every route that shows the data the API names", async () => {
    const response = await post('{"domain":"workflows"}', TOKEN);

    expect(response.status).toBe(200);
    expect(vi.mocked(revalidatePath).mock.calls).toEqual(
      PUBLIC_PAGE_ROUTES.workflows.map(({ route, type }) => [route, type]),
    );
    expect(await response.json()).toEqual({
      revalidated: PUBLIC_PAGE_ROUTES.workflows,
    });
  });

  it("clears the whole marketplace when integrations change", async () => {
    await post('{"domain":"integrations"}', TOKEN);

    expect(vi.mocked(revalidatePath).mock.calls).toEqual([
      ["/[locale]/(landing)/marketplace", "layout"],
    ]);
  });

  it.each([
    ["no token", undefined],
    ["a wrong token", "not-the-token"],
    ["an empty token", ""],
  ])("refuses a request with %s", async (_name, token) => {
    const response = await post('{"domain":"integrations"}', token);

    expect(response.status).toBe(401);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("refuses every request when the server has no token of its own", async () => {
    vi.stubEnv("INTERNAL_API_TOKEN", "");

    const response = await post('{"domain":"integrations"}', "");

    expect(response.status).toBe(401);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it.each([
    ["data it shows nowhere", '{"domain":"pricing"}'],
    ["an inherited key", '{"domain":"constructor"}'],
    ["no domain", "{}"],
    ["a body that is not JSON", "not json"],
  ])("answers 400 to %s", async (_name, body) => {
    const response = await post(body, TOKEN);

    expect(response.status).toBe(400);
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
