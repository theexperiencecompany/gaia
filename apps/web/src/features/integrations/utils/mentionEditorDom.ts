/**
 * DOM helpers for the contentEditable mention editor. The editor's value is a
 * plain string where each chip serializes to `@<toolName>`; these helpers
 * convert between that string and the live (user-mutated) DOM, including
 * caret positions expressed as offsets into the serialized string.
 */

export const MENTION_ATTR = "data-mention";

type LeafKind = "text" | "mention" | "br";

interface EditorLeaf {
  node: Node;
  kind: LeafKind;
  length: number;
}

const isMentionElement = (node: Node): node is HTMLElement =>
  node instanceof HTMLElement && node.hasAttribute(MENTION_ATTR);

/** Document-order leaves that contribute characters to the serialized value. */
function* iterateLeaves(container: Node): Generator<EditorLeaf> {
  for (const node of Array.from(container.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      yield { node, kind: "text", length: node.textContent?.length ?? 0 };
    } else if (isMentionElement(node)) {
      const name = node.getAttribute(MENTION_ATTR) ?? "";
      yield { node, kind: "mention", length: name.length + 1 };
    } else if (node.nodeName === "BR") {
      yield { node, kind: "br", length: 1 };
    } else {
      yield* iterateLeaves(node);
    }
  }
}

/** Serialize editor DOM (or a cloned fragment of it) back to the value string. */
export const serializeEditorNodes = (container: Node): string => {
  let out = "";
  for (const leaf of iterateLeaves(container)) {
    if (leaf.kind === "text") {
      out += leaf.node.textContent ?? "";
    } else if (leaf.kind === "mention") {
      out += `@${(leaf.node as HTMLElement).getAttribute(MENTION_ATTR)}`;
    } else {
      out += "\n";
    }
  }
  // contentEditable inserts &nbsp; for some spaces — normalize for storage.
  return out.replace(/\u00a0/g, " ");
};

/** Caret position as an offset into the serialized value, or null if outside. */
export const getCaretOffset = (root: HTMLElement): number | null => {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer)) return null;
  const pre = range.cloneRange();
  pre.selectNodeContents(root);
  pre.setEnd(range.startContainer, range.startOffset);
  return serializeEditorNodes(pre.cloneContents()).length;
};

/** Serialized-value offset at which a node starts. */
export const getNodeStartOffset = (root: HTMLElement, node: Node): number => {
  const range = document.createRange();
  range.selectNodeContents(root);
  range.setEndBefore(node);
  return serializeEditorNodes(range.cloneContents()).length;
};

/** Place the caret at the given serialized-value offset. */
export const setCaretAtOffset = (root: HTMLElement, offset: number): void => {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  let remaining = offset;
  let placed = false;

  for (const leaf of iterateLeaves(root)) {
    if (remaining > leaf.length) {
      remaining -= leaf.length;
      continue;
    }
    if (leaf.kind === "text") {
      range.setStart(leaf.node, remaining);
    } else if (remaining === 0) {
      // The caret can't sit inside an atomic leaf — snap to its edge.
      range.setStartBefore(leaf.node);
    } else {
      range.setStartAfter(leaf.node);
    }
    placed = true;
    break;
  }

  if (placed) {
    range.collapse(true);
  } else {
    range.selectNodeContents(root);
    range.collapse(false);
  }
  selection.removeAllRanges();
  selection.addRange(range);
};
