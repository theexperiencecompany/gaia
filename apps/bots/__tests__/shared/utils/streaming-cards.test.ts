/**
 * Tool cards on the live bot stream (`handleStreamingChat`).
 *
 * The backend forwards card-worthy `tool_data` entries as their own frames. The
 * streamer must deliver each one deterministically — out of band, as a card the
 * adapter renders natively — and report what the user was shown once the turn's
 * conversation id is known, so the agent's record matches the user's screen.
 * Before this, a connect link reached the user only if every LLM hop copied the
 * URL verbatim; a paraphrase left "use the links above" with nothing above.
 *
 * Only the GaiaClient stream source and the platform send callbacks are faked;
 * the streamer, the card builders and the text renderer are real.
 */
import type { ToolDataEntry } from "@gaia/shared";
import type { ReportedBotCard } from "@gaia/shared/api/generated";
import {
  type Card,
  type GaiaClient,
  handleStreamingChat,
  STREAMING_DEFAULTS,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";

const CONVERSATION_ID = "conv-cards";
const CONNECT_URL = "https://gaia.test/connect/abc123";

const CONNECT_ENTRY: ToolDataEntry = {
  tool_name: "integration_connection_required",
  tool_category: "integration",
  data: {
    integration_id: "posthog",
    integration_name: "PostHog",
    message: "Your PostHog connection expired. Sign in again to keep using it.",
    expired: true,
    connect_url: CONNECT_URL,
    connect_url_valid_minutes: 60,
  },
};

type Step = string | { toolData: ToolDataEntry };

interface Reported {
  conversationId: string;
  cards: ReportedBotCard[];
}

function cardStreamingGaia(steps: Step[], reports: Reported[]): GaiaClient {
  return {
    chatStream: async (
      _request: unknown,
      onChunk: (text: string) => void | Promise<void>,
      onDone: (
        fullText: string,
        conversationId: string,
      ) => void | Promise<void>,
      _onError: unknown,
      onToolData?: (entry: ToolDataEntry) => void | Promise<void>,
    ) => {
      let full = "";
      for (const step of steps) {
        if (typeof step === "string") {
          full += step;
          await onChunk(step);
          continue;
        }
        await onToolData?.(step.toolData);
      }
      await onDone(full, CONVERSATION_ID);
      return full;
    },
    reportCardsDelivered: async (
      _ctx: unknown,
      conversationId: string,
      cards: ReportedBotCard[],
    ) => {
      reports.push({ conversationId, cards });
    },
    createLinkToken: async () => ({ authUrl: "https://gaia.test/link" }),
  } as unknown as GaiaClient;
}

async function runTurn(
  steps: Step[],
  sendCard: (card: Card) => Promise<void>,
): Promise<{ bubbles: string[]; reports: Reported[] }> {
  const bubbles: string[] = [];
  const reports: Reported[] = [];
  await handleStreamingChat(
    cardStreamingGaia(steps, reports),
    {
      message: "pull the fundraising numbers",
      platform: "telegram",
      platformUserId: "u1",
      channelId: "c1",
    },
    async (text) => {
      bubbles.push(text);
    },
    async (text) => {
      bubbles.push(text);
      return async (updated) => {
        bubbles.push(updated);
      };
    },
    async () => {
      throw new Error("auth path is not exercised here");
    },
    async (error) => {
      throw new Error(`unexpected stream error: ${error}`);
    },
    STREAMING_DEFAULTS.telegram,
    undefined,
    undefined,
    undefined,
    sendCard,
  );
  return { bubbles, reports };
}

describe("handleStreamingChat — tool cards", () => {
  it("delivers a connect prompt as a card with a real link button and reports it", async () => {
    const cards: Card[] = [];
    const { reports } = await runTurn(
      ["I need PostHog to finish this.", { toolData: CONNECT_ENTRY }],
      async (card) => {
        cards.push(card);
      },
    );

    expect(cards).toHaveLength(1);
    expect(cards[0]?.actions).toEqual([
      { kind: "link", label: "Reconnect PostHog", url: CONNECT_URL },
    ]);

    expect(reports).toHaveLength(1);
    expect(reports[0]?.conversationId).toBe(CONVERSATION_ID);
    expect(reports[0]?.cards).toHaveLength(1);
    expect(reports[0]?.cards[0]?.tool_name).toBe(
      "integration_connection_required",
    );
    expect(reports[0]?.cards[0]?.delivered).toBe(true);
    // The record the agent reads must carry the exact link the user can tap.
    expect(reports[0]?.cards[0]?.text).toContain(CONNECT_URL);
  });

  it("reports a card the platform refused as not delivered", async () => {
    const { reports } = await runTurn(
      [{ toolData: CONNECT_ENTRY }],
      async () => {
        throw new Error("Bad Request: chat not found");
      },
    );

    expect(reports[0]?.cards).toEqual([
      expect.objectContaining({
        tool_name: "integration_connection_required",
        delivered: false,
      }),
    ]);
  });

  it("delivers nothing and reports nothing for a tool with no bot card", async () => {
    const cards: Card[] = [];
    const { reports } = await runTurn(
      [
        "Here is the weather.",
        { toolData: { tool_name: "weather_data", data: { location: "Pune" } } },
      ],
      async (card) => {
        cards.push(card);
      },
    );

    expect(cards).toEqual([]);
    expect(reports).toEqual([]);
  });

  it("only surfaces an approval while it is still pending", async () => {
    const approval = (status: string): ToolDataEntry => ({
      tool_name: "approval_request",
      tool_category: "hil",
      data: {
        approval_id: "a1",
        tool_call_id: "t1",
        gated_tool_name: "gmail_send",
        integration_name: "Gmail",
        summary: "Send the deck to Vee",
        args_preview: {},
        status,
        feedback: null,
        timeout_seconds: 3600,
      },
    });
    const cards: Card[] = [];
    await runTurn(
      [{ toolData: approval("pending") }, { toolData: approval("approved") }],
      async (card) => {
        cards.push(card);
      },
    );

    expect(cards).toHaveLength(1);
  });
});
