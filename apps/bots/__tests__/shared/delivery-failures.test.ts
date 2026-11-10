/**
 * Delivery-failure reporting through the real GaiaClient, with only the axios
 * transport faked: what a lost reply sends to the API, and what it must not.
 */
import { Readable } from "node:stream";
import {
  GaiaClient,
  handleStreamingChat,
  STREAMING_DEFAULTS,
} from "@gaia/shared/bots";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createDeliveryFailureReporter,
  describeErrorForAlert,
} from "../../../../libs/shared/ts/src/bots/delivery-failures";

const REPORT_PATH = "/api/v1/bot/delivery-failures";

function frames(...payloads: object[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

/** A real GaiaClient: chat streams replay sseBody, every other POST resolves. */
function gaiaWith(sseBody: string) {
  const post = vi.fn(async (url: string) =>
    url === REPORT_PATH
      ? { data: { status: "queued" } }
      : { data: Readable.from([sseBody]) },
  );
  const gaia = new GaiaClient("http://gaia.test", "bot-key", "http://web.test");
  (gaia as unknown as { client: unknown }).client = { post };
  return { gaia, post };
}

async function runFailedTurn(gaia: GaiaClient): Promise<string[]> {
  const errors: string[] = [];
  await handleStreamingChat(
    gaia,
    {
      message: "summarise my inbox",
      platform: "telegram",
      platformUserId: "5550001",
      channelId: "5550001",
    },
    async () => undefined,
    async () => async () => undefined,
    async () => undefined,
    async (formattedError) => {
      errors.push(formattedError);
    },
    STREAMING_DEFAULTS.telegram,
  );
  return errors;
}

function reportsSent(post: ReturnType<typeof vi.fn>) {
  return post.mock.calls.filter(([url]) => url === REPORT_PATH);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a chat turn that fails", () => {
  it("reports a lost reply to the API, authenticated as the platform's bot", async () => {
    const { gaia, post } = gaiaWith(frames({ error: "executor crashed" }));

    const errors = await runFailedTurn(gaia);

    expect(errors).toHaveLength(1);
    await vi.waitFor(() => expect(reportsSent(post)).toHaveLength(1));
    const [[, body, config]] = reportsSent(post);
    expect(body).toEqual({
      kind: "reply_failed",
      reason: "unknown",
      error_message: "chat: executor crashed",
      destination_id: "5550001",
      platform: "telegram",
      occurred_at: expect.any(String),
    });
    expect(config.headers).toMatchObject({
      "X-Bot-API-Key": "bot-key",
      "X-Bot-Platform": "telegram",
    });
  });

  it("does not alert on a plan refusal: the user got the upgrade prompt", async () => {
    const { gaia, post } = gaiaWith(frames({ error: "plan_required" }));

    await runFailedTurn(gaia);
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(reportsSent(post)).toHaveLength(0);
  });
});

describe("createDeliveryFailureReporter", () => {
  it("logs a report the API refused instead of throwing into the delivery path", async () => {
    const gaia = new GaiaClient("http://gaia.test", "k", "http://web.test");
    (gaia as unknown as { client: unknown }).client = {
      post: vi.fn(async () => {
        throw Object.assign(new Error("Request failed"), {
          response: { status: 503, data: {} },
        });
      }),
    };
    const stderr = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    const report = createDeliveryFailureReporter(gaia, "discord");
    expect(() =>
      report({ kind: "send_failed", reason: "server_error" }),
    ).not.toThrow();

    await vi.waitFor(() =>
      expect(stderr).toHaveBeenCalledWith(
        expect.stringContaining("delivery_failure_report_failed"),
      ),
    );
  });
});

describe("describeErrorForAlert", () => {
  it("strips URLs, keeps the status, and fits the API's 500-character limit after the prefix", () => {
    const error = Object.assign(
      new Error(
        `Call to https://api.telegram.org/bot1:TOKEN/sendMessage failed ${"x".repeat(600)}`,
      ),
      { response: { status: 403 } },
    );

    const text = describeErrorForAlert(error, "/todo");

    expect(text.startsWith("/todo: HTTP 403: Call to <url> failed")).toBe(true);
    expect(text).not.toContain("TOKEN");
    expect(text).toHaveLength(500);
  });
});

describe("a reporter whose client throws synchronously", () => {
  it("still never throws into the delivery path", async () => {
    const gaia = {
      reportDeliveryFailure: () => {
        throw new TypeError("client not ready");
      },
    } as unknown as GaiaClient;
    const stderr = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    const report = createDeliveryFailureReporter(gaia, "slack");
    expect(() =>
      report({ kind: "reply_failed", reason: "unknown" }),
    ).not.toThrow();

    await vi.waitFor(() =>
      expect(stderr).toHaveBeenCalledWith(
        expect.stringContaining("delivery_failure_report_failed"),
      ),
    );
  });
});
