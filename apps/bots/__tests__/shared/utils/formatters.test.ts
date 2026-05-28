import type { Conversation, Todo, Workflow } from "@gaia/shared";
import {
  buildAuthLinkMessage,
  convertToDiscordMarkdown,
  convertToSlackMrkdwn,
  convertToTelegramHtml,
  convertToWhatsAppMarkdown,
  escapeHtml,
  formatBotError,
  formatConversation,
  formatConversationList,
  formatTodo,
  formatTodoList,
  formatWorkflow,
  formatWorkflowList,
  GaiaApiError,
  htmlToPlainText,
  PLATFORM_MARKDOWN,
  renderForPlatform,
} from "@gaia/shared";
import { afterAll, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// formatWorkflow
// ---------------------------------------------------------------------------
describe("formatWorkflow", () => {
  const base: Workflow = {
    id: "wf-1",
    name: "My Workflow",
    description: "Does things",
    status: "active",
  };

  it("shows check emoji for active workflow", () => {
    const result = formatWorkflow({ ...base, status: "active" });
    expect(result).toContain("\u2705");
  });

  it("shows pencil emoji for draft workflow", () => {
    const result = formatWorkflow({ ...base, status: "draft" });
    expect(result).toContain("\uD83D\uDCDD");
  });

  it("shows pause emoji for paused/inactive workflow", () => {
    const result = formatWorkflow({ ...base, status: "inactive" });
    expect(result).toContain("\u23F8");
  });

  it("includes name, ID, and description", () => {
    const result = formatWorkflow(base);
    expect(result).toContain("**My Workflow**");
    expect(result).toContain("`wf-1`");
    expect(result).toContain("Does things");
  });

  it('shows "No description" when description is empty', () => {
    const result = formatWorkflow({ ...base, description: "" });
    expect(result).toContain("No description");
  });
});

// ---------------------------------------------------------------------------
// formatWorkflowList
// ---------------------------------------------------------------------------
describe("formatWorkflowList", () => {
  it("returns create instruction for empty list", () => {
    const result = formatWorkflowList([]);
    expect(result).toContain("No workflows found");
    expect(result).toContain("/workflow create");
  });

  it("formats multiple workflows joined by double newlines", () => {
    const workflows: Workflow[] = [
      { id: "1", name: "A", description: "d1", status: "active" },
      { id: "2", name: "B", description: "d2", status: "draft" },
    ];
    const result = formatWorkflowList(workflows);
    expect(result).toContain("**A**");
    expect(result).toContain("**B**");
    expect(result.split("\n\n").length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// formatTodo
// ---------------------------------------------------------------------------
describe("formatTodo", () => {
  const base: Todo = {
    id: "t-1",
    title: "Buy milk",
    completed: false,
  };

  it("shows checked checkbox for completed todo", () => {
    const result = formatTodo({ ...base, completed: true });
    expect(result).toContain("\u2611");
  });

  it("shows empty checkbox for incomplete todo", () => {
    const result = formatTodo({ ...base, completed: false });
    expect(result).toContain("\u2B1C");
  });

  it("uppercases priority", () => {
    const result = formatTodo({ ...base, priority: "high" });
    expect(result).toContain("[HIGH]");
  });

  it("formats due date correctly", () => {
    const result = formatTodo({ ...base, due_date: "2026-06-15T00:00:00Z" });
    expect(result).toContain("Due:");
    // The exact locale format varies, but it should contain the date
    expect(result).toMatch(/Due:\s*\d/);
  });

  it("omits priority when not set", () => {
    const result = formatTodo(base);
    expect(result).not.toContain("[");
  });

  it("omits due date when not set", () => {
    const result = formatTodo(base);
    expect(result).not.toContain("Due:");
  });
});

// ---------------------------------------------------------------------------
// formatTodoList
// ---------------------------------------------------------------------------
describe("formatTodoList", () => {
  it("returns create instruction for empty list", () => {
    const result = formatTodoList([]);
    expect(result).toContain("No todos found");
    expect(result).toContain("/todo add");
  });

  it("formats multiple todos joined by double newlines", () => {
    const todos: Todo[] = [
      { id: "1", title: "A", completed: false },
      { id: "2", title: "B", completed: true },
    ];
    const result = formatTodoList(todos);
    expect(result).toContain("**A**");
    expect(result).toContain("**B**");
  });
});

// ---------------------------------------------------------------------------
// formatConversation
// ---------------------------------------------------------------------------
describe("formatConversation", () => {
  const base: Conversation = {
    conversation_id: "c-1",
    created_at: "2026-01-01",
    updated_at: "2026-01-02",
    title: "Chat about cats",
    message_count: 5,
  };
  const baseUrl = "https://app.gaia.com";

  it("includes title, URL, and message count", () => {
    const result = formatConversation(base, baseUrl);
    expect(result).toContain("**Chat about cats**");
    expect(result).toContain("https://app.gaia.com/c/c-1");
    expect(result).toContain("(5 messages)");
  });

  it('shows "Untitled Conversation" when title is missing', () => {
    const result = formatConversation({ ...base, title: undefined }, baseUrl);
    expect(result).toContain("Untitled Conversation");
  });

  it("omits message count parenthetical when missing", () => {
    const result = formatConversation(
      { ...base, message_count: undefined },
      baseUrl,
    );
    expect(result).not.toContain("messages");
  });
});

// ---------------------------------------------------------------------------
// formatConversationList
// ---------------------------------------------------------------------------
describe("formatConversationList", () => {
  const baseUrl = "https://app.gaia.com";

  it("returns empty list message", () => {
    const result = formatConversationList([], baseUrl);
    expect(result).toContain("No conversations found");
  });

  it("joins multiple conversations with double newlines", () => {
    const conversations: Conversation[] = [
      {
        conversation_id: "1",
        title: "A",
        created_at: "2026-01-01",
        updated_at: "2026-01-01",
      },
      {
        conversation_id: "2",
        title: "B",
        created_at: "2026-01-01",
        updated_at: "2026-01-01",
      },
    ];
    const result = formatConversationList(conversations, baseUrl);
    expect(result).toContain("**A**");
    expect(result).toContain("**B**");
    expect(result).toContain("/c/1");
    expect(result).toContain("/c/2");
  });
});

// ---------------------------------------------------------------------------
// convertToTelegramHtml — Telegram HTML parse mode
// ---------------------------------------------------------------------------
describe("convertToTelegramHtml", () => {
  // --- Regression guards ---------------------------------------------------
  // These encode the exact production bug legacy Markdown caused (captured in
  // the live DOM: an auth token's underscores were parsed as italics and
  // silently dropped, corrupting the link). They assert OBSERVABLE output, so
  // they fail on any parse mode that mangles URLs/underscores — which is what
  // makes them catch the regression the old implementation-coupled tests
  // could not.

  it("keeps underscores in a bare URL intact (no italic, nothing dropped)", () => {
    const out = convertToTelegramHtml(
      "Open: http://localhost:3000/auth?platform=telegram&token=AjJD_TFC2_1Fgn",
    );
    expect(out).toContain("token=AjJD_TFC2_1Fgn");
    expect(out).not.toContain("<i>");
  });

  it("renders a markdown link with an underscored URL as a clickable anchor", () => {
    expect(
      convertToTelegramHtml("[docs](https://docs.heygaia.io/getting_started)"),
    ).toBe('<a href="https://docs.heygaia.io/getting_started">docs</a>');
  });

  it("does not italicize snake_case identifiers", () => {
    expect(convertToTelegramHtml("set user_id and api_key")).toBe(
      "set user_id and api_key",
    );
  });

  it("escapes &, <, > so user text can never break the markup", () => {
    expect(convertToTelegramHtml("use <input> & <b> tags")).toBe(
      "use &lt;input&gt; &amp; &lt;b&gt; tags",
    );
  });

  it("does not collide with ' N ' substrings in ordinary text", () => {
    // The internal placeholder sentinel must never match real text.
    expect(convertToTelegramHtml("I have 3 apples and 12 oranges")).toBe(
      "I have 3 apples and 12 oranges",
    );
  });

  // --- Formatting conversions ---------------------------------------------

  it("converts **bold** to <b>", () => {
    expect(convertToTelegramHtml("Hello **world**")).toBe("Hello <b>world</b>");
  });

  it("converts *italic* and _italic_ to <i>", () => {
    expect(convertToTelegramHtml("a *b* and _c_")).toBe(
      "a <i>b</i> and <i>c</i>",
    );
  });

  it("converts ***bold italic*** to nested <b><i>", () => {
    expect(convertToTelegramHtml("***x***")).toBe("<b><i>x</i></b>");
  });

  it("converts ~~strike~~ to <s>", () => {
    expect(convertToTelegramHtml("~~gone~~")).toBe("<s>gone</s>");
  });

  it("converts a heading to bold (Telegram HTML has no headings)", () => {
    expect(convertToTelegramHtml("# My Heading")).toBe("<b>My Heading</b>");
  });

  it("converts list bullets to • and strips horizontal rules", () => {
    expect(convertToTelegramHtml("- one\n- two")).toBe("• one\n• two");
    expect(convertToTelegramHtml("above\n---\nbelow")).toBe("above\n\nbelow");
  });

  it("wraps inline code in <code> with its contents escaped", () => {
    expect(convertToTelegramHtml("run `a < b`")).toBe(
      "run <code>a &lt; b</code>",
    );
  });

  it("wraps a fenced block in <pre><code> with a language class, escaped", () => {
    expect(convertToTelegramHtml("```python\nx = a < b\n```")).toBe(
      '<pre><code class="language-python">x = a &lt; b</code></pre>',
    );
  });

  it("does not convert markdown inside a fenced code block", () => {
    expect(convertToTelegramHtml("```\n**not bold**\n```")).toBe(
      "<pre>**not bold**</pre>",
    );
  });
});

// ---------------------------------------------------------------------------
// escapeHtml / htmlToPlainText — Telegram HTML helpers
// ---------------------------------------------------------------------------
describe("escapeHtml", () => {
  it("escapes only the three HTML-special characters", () => {
    expect(escapeHtml('a & b < c > d "e"')).toBe('a &amp; b &lt; c &gt; d "e"');
  });
});

describe("htmlToPlainText", () => {
  it("strips tags and decodes entities for the plain-text fallback", () => {
    expect(
      htmlToPlainText('<b>Hi</b> <a href="https://x.io/a_b">link</a> a &lt; b'),
    ).toBe("Hi link a < b");
  });

  it("round-trips escaped ampersands without double-decoding", () => {
    expect(htmlToPlainText("Tom &amp;amp; Jerry")).toBe("Tom &amp; Jerry");
  });
});

// ---------------------------------------------------------------------------
// convertToSlackMrkdwn
// ---------------------------------------------------------------------------
describe("convertToSlackMrkdwn", () => {
  it("converts **bold** to *bold*", () => {
    expect(convertToSlackMrkdwn("Hello **world**")).toBe("Hello *world*");
  });

  it("converts [label](url) to <url|label>", () => {
    expect(convertToSlackMrkdwn("[Click here](https://example.com)")).toBe(
      "<https://example.com|Click here>",
    );
  });

  it("converts # Heading to *Heading*", () => {
    expect(convertToSlackMrkdwn("## Sub Heading")).toBe("*Sub Heading*");
  });

  it("preserves code blocks unchanged", () => {
    const input = "```\nsome code\n```";
    expect(convertToSlackMrkdwn(input)).toBe(input);
  });

  it("escapes <, >, & in narrative so a stray tag can't break the message", () => {
    expect(convertToSlackMrkdwn("compare a < b and use <script>")).toBe(
      "compare a &lt; b and use &lt;script&gt;",
    );
  });

  it("escapes the link label but leaves the URL (with & and _) verbatim", () => {
    expect(convertToSlackMrkdwn("[a<b](https://x.io/a_b?x=1&y=2)")).toBe(
      "<https://x.io/a_b?x=1&y=2|a&lt;b>",
    );
  });

  it("converts ~~strike~~ to single-tilde ~strike~", () => {
    expect(convertToSlackMrkdwn("~~gone~~")).toBe("~gone~");
  });
});

// ---------------------------------------------------------------------------
// convertToWhatsAppMarkdown
// ---------------------------------------------------------------------------
describe("convertToWhatsAppMarkdown", () => {
  it("converts **bold** to *bold*", () => {
    expect(convertToWhatsAppMarkdown("Hello **world**")).toBe("Hello *world*");
  });

  it("converts ***bold italic*** to *bold*", () => {
    expect(convertToWhatsAppMarkdown("***text***")).toBe("*text*");
  });

  it("converts [label](url) to label (url)", () => {
    expect(convertToWhatsAppMarkdown("[Click here](https://example.com)")).toBe(
      "Click here (https://example.com)",
    );
  });

  it("converts # Heading to *Heading*", () => {
    expect(convertToWhatsAppMarkdown("# My Heading")).toBe("*My Heading*");
  });

  it("converts ## Sub Heading to *Sub Heading*", () => {
    expect(convertToWhatsAppMarkdown("## Sub Heading")).toBe("*Sub Heading*");
  });

  it("strips > quote prefix", () => {
    expect(convertToWhatsAppMarkdown("> quoted text")).toBe("quoted text");
  });

  it("removes --- horizontal rule", () => {
    expect(convertToWhatsAppMarkdown("above\n---\nbelow")).toBe(
      "above\n\nbelow",
    );
  });

  it("preserves code blocks unchanged", () => {
    const input = "```\nconst x = 1;\n```";
    expect(convertToWhatsAppMarkdown(input)).toBe(input);
  });

  it("does not convert **bold** inside code blocks", () => {
    const input = "```\n**not bold**\n```";
    expect(convertToWhatsAppMarkdown(input)).toBe(input);
  });

  it("handles mixed content with code blocks, bold, and links", () => {
    const input =
      "**bold** and [link](https://x.com)\n```\ncode **here**\n```\n**more**";
    const result = convertToWhatsAppMarkdown(input);
    expect(result).toContain("*bold*");
    expect(result).toContain("link (https://x.com)");
    expect(result).toContain("```\ncode **here**\n```");
    expect(result).toContain("*more*");
  });

  it("converts field values with **Name:** pattern to *Name:*", () => {
    expect(convertToWhatsAppMarkdown("**Name:** Aryan")).toBe("*Name:* Aryan");
  });
});

// ---------------------------------------------------------------------------
// convertToDiscordMarkdown
// ---------------------------------------------------------------------------
describe("convertToDiscordMarkdown", () => {
  it("converts [label](url) masked links to label (url)", () => {
    expect(convertToDiscordMarkdown("[Click here](https://example.com)")).toBe(
      "Click here (https://example.com)",
    );
  });

  it("leaves native CommonMark (bold, headings) untouched", () => {
    const input = "# Heading\n**bold** and _italic_";
    expect(convertToDiscordMarkdown(input)).toBe(input);
  });

  it("preserves code blocks unchanged", () => {
    const input = "```\n[not a link](x)\n```";
    expect(convertToDiscordMarkdown(input)).toBe(input);
  });
});

// ---------------------------------------------------------------------------
// PLATFORM_MARKDOWN map + renderForPlatform — the centralization chokepoint
// ---------------------------------------------------------------------------
describe("PLATFORM_MARKDOWN", () => {
  it("maps each platform to its dedicated converter", () => {
    expect(PLATFORM_MARKDOWN.discord).toBe(convertToDiscordMarkdown);
    expect(PLATFORM_MARKDOWN.slack).toBe(convertToSlackMrkdwn);
    expect(PLATFORM_MARKDOWN.telegram).toBe(convertToTelegramHtml);
    expect(PLATFORM_MARKDOWN.whatsapp).toBe(convertToWhatsAppMarkdown);
  });
});

describe("renderForPlatform", () => {
  it("routes through the discord converter (masked link → bare)", () => {
    expect(renderForPlatform("[GAIA](https://heygaia.io)", "discord")).toBe(
      "GAIA (https://heygaia.io)",
    );
  });

  it("routes through the slack converter (**bold** → *bold*, link → <url|label>)", () => {
    expect(renderForPlatform("**hi** [GAIA](https://x.com)", "slack")).toBe(
      "*hi* <https://x.com|GAIA>",
    );
  });

  it("routes through the telegram converter (**bold** → <b>)", () => {
    expect(renderForPlatform("**hi**", "telegram")).toBe("<b>hi</b>");
  });

  it("routes through the whatsapp converter (link → label (url))", () => {
    expect(renderForPlatform("[GAIA](https://x.com)", "whatsapp")).toBe(
      "GAIA (https://x.com)",
    );
  });

  it("produces output identical to the platform's converter", () => {
    const text = "**Heading**\n[link](https://x.com)";
    expect(renderForPlatform(text, "slack")).toBe(convertToSlackMrkdwn(text));
    expect(renderForPlatform(text, "whatsapp")).toBe(
      convertToWhatsAppMarkdown(text),
    );
  });
});

// ---------------------------------------------------------------------------
// buildAuthLinkMessage — the single canonical auth prompt
// ---------------------------------------------------------------------------
describe("buildAuthLinkMessage", () => {
  it("includes the auth URL verbatim so it stays copy-pasteable", () => {
    // Underscores in the token must survive (real auth tokens contain them).
    const url = "https://auth.gaia.com/link?token=ab_cd_ef";
    const msg = buildAuthLinkMessage(url);
    expect(msg).toContain(url);
    expect(msg).toContain("Link your account to GAIA");
  });

  it("returns one canonical message regardless of caller", () => {
    // Regression guard for 'hi vs /auth showed different text': a single
    // builder means the /auth command and the chat auth-prompt cannot diverge.
    expect(buildAuthLinkMessage("https://x")).toBe(
      buildAuthLinkMessage("https://x"),
    );
  });
});

// ---------------------------------------------------------------------------
// formatBotError
// ---------------------------------------------------------------------------
describe("formatBotError", () => {
  // Suppress console.error for the generic error fallback tests
  const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

  it("returns auth message for GaiaApiError with 401", () => {
    const err = new GaiaApiError("Unauthorized", 401);
    const result = formatBotError(err);
    expect(result).toContain("Authentication required");
    expect(result).toContain("/auth");
  });

  it("returns not found message for 404 status", () => {
    const err = { response: { status: 404 }, message: "Not found" };
    const result = formatBotError(err);
    expect(result).toContain("Not found");
  });

  it("returns rate limit message for 429 status", () => {
    const err = new GaiaApiError("Rate limited", 429);
    const result = formatBotError(err);
    expect(result).toContain("too fast");
  });

  it("returns timeout message for timeout errors", () => {
    const err = new Error("Request timed out");
    const result = formatBotError(err);
    expect(result).toContain("timed out");
  });

  it("returns connection message for connection lost", () => {
    const err = new Error("Connection lost before receiving a response");
    const result = formatBotError(err);
    expect(result).toContain("Connection lost");
  });

  it("returns connection interrupted for ECONNRESET", () => {
    const err = new Error("ECONNRESET");
    const result = formatBotError(err);
    expect(result).toContain("Connection interrupted");
  });

  it("returns incomplete message for stream processing", () => {
    const err = new Error("Stream processing incomplete");
    const result = formatBotError(err);
    expect(result).toContain("incomplete");
  });

  it('returns "something went wrong" for generic Error', () => {
    const err = new Error("some random failure");
    const result = formatBotError(err);
    expect(result).toContain("Something went wrong");
  });

  it('returns "something went wrong" for non-Error value', () => {
    const result = formatBotError("just a string");
    expect(result).toContain("Something went wrong");
  });

  afterAll(() => {
    consoleSpy.mockRestore();
  });
});
