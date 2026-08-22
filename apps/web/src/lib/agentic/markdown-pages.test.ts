import { describe, expect, it } from "vitest";

import {
  buildPageMarkdown,
  MARKDOWN_CACHE_CONTROL,
} from "@/lib/agentic/markdown-pages";

const HOMEPAGE_FIXTURE = {
  title: "GAIA — Your Personal AI Assistant",
  intro:
    "GAIA watches your inbox, calendar, and tools, and acts before you ask. It drafts replies, schedules meetings, and closes tasks on its own, then reports back with what got done. Connect your apps once and GAIA keeps your day moving across email, messaging, and every workflow in between, proactively instead of on command.",
  sections: [
    {
      heading: "Proactive by design",
      description:
        "GAIA monitors your connected tools continuously and surfaces the two or three things that need you each morning. Everything outward-facing waits for your approval first, so automation never means losing control. Briefings arrive before you ask, follow-ups go out on schedule, and nothing slips through because GAIA keeps context across every conversation and every tool you connect.",
    },
    {
      heading: "Works where you work",
      description:
        "Message GAIA from WhatsApp, Telegram, Slack, Discord, or the web. Tasks started on one surface continue on another, with shared memory across every conversation. There is no new app to learn: send a message the way you would text a colleague, and GAIA turns it into research, drafts, calendar moves, and completed todos.",
    },
    {
      heading: "Your data stays yours",
      description:
        "GAIA is open source, so every line of code that touches your data is inspectable. We never train on your data, never sell it, and never share it with model providers. If you want total control, self-host the entire stack on your own infrastructure with the same features as the cloud version.",
    },
  ],
  faqs: [
    {
      question: "Is this just another chatbot like ChatGPT?",
      answer:
        "No. ChatGPT waits for you to ask. GAIA watches your inbox, calendar, and tools, and acts before you ask: drafting replies, scheduling meetings, and closing tasks on its own. Less chatbot, more teammate who actually does the work.",
    },
    {
      question: "Can GAIA really run my whole day?",
      answer:
        "Yes, that is the point. Every morning GAIA sends a briefing: the two or three things that need you, and the list it plans to handle itself. Approve with one tap and it gets to work drafting, scheduling, and following up, then reports back in the evening with what got done.",
    },
    {
      question: "Do I need to be technical to use this?",
      answer:
        "No. If you can send a text, you can use GAIA. You write in plain English, GAIA does the research, books the calendar, and sets the reminders. Connecting your apps is one click each. No setup, no code.",
    },
    {
      question: "Is my personal data safe?",
      answer:
        "Yes. We never train on your data, never sell it, and never share it with model providers. GAIA is open source, so every line of code that touches your data is inspectable. And if you want total control, you can self-host the whole thing.",
    },
  ],
  links: [
    { label: "Pricing", href: "https://heygaia.io/pricing" },
    { label: "Blog", href: "https://heygaia.io/blog" },
    { label: "Documentation", href: "https://docs.heygaia.io" },
  ],
};

describe("buildPageMarkdown", () => {
  it("starts with an H1 title", () => {
    const body = buildPageMarkdown(HOMEPAGE_FIXTURE);
    expect(body.startsWith("# GAIA — Your Personal AI Assistant\n")).toBe(true);
  });

  it("renders each section as an H2 followed by its description", () => {
    const body = buildPageMarkdown(HOMEPAGE_FIXTURE);
    expect(body).toContain("## Proactive by design");
    expect(body).toContain("## Works where you work");
    expect(
      body.indexOf("## Proactive by design") <
        body.indexOf("## Works where you work"),
    ).toBe(true);
    expect(body).toContain("GAIA monitors your connected tools continuously");
  });

  it("renders FAQ questions as H3 with paragraph answers", () => {
    const body = buildPageMarkdown(HOMEPAGE_FIXTURE);
    expect(body).toContain("## Frequently asked questions");
    expect(body).toContain("### Is this just another chatbot like ChatGPT?");
    expect(body).toContain("No. ChatGPT waits for you to ask.");
    // Answers are plain paragraphs, not list items or headings.
    expect(body).not.toMatch(/### No\. ChatGPT/);
  });

  it("renders the links block last as a markdown list", () => {
    const body = buildPageMarkdown(HOMEPAGE_FIXTURE);
    const linksIdx = body.indexOf("## Links");
    expect(linksIdx).toBeGreaterThan(-1);
    expect(
      body.indexOf("- [Pricing](https://heygaia.io/pricing)"),
    ).toBeGreaterThan(linksIdx);
    expect(
      body.trimEnd().endsWith("- [Documentation](https://docs.heygaia.io)"),
    ).toBe(true);
  });

  it("produces a substantial document for a homepage fixture", () => {
    expect(buildPageMarkdown(HOMEPAGE_FIXTURE).length).toBeGreaterThanOrEqual(
      1500,
    );
  });

  it("contains zero raw HTML tags", () => {
    const body = buildPageMarkdown(HOMEPAGE_FIXTURE);
    expect(body).not.toMatch(/<\/*[a-z][a-z0-9-]*[^>]*>/i);
    expect(body).not.toContain("<script");
    expect(body).not.toContain("</p>");
  });

  it("ends with exactly one trailing newline", () => {
    const body = buildPageMarkdown({ title: "T" });
    expect(body.endsWith("\n")).toBe(true);
    expect(body.endsWith("\n\n")).toBe(false);
  });

  it("omits empty optional blocks entirely", () => {
    const body = buildPageMarkdown({ title: "Only title" });
    expect(body).toBe("# Only title\n");
    expect(body).not.toContain("## Frequently asked questions");
    expect(body).not.toContain("## Links");
  });

  it("skips blank intro and section descriptions", () => {
    const body = buildPageMarkdown({
      title: "T",
      intro: "   ",
      sections: [{ heading: "S", description: "" }],
    });
    expect(body).toBe("# T\n\n## S\n");
  });

  it("filters FAQ entries missing question or answer", () => {
    const body = buildPageMarkdown({
      title: "T",
      faqs: [
        { question: "", answer: "orphan answer" },
        { question: "Valid?", answer: "" },
        { question: "Kept?", answer: "Yes." },
      ],
    });
    expect(body).toContain("### Kept?");
    expect(body).not.toContain("orphan answer");
    expect(body).not.toContain("### Valid?");
  });
});

describe("MARKDOWN_CACHE_CONTROL", () => {
  it("is the agreed public short-cache hint", () => {
    expect(MARKDOWN_CACHE_CONTROL).toBe("public, max-age=3600");
  });
});
