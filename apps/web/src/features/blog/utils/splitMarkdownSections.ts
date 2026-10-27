import type { Element, ElementContent, Root, RootContent } from "hast";

/** Headings that start a new top-level section in a long post. */
const SECTION_HEADINGS = new Set(["h1", "h2", "h3"]);

function newSection(): Element {
  return {
    type: "element",
    tagName: "section",
    properties: {},
    children: [],
  };
}

/**
 * Rehype plugin that groups a post's top-level nodes into one `<section>` per
 * heading, so a long article is not a single element with a hundred children.
 * The sections add no styles; margins collapse through them as before.
 */
export function rehypeSplitMarkdownSections() {
  return (tree: Root): void => {
    const children: RootContent[] = [];
    let section: Element | null = null;

    for (const node of tree.children) {
      if (node.type === "element" && SECTION_HEADINGS.has(node.tagName)) {
        section = newSection();
        children.push(section);
      }

      if (section === null) {
        children.push(node);
      } else if (node.type !== "doctype") {
        section.children.push(node as ElementContent);
      }
    }

    tree.children = children;
  };
}
