/**
 * Round-trips between the editor's stored value — a plain string where each
 * mention is an `@<toolName>` token and lines are separated by `\n` — and the
 * Tiptap document model. Each line maps to a paragraph; `@<toolName>` tokens
 * (recognized by {@link buildMentionSegments}) map to atomic `mention` nodes,
 * everything else stays literal text (Markdown is authored as plain text).
 */

import type { JSONContent } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";

import { buildMentionSegments } from "@/features/integrations/utils/toolMentions";

export const MENTION_NODE = "mention";

/** Parse the stored value into a Tiptap document, resolving mentions to chips. */
export const valueToContent = (
  value: string,
  toolNames: string[],
): JSONContent => ({
  type: "doc",
  content: value.split("\n").map((line) => {
    const inline: JSONContent[] = [];
    for (const segment of buildMentionSegments(line, toolNames)) {
      if (segment.mention) {
        const name = segment.text.slice(1);
        inline.push({ type: MENTION_NODE, attrs: { id: name, label: name } });
      } else if (segment.text) {
        inline.push({ type: "text", text: segment.text });
      }
    }
    return { type: "paragraph", content: inline };
  }),
});

/** Serialize a Tiptap document back to the stored `@<toolName>` string. */
export const docToValue = (doc: ProseMirrorNode): string => {
  const lines: string[] = [];
  doc.forEach((block) => {
    let line = "";
    block.forEach((child) => {
      if (child.isText) {
        line += child.text ?? "";
      } else if (child.type.name === MENTION_NODE) {
        line += `@${child.attrs.label ?? child.attrs.id}`;
      } else if (child.type.name === "hardBreak") {
        line += "\n";
      }
    });
    lines.push(line);
  });
  return lines.join("\n");
};
