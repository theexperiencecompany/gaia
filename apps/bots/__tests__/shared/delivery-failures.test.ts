/**
 * Delivery-failure reporting through the real GaiaClient, with only the axios
 * transport faked: what a lost reply sends to the API, and what it must not.
 */
import { GaiaClient } from "@gaia/shared/bots";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createDeliveryFailureReporter,
  describeErrorForAlert,
} from "../../../../libs/shared/ts/src/bots/delivery-failures";
import { HarnessAdapter } from "../../harness/src/adapter";
import { resolveEmulation } from "../../harness/src/emulation";
import { TranscriptRecorder } from "../../harness/src/transcript";
import { injectGaia } from "./helpers/inject-gaia";

const REPORT_PATH = "/api/v1/bot/delivery-failures";
const MESSAGES_PATH = "/api/v1/bot/messages";

/** An axios-shaped refusal, as the transport throws it. */
function httpError(status: number, data: object = {}): Error {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data },
  });
}

/** A real GaiaClient whose transport refuses every post with refusal; reports and link tokens resolve. */
function gaiaRefusingPosts(refusal: Error) {
  const post = vi.fn(async (url: string) => {
    if (url === REPORT_PATH) return { data: { status: "queued" } };
    if (url === MESSAGES_PATH) throw refusal;
    return { data: { token: "tok", auth_url: "https://gaia.test/link" } };
  });
  const get = vi.fn(async () => ({
    data: { authenticated: false, platform: "telegram" },
  }));
  const gaia = new GaiaClient("http://gaia.test", "bot-key", "http://web.test");
  (gaia as unknown as { client: unknown }).client = { post, get };
  return { gaia, post };
}

/** Posts one message through the real post path of a telegram-emulating harness. */
async function postRefusedMessage(
  gaia: GaiaClient,
): Promise<TranscriptRecorder> {
  const recorder = new TranscriptRecorder("telegram");
  const adapter = new HarnessAdapter(resolveEmulation("telegram"), recorder);
  injectGaia(adapter, gaia, createDeliveryFailureReporter(gaia, "telegram"));
  await adapter.simulateMessage("5550001", "summarise my inbox");
  return recorder;
}

function reportsSent(post: ReturnType<typeof vi.fn>) {
  return post.mock.calls.filter(([url]) => url === REPORT_PATH);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a message the API refuses", () => {
  it("reports a lost reply to the API, authenticated as the platform's bot", async () => {
    const { gaia, post } = gaiaRefusingPosts(httpError(500));

    const recorder = await postRefusedMessage(gaia);

    expect(recorder.getEvents().filter((e) => e.type === "send")).toHaveLength(
      1,
    );
    await vi.waitFor(() => expect(reportsSent(post)).toHaveLength(1));
    const [[, body, config]] = reportsSent(post);
    expect(body).toEqual({
      kind: "reply_failed",
      reason: "server_error",
      error_message: "chat: HTTP 500: API error: 500",
      destination_id: "5550001",
      platform: "telegram",
      occurred_at: expect.any(String),
    });
    expect(config.headers).toMatchObject({
      "X-Bot-API-Key": "bot-key",
      "X-Bot-Platform": "telegram",
    });
  });

  it("does not alert on an account that is not linked: the user got the link prompt", async () => {
    const { gaia, post } = gaiaRefusingPosts(
      httpError(401, { code: "NOT_AUTHENTICATED" }),
    );

    const recorder = await postRefusedMessage(gaia);
    await new Promise((resolve) => setTimeout(resolve, 10));

    const sent = recorder.getEvents().filter((e) => e.type === "send");
    expect(sent).toEqual([
      expect.objectContaining({
        text: expect.stringContaining("https://gaia.test/link"),
      }),
    ]);
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
