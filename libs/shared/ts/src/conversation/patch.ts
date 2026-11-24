import type { ItemChange } from "../api/generated";

/**
 * Applies the changes a wire 2 stream sends for an item or a reply's timeline the
 * client already holds. Only the containers on a changed path are copied, so every
 * step a change did not touch keeps its identity and its rendered row.
 */

type Path = ItemChange["path"];

/** The held value has no place for a change: it is not the copy the change was made against. */
const NOT_APPLICABLE = Symbol("change not applicable");
type Changed = unknown | typeof NOT_APPLICABLE;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function atTarget(node: unknown, change: ItemChange): Changed {
  if (change.op === "set") return change.value;
  if (
    change.op === "append" &&
    typeof node === "string" &&
    typeof change.value === "string"
  )
    return node + change.value;
  return NOT_APPLICABLE;
}

function inRecord(
  node: Record<string, unknown>,
  key: string,
  change: ItemChange,
  deeper: Path,
): Changed {
  if (deeper.length === 0 && change.op === "remove") {
    const { [key]: _dropped, ...kept } = node;
    return kept;
  }
  if (deeper.length === 0 && change.op === "set")
    return { ...node, [key]: change.value };
  // A key this build's schema does not keep: the change is to something it never reads.
  if (!(key in node)) return node;
  const inner = changed(node[key], change, deeper);
  return inner === NOT_APPLICABLE ? inner : { ...node, [key]: inner };
}

function inList(
  node: readonly unknown[],
  index: number,
  change: ItemChange,
  deeper: Path,
): Changed {
  const last = deeper.length === 0;
  if (last && change.op === "remove")
    return index === node.length - 1 ? node.slice(0, -1) : NOT_APPLICABLE;
  if (last && change.op === "set" && index === node.length)
    return [...node, change.value];
  if (index < 0 || index >= node.length) return NOT_APPLICABLE;
  const inner = changed(node[index], change, deeper);
  if (inner === NOT_APPLICABLE) return inner;
  const copy = [...node];
  copy[index] = inner;
  return copy;
}

function changed(node: unknown, change: ItemChange, rest: Path): Changed {
  if (rest.length === 0) return atTarget(node, change);
  const [key, ...deeper] = rest;
  if (isRecord(node) && typeof key === "string")
    return inRecord(node, key, change, deeper);
  if (Array.isArray(node) && typeof key === "number")
    return inList(node, key, change, deeper);
  return NOT_APPLICABLE;
}

/** The held value with the changes applied in order; null when one has no place in it. */
export function applyChanges<T>(
  held: T,
  changes: readonly ItemChange[],
): T | null {
  let next: unknown = held;
  for (const change of changes) {
    const result = changed(next, change, change.path);
    if (result === NOT_APPLICABLE) return null;
    next = result;
  }
  // The server writes each change against the JSON of the same model T was parsed from.
  return next as T;
}
