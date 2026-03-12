// apps/web/src/features/recording/types/__tests__/scenario.test.ts
import { describe, it, expect } from "vitest";
import {
  ScenarioSchema,
  UserMessageStateSchema,
  BotMessageStateSchema,
  LoadingStateSchema,
  PauseStateSchema,
} from "../scenario";

describe("ScenarioSchema", () => {
  it("parses a valid minimal scenario", () => {
    const input = {
      id: "test",
      title: "Test",
      states: [{ type: "user_message", text: "Hello" }],
    };
    const result = ScenarioSchema.safeParse(input);
    expect(result.success).toBe(true);
  });

  it("applies default viewport 390x844", () => {
    const input = {
      id: "test",
      title: "Test",
      states: [{ type: "user_message", text: "Hi" }],
    };
    const result = ScenarioSchema.parse(input);
    expect(result.viewport).toEqual({ width: 390, height: 844 });
  });

  it("accepts custom viewport", () => {
    const input = {
      id: "test",
      title: "Test",
      viewport: { width: 1920, height: 1080 },
      states: [{ type: "user_message", text: "Hi" }],
    };
    const result = ScenarioSchema.parse(input);
    expect(result.viewport).toEqual({ width: 1920, height: 1080 });
  });

  it("rejects empty states array", () => {
    const result = ScenarioSchema.safeParse({
      id: "test",
      title: "Test",
      states: [],
    });
    expect(result.success).toBe(false);
  });

  it("rejects unknown state type", () => {
    const result = ScenarioSchema.safeParse({
      id: "test",
      title: "Test",
      states: [{ type: "unknown_type", text: "Hi" }],
    });
    expect(result.success).toBe(false);
  });

  it("rejects missing id", () => {
    const result = ScenarioSchema.safeParse({
      title: "Test",
      states: [{ type: "user_message", text: "Hi" }],
    });
    expect(result.success).toBe(false);
  });

  it("applies default dark theme", () => {
    const result = ScenarioSchema.parse({
      id: "test",
      title: "Test",
      states: [{ type: "user_message", text: "Hi" }],
    });
    expect(result.settings?.theme).toBe("dark");
  });
});

describe("UserMessageStateSchema", () => {
  it("applies default typingSpeed of 50", () => {
    const result = UserMessageStateSchema.parse({
      type: "user_message",
      text: "Hi",
    });
    expect(result.typingSpeed).toBe(50);
  });

  it("applies default pauseAfter of 300", () => {
    const result = UserMessageStateSchema.parse({
      type: "user_message",
      text: "Hi",
    });
    expect(result.pauseAfter).toBe(300);
  });

  it("accepts custom typingSpeed", () => {
    const result = UserMessageStateSchema.parse({
      type: "user_message",
      text: "Hi",
      typingSpeed: 100,
    });
    expect(result.typingSpeed).toBe(100);
  });

  it("rejects empty text", () => {
    const result = UserMessageStateSchema.safeParse({
      type: "user_message",
      text: "",
    });
    expect(result.success).toBe(false);
  });
});

describe("BotMessageStateSchema", () => {
  it("applies default streamingSpeed of 15", () => {
    const result = BotMessageStateSchema.parse({
      type: "bot_message",
      text: "Hello",
    });
    expect(result.streamingSpeed).toBe(15);
  });

  it("accepts tool_data array", () => {
    const result = BotMessageStateSchema.parse({
      type: "bot_message",
      text: "Hello",
      tool_data: [
        {
          tool_name: "calendar_options",
          tool_category: "gcal",
          data: [],
          timestamp: null,
        },
      ],
    });
    expect(result.tool_data).toHaveLength(1);
  });

  it("accepts follow_up_actions", () => {
    const result = BotMessageStateSchema.parse({
      type: "bot_message",
      text: "Hello",
      follow_up_actions: ["Option A", "Option B"],
    });
    expect(result.follow_up_actions).toEqual(["Option A", "Option B"]);
  });
});

describe("LoadingStateSchema", () => {
  it("applies default duration of 1500", () => {
    const result = LoadingStateSchema.parse({
      type: "loading",
      text: "Loading...",
    });
    expect(result.duration).toBe(1500);
  });

  it("accepts toolInfo", () => {
    const result = LoadingStateSchema.parse({
      type: "loading",
      text: "Searching...",
      toolInfo: { toolCategory: "search", showCategory: true },
    });
    expect(result.toolInfo?.toolCategory).toBe("search");
  });
});

describe("PauseStateSchema", () => {
  it("rejects duration below 100ms", () => {
    const result = PauseStateSchema.safeParse({
      type: "pause",
      duration: 50,
    });
    expect(result.success).toBe(false);
  });

  it("accepts 100ms pause", () => {
    const result = PauseStateSchema.safeParse({
      type: "pause",
      duration: 100,
    });
    expect(result.success).toBe(true);
  });
});
