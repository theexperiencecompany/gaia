/**
 * Grounded figures: prose names a slot into a component's data ({funnel1.maxDrop}) and code
 * computes and prints the number. The validator also rejects any typed number the brief never
 * states. Node-safe: the renderer and the server-side validator share this module.
 */

export interface GroundNode {
  type?: string;
  typeName?: string;
  statementId?: string;
  props?: Record<string, unknown>;
}
export type GroundingIndex = Map<string, GroundNode>;

interface Figure {
  n: number;
  pct?: boolean;
}
type SlotValue = string | Figure;

// {statement.key}, {statement.key:Series}, and a trailing ~ on the key for a rounded figure
const SLOT = /\{([A-Za-z_$][\w$]*)\.([A-Za-z]+)(~?)(?::([^}]+))?\}/g;

/** Whether text holds a {statement.key} slot, which only prose components resolve. */
export function containsSlot(text: string): boolean {
  return new RegExp(SLOT.source).test(text);
}

const fig = (n: number, pct = false): Figure => ({ n, pct });

/** Exact: integers as written, others to one decimal. Rounded (~): two significant figures. */
function show(value: SlotValue, rounded: boolean): string {
  if (typeof value === "string") return value;
  let n = value.n;
  if (rounded && n !== 0) {
    const magnitude = 10 ** (Math.floor(Math.log10(Math.abs(n))) - 1);
    n = Math.round(n / magnitude) * magnitude;
  } else if (!Number.isInteger(n)) {
    n = Math.round(n * 10) / 10;
  }
  const digits = n.toLocaleString("en", { maximumFractionDigits: 1 });
  return `${digits}${value.pct ? "%" : ""}`;
}

/** Exact name first, then the one name starting with the argument; ambiguous is a miss. */
function pick<T>(
  items: readonly T[],
  nameOf: (item: T) => string,
  want: string,
): T | undefined {
  const w = want.trim().toLowerCase();
  const exact = items.find((item) => nameOf(item).toLowerCase() === w);
  if (exact) return exact;
  const starts = items.filter((item) =>
    nameOf(item).toLowerCase().startsWith(w),
  );
  return starts.length === 1 ? starts[0] : undefined;
}

const sum = (values: number[]): number => values.reduce((a, b) => a + b, 0);
const last = <T>(values: readonly T[]): T => values[values.length - 1];

type Series = [string, number[]];

function seriesOf(
  props: Record<string, unknown>,
  name?: string,
): { labels: string[]; values: number[] } | null {
  const labels = (props.labels as string[] | undefined) ?? [];
  const series = (props.series as Series[] | undefined) ?? [];
  const found = name ? pick(series, ([n]) => n, name) : series[0];
  return found ? { labels, values: found[1] } : null;
}

const NUMERIC_CELL = /^[\d,.$€£%-]+$/;
const toNumber = (cell: unknown): number =>
  Number(String(cell).replace(/[^0-9.-]/g, ""));

function columnOf(
  props: Record<string, unknown>,
  name?: string,
): { keys: string[]; values: number[] } | null {
  const columns = (props.columns as string[] | undefined) ?? [];
  const j = name ? columns.indexOf(pick(columns, (c) => c, name) ?? "") : 1;
  if (j < 0) return null;
  const rows = ((props.rows as unknown[][] | undefined) ?? []).filter(
    (row) =>
      typeof row[j] === "number" || NUMERIC_CELL.test(String(row[j] ?? "")),
  );
  return {
    keys: rows.map((row) => String(row[0])),
    values: rows.map((row) => toNumber(row[j])),
  };
}

const SERIES_SLOTS = [
  "total",
  "max",
  "maxLabel",
  "min",
  "minLabel",
  "avg",
  "first",
  "last",
  "change",
  "changePct",
];

/** Every slot a component offers, by component name. Keys take an optional :series or :column. */
const SLOTS: Record<string, readonly string[]> = {
  Funnel: [
    "first",
    "last",
    "maxDrop",
    "maxDropStage",
    "worstStep",
    "worstStepLoss",
    "overall",
  ],
  Line: SERIES_SLOTS,
  Area: SERIES_SLOTS,
  Bars: SERIES_SLOTS,
  StackedBars: SERIES_SLOTS,
  Gauge: ["value", "target", "gap"],
  DataTable: ["sum", "max", "maxRow", "min", "minRow", "count"],
  Heatmap: ["max", "maxCell", "total"],
};

function funnelSlots(
  props: Record<string, unknown>,
): Record<string, SlotValue> | undefined {
  const stages = (props.stages as [string, number][] | undefined) ?? [];
  if (stages.length < 2) return undefined;
  // largest absolute drop, and the lowest share carried from one stage to the next
  let drop = 1;
  let worst = 1;
  for (let i = 1; i < stages.length; i++) {
    if (stages[i - 1][1] - stages[i][1] > stages[drop - 1][1] - stages[drop][1])
      drop = i;
    if (
      stages[i][1] / stages[i - 1][1] <
      stages[worst][1] / stages[worst - 1][1]
    )
      worst = i;
  }
  return {
    first: fig(stages[0][1]),
    last: fig(last(stages)[1]),
    maxDrop: fig(stages[drop - 1][1] - stages[drop][1]),
    maxDropStage: `${stages[drop - 1][0]} to ${stages[drop][0]}`,
    worstStep: `${stages[worst - 1][0]} to ${stages[worst][0]}`,
    worstStepLoss: fig(
      (1 - stages[worst][1] / stages[worst - 1][1]) * 100,
      true,
    ),
    overall: fig((last(stages)[1] / stages[0][1]) * 100, true),
  };
}

function seriesSlots(
  props: Record<string, unknown>,
  key: string,
  arg?: string,
): Record<string, SlotValue> | undefined {
  if (key === "total" && !arg) {
    const all = ((props.series as Series[] | undefined) ?? []).flatMap(
      ([, v]) => v,
    );
    return { total: fig(sum(all)) };
  }
  const s = seriesOf(props, arg);
  if (!s?.values.length) return undefined;
  const v = s.values;
  const hi = Math.max(...v);
  const lo = Math.min(...v);
  return {
    total: fig(sum(v)),
    max: fig(hi),
    maxLabel: s.labels[v.indexOf(hi)],
    min: fig(lo),
    minLabel: s.labels[v.indexOf(lo)],
    avg: fig(sum(v) / v.length),
    first: fig(v[0]),
    last: fig(last(v)),
    change: fig(last(v) - v[0]),
    changePct: fig(((last(v) - v[0]) / v[0]) * 100, true),
  };
}

function gaugeSlots(props: Record<string, unknown>): Record<string, SlotValue> {
  const value = props.value as number;
  const target = props.target as number | undefined;
  return target == null
    ? { value: fig(value) }
    : { value: fig(value), target: fig(target), gap: fig(value - target) };
}

function tableSlots(
  props: Record<string, unknown>,
  arg?: string,
): Record<string, SlotValue> | undefined {
  const c = columnOf(props, arg);
  if (!c?.values.length) return undefined;
  const hi = Math.max(...c.values);
  const lo = Math.min(...c.values);
  return {
    sum: fig(sum(c.values)),
    max: fig(hi),
    maxRow: c.keys[c.values.indexOf(hi)],
    min: fig(lo),
    minRow: c.keys[c.values.indexOf(lo)],
    count: fig(c.values.length),
  };
}

function heatmapSlots(
  props: Record<string, unknown>,
): Record<string, SlotValue> | undefined {
  const values = (props.values as number[][] | undefined) ?? [];
  const flat = values.flat();
  if (!flat.length) return undefined;
  const hi = Math.max(...flat);
  const r = values.findIndex((row) => row.includes(hi));
  const rows = props.rows as string[];
  const columns = props.columns as string[];
  return {
    max: fig(hi),
    maxCell: `${rows[r]} ${columns[values[r].indexOf(hi)]}`,
    total: fig(sum(flat)),
  };
}

function compute(
  node: GroundNode,
  key: string,
  arg?: string,
): SlotValue | undefined {
  const props = node.props ?? {};
  switch (node.typeName) {
    case "Funnel":
      return funnelSlots(props)?.[key];
    case "Line":
    case "Area":
    case "Bars":
    case "StackedBars":
      return seriesSlots(props, key, arg)?.[key];
    case "Gauge":
      return gaugeSlots(props)[key];
    case "DataTable":
      return tableSlots(props, arg)?.[key];
    case "Heatmap":
      return heatmapSlots(props)?.[key];
    default:
      return undefined;
  }
}

/** Every named statement in a parsed program, by statement id. */
export function buildIndex(root: unknown): GroundingIndex {
  const index: GroundingIndex = new Map();
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      value.forEach(walk);
      return;
    }
    if (!value || typeof value !== "object") return;
    const node = value as GroundNode;
    if (node.type === "element" && node.statementId)
      index.set(node.statementId, node);
    Object.values(node.props ?? {}).forEach(walk);
  };
  walk(root);
  return index;
}

/** Replace every slot; unknown ones are listed and left visible, so a miss is never silent. */
export function resolveText(
  text: string,
  index: GroundingIndex,
): { text: string; unknown: string[] } {
  const unknown: string[] = [];
  const dataNodes = [...index.values()].filter((n) => SLOTS[n.typeName ?? ""]);
  const out = text.replace(
    SLOT,
    (whole, id: string, key: string, tilde: string, arg?: string) => {
      // exact id, else the one data statement whose id starts with it
      const node =
        index.get(id) ?? pick(dataNodes, (n) => n.statementId ?? "", id);
      const offered = node ? SLOTS[node.typeName ?? ""]?.includes(key) : false;
      const value = node && offered ? compute(node, key, arg) : undefined;
      if (value === undefined) {
        unknown.push(`${id}.${key}${arg ? `:${arg}` : ""}`);
        return whole;
      }
      return show(value, tilde === "~");
    },
  );
  return { text: out, unknown };
}

const NUMBER = /\d[\d,]*(?:\.\d+)?/g;
const RANGE = /\b(\d{1,3})\s*(?:\.\.|-|–|to)\s*(\d{1,3})\b/g;
const MAX_RANGE_SPAN = 60;
const norm = (token: string): string => String(Number(token.replace(/,/g, "")));

/** A run of digits and commas counts as written ("1,840") and as a list ("190,160,70"). */
function readings(token: string): string[] {
  return [norm(token), ...token.split(",").filter(Boolean).map(norm)];
}

/** Every number the source states, plus each integer inside a stated range ("6..21" grounds 13). */
export function sourceNumbers(source: string): Set<string> {
  const out = new Set((source.match(NUMBER) ?? []).flatMap(readings));
  for (const [, a, b] of source.matchAll(RANGE)) {
    const lo = Number(a);
    const hi = Number(b);
    if (hi > lo && hi - lo <= MAX_RANGE_SPAN) {
      for (let n = lo; n <= hi; n++) out.add(String(n));
    }
  }
  return out;
}

// small counts (0-12) and 100 (the top of a percentage scale) are not claims
const SMALL_COUNT_MAX = 12;
const PERCENT_SCALE_TOP = "100";

/** Numbers typed into text that the source never states. */
export function ungrounded(text: string, source: Set<string>): string[] {
  const typed = (text.replace(SLOT, "").match(NUMBER) ?? []).map((n) =>
    n.replace(/,$/, ""),
  );
  return typed.filter(
    (n) =>
      !source.has(norm(n)) &&
      !(Number(norm(n)) <= SMALL_COUNT_MAX && !n.includes(".")) &&
      norm(n) !== PERCENT_SCALE_TOP,
  );
}

const ROOT_START = /root\s*=\s*Artifact\(/;
const STATEMENT_LINE = /^[A-Za-z_$][\w$]*\s*=/;

/** The program inside a reply: from the first `root = Artifact(`, statement lines only. */
export function extractProgram(reply: string): string {
  const start = reply.search(ROOT_START);
  if (start < 0) return reply;
  return reply
    .slice(start)
    .split("\n")
    .filter((line) => STATEMENT_LINE.test(line.trim()))
    .join("\n");
}
