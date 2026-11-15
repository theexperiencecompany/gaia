import type { List, Paragraph, Root } from "mdast";
import type { Plugin } from "unified";
import { SKIP, visit } from "unist-util-visit";

/**
 * Render a list whose items are all empty as the literal text it was written as.
 * A reply of just "42." parses as an empty ordered list starting at 42, which
 * shows the number as a hanging list marker inside an indented, margined list.
 */
export const remarkBareListMarker: Plugin<[], Root> = () => {
  return (tree, file) => {
    const source = String(file);
    visit(tree, "list", (node: List, index, parent) => {
      const isBare = node.children.every((item) => item.children.length === 0);
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      if (!isBare || !parent || index === undefined) return;
      if (start === undefined || end === undefined) return;
      const paragraph: Paragraph = {
        type: "paragraph",
        children: [{ type: "text", value: source.slice(start, end) }],
      };
      parent.children.splice(index, 1, paragraph);
      return [SKIP, index];
    });
  };
};
