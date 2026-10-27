/** Markdown building blocks shared by /llms.txt, /AGENTS.md and the page markdown variants. */

export const MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8";

/** Collapse whitespace so titles/descriptions stay on one markdown line. */
export function oneLine(value: string): string {
  return value
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Escape square brackets so titles can't break the `[title](url)` syntax. */
function escapeTitle(value: string): string {
  return oneLine(value).replaceAll("[", "(").replaceAll("]", ")");
}

export function link(title: string, url: string): string {
  return `[${escapeTitle(title)}](${url})`;
}

export function bulletList(items: readonly string[]): string {
  return items.map((item) => `- ${oneLine(item)}`).join("\n");
}

export function numberedList(items: readonly string[]): string {
  return items
    .map((item, index) => `${index + 1}. ${oneLine(item)}`)
    .join("\n");
}

function tableCell(value: string): string {
  return oneLine(value).replaceAll("|", "\\|");
}

export function table(
  headers: readonly string[],
  rows: readonly (readonly string[])[],
): string {
  const line = (cells: readonly string[]) =>
    `| ${cells.map(tableCell).join(" | ")} |`;
  return [
    line(headers),
    line(headers.map(() => "---")),
    ...rows.map(line),
  ].join("\n");
}

export function faqSection(
  heading: string,
  faqs: readonly { question: string; answer: string }[],
): string {
  return [
    `## ${heading}`,
    ...faqs.map(
      (faq) => `### ${oneLine(faq.question)}\n\n${faq.answer.trim()}`,
    ),
  ].join("\n\n");
}

/** Join markdown blocks with blank lines, ending in one newline. */
export function document(blocks: readonly string[]): string {
  return `${blocks.map((block) => block.trim()).join("\n\n")}\n`;
}
