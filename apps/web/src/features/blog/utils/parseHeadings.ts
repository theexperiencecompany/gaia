import type { Root } from "mdast";
import { toString as mdastToString } from "mdast-util-to-string";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";
import { visit } from "unist-util-visit";

export interface Heading {
  id: string;
  text: string;
  level: number;
}

export function slugifyHeading(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/--+/g, "-")
    .trim();
}

/**
 * Parse headings from markdown content using a proper AST parser.
 * Correctly skips `#` inside code blocks, blockquotes, and other contexts.
 */
export function parseHeadings(content: string): Heading[] {
  const headings: Heading[] = [];

  const tree = unified().use(remarkParse).use(remarkGfm).parse(content) as Root;

  visit(tree, "heading", (node) => {
    if (node.depth > 3) return;
    const text = mdastToString(node);
    headings.push({
      id: slugifyHeading(text),
      text,
      level: node.depth,
    });
  });

  return headings;
}
