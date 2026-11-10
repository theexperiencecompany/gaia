/** Marketing data JSON renders as plain text, so markup written into it reaches visitors verbatim. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProseParagraphs } from "@/components/seo/ProseParagraphs";

const DATA_ROOT = path.resolve(__dirname, "../../public/data");
// blog posts are markdown bodies rendered through MarkdownWrapper
const MARKDOWN_DIRS = new Set([path.join(DATA_ROOT, "blog")]);

const MARKDOWN_BOLD = /\*\*[^*\s][^*]*\*\*/;
// named list, not &\w+; — prose like "Q&A; bot" is plain text
const HTML_ENTITY = /&(?:nbsp|amp|lt|gt|quot|apos|#\d+|#x[\da-fA-F]+);/;

function jsonFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      return MARKDOWN_DIRS.has(full) ? [] : jsonFiles(full);
    }
    return name.endsWith(".json") ? [full] : [];
  });
}

function strings(value: unknown, at: string): [string, string][] {
  if (typeof value === "string") return [[at, value]];
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => strings(item, `${at}[${index}]`));
  }
  if (value !== null && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) =>
      strings(item, `${at}.${key}`),
    );
  }
  return [];
}

const ALL_STRINGS = jsonFiles(DATA_ROOT).flatMap((file) =>
  strings(
    JSON.parse(readFileSync(file, "utf8")),
    path.relative(DATA_ROOT, file),
  ),
);

describe("marketing data plain text", () => {
  it("carries no markdown bold markers", () => {
    const offenders = ALL_STRINGS.filter(([, text]) =>
      MARKDOWN_BOLD.test(text),
    ).map(([at]) => at);
    expect(offenders).toEqual([]);
  });

  it("carries no HTML entity literals", () => {
    const offenders = ALL_STRINGS.filter(([, text]) =>
      HTML_ENTITY.test(text),
    ).map(([at]) => at);
    expect(offenders).toEqual([]);
  });

  it("renders cron step syntax literally", () => {
    const html = renderToStaticMarkup(
      createElement(ProseParagraphs, {
        text: "*/15 * * * * runs every 15 minutes",
        className: "",
      }),
    );
    expect(html).toContain("*/15 * * * * runs every 15 minutes");
  });
});
