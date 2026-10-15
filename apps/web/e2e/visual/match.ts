import type { DomElement } from "./types";

/**
 * Pairs base and head elements for the style diff. Elements with text pair only
 * with the same tag and identical text under the same anchor (an ancestor with a
 * stable id, a landmark role or its own text), so a sibling added before them
 * cannot shift them onto a neighbour. Textless elements fall back to the
 * structural path, and only when both boxes are of a similar size.
 */

// Longer subtree text is a container's content, not a label that identifies it.
const TEXT_IDENTITY_MAX_CHARS = 40;
const LANDMARK_TAGS = new Set([
  "header",
  "nav",
  "main",
  "footer",
  "aside",
  "form",
  "dialog",
]);
// Generated ids (React useId, HeroUI) carry digits or punctuation and differ between runs.
const STABLE_ID = /^[a-z][a-z-]*$/i;
const SIZE_RATIO_LIMIT = 2;
const SIZE_SLACK_PX = 16;

export const parentPath = (path: string) =>
  path.slice(0, path.lastIndexOf(">"));
export const tagOf = (el: DomElement) =>
  el.path.slice(el.path.lastIndexOf(">") + 1).split(":")[0];

/** An ancestor's contribution to its descendants' anchor key, or null when it is not an anchor. */
function anchorIdent(el: DomElement): string | null {
  if (el.id && STABLE_ID.test(el.id)) return `#${el.id}`;
  if (el.role) return `[role=${el.role}]`;
  if (LANDMARK_TAGS.has(tagOf(el))) return tagOf(el);
  return el.label ? `"${el.label}"` : null;
}

/** Each element's identity key, or null for textless elements. */
function textKeys(elements: DomElement[]): Map<DomElement, string | null> {
  const byPath = new Map(elements.map((el) => [el.path, el]));
  const fragments = new Map<string, string[]>();
  for (const el of elements) {
    if (!el.label) continue;
    for (let path = el.path; path.includes(">"); path = parentPath(path)) {
      const list = fragments.get(path) ?? [];
      list.push(el.label);
      fragments.set(path, list);
    }
  }
  const anchors = new Map<string, string>();
  const anchorOf = (path: string): string => {
    if (!path.includes(">")) return "";
    const known = anchors.get(path);
    if (known !== undefined) return known;
    const parent = parentPath(path);
    const ancestor = byPath.get(parent);
    const ident = ancestor ? anchorIdent(ancestor) : null;
    const anchor = ident ? `${anchorOf(parent)}/${ident}` : anchorOf(parent);
    anchors.set(path, anchor);
    return anchor;
  };
  return new Map(
    elements.map((el) => {
      const text = el.label || (fragments.get(el.path) ?? []).join(" ");
      const identifying = text !== "" && text.length <= TEXT_IDENTITY_MAX_CHARS;
      return [
        el,
        identifying ? `${anchorOf(el.path)}|${tagOf(el)}|${text}` : null,
      ];
    }),
  );
}

const similar = (a: number, b: number) =>
  Math.abs(a - b) <= SIZE_SLACK_PX ||
  Math.max(a, b) / Math.max(Math.min(a, b), 1) <= SIZE_RATIO_LIMIT;

/** Base element to its head partner; elements absent from the map were added or removed. */
export function matchElements(
  base: DomElement[],
  head: DomElement[],
): Map<DomElement, DomElement> {
  const baseKeys = textKeys(base);
  const headKeys = textKeys(head);
  const pairs = new Map<DomElement, DomElement>();

  const headByKey = new Map<string, DomElement[]>();
  for (const el of head) {
    const key = headKeys.get(el);
    if (key) headByKey.set(key, [...(headByKey.get(key) ?? []), el]);
  }
  const headByPath = new Map(head.map((el) => [el.path, el]));
  for (const el of base) {
    const key = baseKeys.get(el);
    if (key) {
      // Same key more than once: pair in document order.
      const partner = headByKey.get(key)?.shift();
      if (partner) pairs.set(el, partner);
      continue;
    }
    const partner = headByPath.get(el.path);
    if (
      partner &&
      !headKeys.get(partner) &&
      similar(el.rect.width, partner.rect.width) &&
      similar(el.rect.height, partner.rect.height)
    )
      pairs.set(el, partner);
  }
  return pairs;
}
