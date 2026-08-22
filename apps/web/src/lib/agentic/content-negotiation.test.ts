import { describe, expect, it } from "vitest";

import {
  negotiate,
  negotiateFromAcceptHeader,
} from "@/lib/agentic/content-negotiation";

function requestWithAccept(accept: string | null): Request {
  const headers = new Headers();
  if (accept !== null) headers.set("accept", accept);
  return new Request("https://heygaia.io/", { headers });
}

describe("negotiateFromAcceptHeader", () => {
  it("serves html for a missing Accept header", () => {
    expect(negotiateFromAcceptHeader(null)).toBe("html");
    expect(negotiateFromAcceptHeader(undefined)).toBe("html");
  });

  it("serves html for a blank Accept header", () => {
    expect(negotiateFromAcceptHeader("")).toBe("html");
    expect(negotiateFromAcceptHeader("   ")).toBe("html");
  });

  it("maps */* to html", () => {
    expect(negotiateFromAcceptHeader("*/*")).toBe("html");
  });

  it("maps text/* to html (html matches the wildcard)", () => {
    expect(negotiateFromAcceptHeader("text/*")).toBe("html");
  });

  it("never serves markdown unless text/markdown is explicitly listed", () => {
    expect(negotiateFromAcceptHeader("*/*;q=0.9, application/json;q=0.8")).toBe(
      "html",
    );
  });

  it("serves markdown when text/markdown is the only type", () => {
    expect(negotiateFromAcceptHeader("text/markdown")).toBe("markdown");
  });

  it("prefers markdown at higher q", () => {
    expect(
      negotiateFromAcceptHeader("text/html;q=0.5, text/markdown;q=0.8"),
    ).toBe("markdown");
  });

  it("serves html at higher q", () => {
    expect(
      negotiateFromAcceptHeader("text/html;q=0.8, text/markdown;q=0.5"),
    ).toBe("html");
  });

  it("breaks q ties toward markdown (agent signalled intent)", () => {
    expect(
      negotiateFromAcceptHeader("text/html;q=0.7, text/markdown;q=0.7"),
    ).toBe("markdown");
    expect(negotiateFromAcceptHeader("text/html, text/markdown")).toBe(
      "markdown",
    );
  });

  it("falls back to html when markdown is explicitly rejected", () => {
    expect(
      negotiateFromAcceptHeader("text/markdown;q=0, text/html;q=0.5"),
    ).toBe("html");
  });

  it("returns notacceptable when both types are explicitly rejected", () => {
    expect(negotiateFromAcceptHeader("text/markdown;q=0, text/html;q=0")).toBe(
      "notacceptable",
    );
  });

  it("returns notacceptable for explicit types that match neither variant", () => {
    expect(negotiateFromAcceptHeader("application/json")).toBe("notacceptable");
    expect(negotiateFromAcceptHeader("application/json, image/png")).toBe(
      "notacceptable",
    );
  });

  it("returns notacceptable when all compatible wildcards are rejected", () => {
    expect(negotiateFromAcceptHeader("text/*;q=0")).toBe("notacceptable");
    expect(negotiateFromAcceptHeader("*/*;q=0")).toBe("notacceptable");
  });

  it("lets an exact entry override a rejected wildcard (RFC precedence)", () => {
    // */* rejects everything, but the specific text/markdown re-enables it.
    expect(negotiateFromAcceptHeader("*/*;q=0, text/markdown")).toBe(
      "markdown",
    );
    expect(negotiateFromAcceptHeader("*/*;q=0, text/html;q=0.6")).toBe("html");
  });

  it("lets text/* override */* but exact override both", () => {
    // text/* at 0.4 is more specific than */* at 0.8 for both candidates;
    // markdown must be explicitly listed to win, so this resolves via html.
    expect(negotiateFromAcceptHeader("text/*;q=0.4, */*;q=0.8")).toBe("html");
    // Exact text/markdown beats the lower-specificity ranges.
    expect(
      negotiateFromAcceptHeader("text/*;q=0.2, */*;q=0.1, text/markdown;q=0.3"),
    ).toBe("markdown");
    // Exact text/html beats text/*.
    expect(
      negotiateFromAcceptHeader("text/*;q=0.2, */*;q=0.1, text/html;q=0.3"),
    ).toBe("html");
  });

  it("is case-insensitive across types, subtypes and parameter names", () => {
    expect(negotiateFromAcceptHeader("TEXT/MARKDOWN ; Q=0.9")).toBe("markdown");
    expect(negotiateFromAcceptHeader("Text/Html ; Q=1.0, Text/Markdown")).toBe(
      "markdown",
    );
    expect(negotiateFromAcceptHeader("APPLICATION/JSON")).toBe("notacceptable");
  });

  it("tolerates whitespace around separators", () => {
    expect(
      negotiateFromAcceptHeader("  text/html ; q=0.3 ,  text/markdown;q=0.4  "),
    ).toBe("markdown");
  });

  it("ignores non-q parameters", () => {
    expect(
      negotiateFromAcceptHeader("text/markdown;level=1, text/html;q=0.2"),
    ).toBe("markdown");
  });

  it("takes the highest q among duplicate entries", () => {
    expect(negotiateFromAcceptHeader("text/html;q=0.2, text/html;q=0.9")).toBe(
      "html",
    );
    expect(
      negotiateFromAcceptHeader(
        "text/html;q=0.9, text/markdown;q=0.2, text/markdown;q=0.95",
      ),
    ).toBe("markdown");
  });

  it("degrades gracefully on garbage headers", () => {
    expect(negotiateFromAcceptHeader(",,,")).toBe("html");
    expect(negotiateFromAcceptHeader("garbage")).toBe("html");
    expect(negotiateFromAcceptHeader("<>;;;===")).toBe("html");
    // One garbage segment must not poison valid siblings.
    expect(negotiateFromAcceptHeader("garbage,, text/markdown;q=1")).toBe(
      "markdown",
    );
    expect(negotiateFromAcceptHeader('text/"quoted"')).toBe("html");
  });

  it("treats malformed q values leniently", () => {
    // Non-numeric q ignored → default 1 → markdown wins over nothing else.
    expect(negotiateFromAcceptHeader("text/markdown;q=abc")).toBe("markdown");
    // Out-of-range numeric q clamps to 1.
    expect(negotiateFromAcceptHeader("text/markdown;q=5")).toBe("markdown");
    expect(negotiateFromAcceptHeader("text/markdown;q=-1")).toBe("markdown");
  });
});

describe("negotiate", () => {
  it("reads the Accept header off a Request", () => {
    expect(negotiate(requestWithAccept("text/markdown"))).toBe("markdown");
    expect(negotiate(requestWithAccept("*/*"))).toBe("html");
    expect(negotiate(requestWithAccept("application/json"))).toBe(
      "notacceptable",
    );
  });

  it("handles requests without an Accept header", () => {
    expect(negotiate(requestWithAccept(null))).toBe("html");
  });

  it("only reads headers — method-agnostic by design", () => {
    // Method gating lives in middleware; the parser itself only inspects
    // Accept so GET/POST behave identically here.
    const post = new Request("https://heygaia.io/", {
      method: "POST",
      headers: { accept: "text/markdown" },
    });
    expect(negotiate(post)).toBe("markdown");
  });
});
