/**
 * Flatten tool args into preview rows for approval cards, on web and mobile.
 *
 * Top-level scalars alone drop the real content of a calendar create
 * (`{events: [...]}`), so this walks one level into objects and arrays of
 * objects, grouping array items (Event 1, Event 2) so the card shows what
 * will happen, not the schema shape.
 */

export interface ArgsPreviewRow {
  key: string;
  value: string;
  /** Array-item grouping ("Event 1"); null for top-level rows. */
  group: string | null;
}

export interface FlattenedArgs {
  rows: ArgsPreviewRow[];
  /** Rows dropped by the caps below. */
  omitted: number;
}

const MAX_ROWS = 20;
const MAX_ARRAY_ITEMS = 4;
const MAX_DEPTH = 2;

function prettyKey(key: string): string {
  return key.replaceAll("_", " ");
}

function singularize(key: string): string {
  const pretty = prettyKey(key);
  if (pretty.endsWith("ies")) return `${pretty.slice(0, -3)}y`;
  if (pretty.endsWith("ses")) return pretty;
  if (pretty.endsWith("s") && !pretty.endsWith("ss"))
    return pretty.slice(0, -1);
  return pretty;
}

function capitalize(text: string): string {
  return text.length === 0
    ? text
    : text.charAt(0).toUpperCase() + text.slice(1);
}

/** "2026-09-21T10:00:00" -> "Sun, Sep 21, 10:00 AM"; non-dates pass through. */
function prettyValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const iso = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(
    trimmed,
  );
  if (iso) {
    const [, y, mo, d, h, mi] = iso;
    const months = [
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec",
    ];
    const hour24 = Number(h);
    const suffix = hour24 >= 12 ? "PM" : "AM";
    const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
    const date = new Date(Number(y), Number(mo) - 1, Number(d));
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    return `${days[date.getDay()]}, ${months[Number(mo) - 1]} ${Number(d)}, ${hour12}:${mi} ${suffix}`;
  }
  return trimmed;
}

export function flattenArgsPreview(
  args: Record<string, unknown>,
): FlattenedArgs {
  const rows: ArgsPreviewRow[] = [];
  let omitted = 0;

  const push = (row: ArgsPreviewRow): void => {
    if (rows.length < MAX_ROWS) rows.push(row);
    else omitted += 1;
  };

  const walkArray = (
    value: unknown[],
    key: string,
    group: string | null,
    depth: number,
  ): void => {
    if (value.length === 0) return;
    if (value.every((item) => typeof item !== "object" || item === null)) {
      const joined = value
        .map((item) => prettyValue(item))
        .filter((text): text is string => text !== null)
        .join(", ");
      if (joined !== "") push({ key: prettyKey(key), value: joined, group });
      return;
    }
    const label = capitalize(singularize(key));
    value.slice(0, MAX_ARRAY_ITEMS).forEach((item, index) => {
      if (typeof item !== "object" || item === null) return;
      const itemGroup = `${label} ${index + 1}`;
      for (const [childKey, childValue] of Object.entries(item)) {
        walk(childValue, childKey, itemGroup, depth + 1);
      }
    });
    const rest = value.length - MAX_ARRAY_ITEMS;
    if (rest > 0) omitted += rest;
  };

  const walkObject = (
    value: Record<string, unknown>,
    key: string,
    group: string | null,
    depth: number,
  ): void => {
    if (depth >= MAX_DEPTH) {
      omitted += 1;
      return;
    }
    for (const [childKey, childValue] of Object.entries(value)) {
      walk(childValue, `${key} ${childKey}`, group, depth + 1);
    }
  };

  const walk = (
    value: unknown,
    key: string,
    group: string | null,
    depth: number,
  ): void => {
    if (value === null || value === undefined) return;
    if (Array.isArray(value)) {
      walkArray(value, key, group, depth);
      return;
    }
    if (typeof value === "object") {
      walkObject(value as Record<string, unknown>, key, group, depth);
      return;
    }
    const text = prettyValue(value);
    if (text !== null) push({ key: prettyKey(key), value: text, group });
  };

  for (const [key, value] of Object.entries(args ?? {})) {
    walk(value, key, null, 0);
  }
  return { rows, omitted };
}
