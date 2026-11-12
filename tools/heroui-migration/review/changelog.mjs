#!/usr/bin/env node
/**
 * The component change log: for every changed web file, which HeroUI v2
 * components became which v3 compound parts, and which props and variants were
 * remapped, with the decisions.json rule that explains each remap.
 *
 *   node review/changelog.mjs --repo <git dir> --before <sha> --after <sha> [--out DIR]
 *
 * Output: <out>/report/changelog.json
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DEFAULT_OUT } from "./config.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i === -1 ? d : argv[i + 1];
};
const REPO = resolve(arg("repo", "."));
const BEFORE = arg("before");
const AFTER = arg("after");
const OUT = resolve(arg("out", DEFAULT_OUT));
if (!BEFORE || !AFTER) throw new Error("--before <sha> and --after <sha> are required");

const git = (...a) => execFileSync("git", ["-C", REPO, ...a], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
const show = (ref, file) => {
  try {
    return execFileSync("git", ["-C", REPO, "show", `${ref}:${file}`], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] });
  } catch {
    return "";
  }
};

const { decisions, drop } = JSON.parse(readFileSync(join(HERE, "..", "decisions.json"), "utf8"));
/** The codemod's joint Button table (codemods/v3-props.cjs): colour folds into variant. */
const BUTTON_PAIRS = {
  "default|solid": "primary", "primary|solid": "primary", "secondary|solid": "secondary",
  "success|solid": "primary", "warning|solid": "primary", "danger|solid": "danger",
  "primary|bordered": "secondary", "primary|light": "tertiary", "primary|flat": "tertiary",
  "primary|faded": "secondary", "primary|ghost": "ghost", "danger|flat": "danger-soft",
  "danger|bordered": "danger-soft", "default|bordered": "secondary", "default|flat": "tertiary",
  "default|light": "tertiary", "default|ghost": "ghost", "secondary|flat": "tertiary",
  "secondary|light": "tertiary", "secondary|bordered": "secondary",
};
/** The codemod's prop renames (codemods/v3-props.cjs RENAME). */
const RENAMES = { isLoading: "isPending", onValueChange: "onChange" };

/** v2 flat names and the v3 compound root they belong to. Order matters: longest prefix first. */
const FAMILIES = [
  ["Autocomplete", "ComboBox"], ["Accordion", "Accordion"], ["Avatar", "Avatar"], ["Breadcrumb", "Breadcrumbs"],
  ["Checkbox", "Checkbox"], ["Chip", "Chip"], ["Divider", "Separator"], ["Drawer", "Drawer"], ["Dropdown", "Dropdown"],
  ["Input", "TextField"], ["Textarea", "TextArea"], ["Kbd", "Kbd"], ["Listbox", "ListBox"], ["Modal", "Modal"],
  ["Pagination", "Pagination"], ["Popover", "Popover"], ["Progress", "ProgressBar"], ["Radio", "RadioGroup"],
  ["ScrollShadow", "ScrollShadow"], ["Select", "Select"], ["Skeleton", "Skeleton"], ["Slider", "Slider"],
  ["Spinner", "Spinner"], ["Switch", "Switch"], ["Tab", "Tabs"], ["Table", "Table"], ["Tooltip", "Tooltip"],
  ["Button", "Button"], ["Card", "Card"], ["Link", "Link"], ["Image", "img"], ["useDisclosure", "useOverlayState"],
];
const V3_ROOT_ALIASES = { TextField: ["TextField", "InputGroup", "SearchField", "Input", "Label", "FieldError", "Description"], Select: ["Select", "ListBox"], Dropdown: ["Dropdown", "Menu"], Tabs: ["Tabs"], Modal: ["Modal", "AlertDialog"] };
const familyOf = (name) => FAMILIES.find(([p]) => name.startsWith(p));

function heroImports(src) {
  const names = new Set();
  for (const m of src.matchAll(/import\s+(?:type\s+)?\{([^}]*)\}\s+from\s+["'](@heroui\/[^"']+)["']/g))
    for (const spec of m[1].split(",")) {
      const local = spec.trim().replace(/^type\s+/, "").split(/\s+as\s+/).pop();
      if (local) names.add(local);
    }
  return names;
}

function usage(src, names) {
  const counts = {};
  for (const m of src.matchAll(/<([A-Z][A-Za-z]*(?:\.[A-Z][A-Za-z]*)*)[\s/>]/g)) {
    const root = m[1].split(".")[0];
    if (names.has(root)) counts[m[1]] = (counts[m[1]] ?? 0) + 1;
  }
  for (const name of names) if (/^use[A-Z]/.test(name)) {
    const n = (src.match(new RegExp(`\\b${name}\\(`, "g")) ?? []).length;
    if (n) counts[name] = n;
  }
  return counts;
}

const ATTR = /\b([a-zA-Z][\w-]*)=("[^"]*"|\{[^{}]*\})/g;

/** Attribute changes inside each diff hunk, attributed to the JSX tag they sit under. */
function propChanges(file) {
  const diff = git("diff", "-U4", BEFORE, AFTER, "--", file);
  const changes = [];
  for (const hunk of diff.split(/\n(?=@@)/).slice(1)) {
    let tag = null;
    const removed = [];
    const added = [];
    for (const line of hunk.split("\n").slice(1)) {
      const sign = line[0];
      const body = line.slice(1);
      const t = [...body.matchAll(/<([A-Z][A-Za-z]*(?:\.[A-Z][A-Za-z]*)*)/g)].pop();
      if (t && sign !== "+") tag = t[1];
      for (const m of body.matchAll(ATTR)) {
        const rec = { tag: t?.[1] ?? tag, name: m[1], value: m[2] };
        if (sign === "-") removed.push(rec);
        else if (sign === "+") added.push(rec);
      }
    }
    const key = (r) => `${r.name}=${r.value}`;
    const addedKeys = new Set(added.map(key));
    const removedKeys = new Set(removed.map(key));
    const gone = removed.filter((r) => !addedKeys.has(key(r)) && r.name !== "className");
    const fresh = added.filter((r) => !removedKeys.has(key(r)) && r.name !== "className");
    const color = gone.find((r) => r.name === "color");
    for (const r of gone) {
      const renamed = RENAMES[r.name] ? fresh.find((a) => a.name === RENAMES[r.name]) : null;
      const same = fresh.find((a) => a.name === r.name);
      const to = same ?? renamed;
      if (to) fresh.splice(fresh.indexOf(to), 1);
      changes.push({ component: r.tag, from: `${r.name}=${r.value}`, to: to ? `${to.name}=${to.value}` : null, rule: ruleFor(r, to, color) });
    }
    for (const a of fresh) changes.push({ component: a.tag, from: null, to: `${a.name}=${a.value}`, rule: null });
  }
  return changes;
}

const unquote = (v) => v?.replace(/^"|"$/g, "");
function ruleFor(removed, added, color) {
  const comp = removed.tag?.split(".")[0].toLowerCase();
  if (!added) return drop?.[comp]?.includes(removed.name) ? `dropped: on decisions.json's ${comp} drop list` : "removed";
  if (removed.name !== added.name) return `renamed ${removed.name} -> ${added.name}`;
  const from = unquote(removed.value);
  const to = unquote(added.value);
  if (comp === "button" && removed.name === "variant") {
    const pair = `${unquote(color?.value) ?? "default"}|${from}`;
    if (BUTTON_PAIRS[pair] === to) return `Button color x variant table: ${pair} -> ${to}`;
  }
  if (decisions?.[comp]?.[removed.name]?.[from] === to) return `decisions.json ${comp}.${removed.name}.${from} -> ${to}`;
  return "manual: not a decisions.json rule";
}

const files = git("diff", "--name-only", BEFORE, AFTER, "--", "apps/web", "libs/shared/ts")
  .split("\n")
  .filter((f) => /\.(tsx?|css)$/.test(f));
const entries = [];
for (const file of files) {
  const a = show(BEFORE, file);
  const b = show(AFTER, file);
  const v2 = heroImports(a);
  const v3 = heroImports(b);
  const before = usage(a, v2);
  const after = usage(b, v3);
  const fams = {};
  for (const [name, n] of Object.entries(before)) {
    const fam = familyOf(name.split(".")[0]);
    const root = fam?.[1] ?? name.split(".")[0];
    (fams[root] ??= { v2: {}, v3: {} }).v2[name] = n;
  }
  for (const [name, n] of Object.entries(after)) {
    const root0 = name.split(".")[0];
    const root = Object.entries(V3_ROOT_ALIASES).find(([, al]) => al.includes(root0))?.[0] ?? root0;
    (fams[root] ??= { v2: {}, v3: {} }).v3[name] = n;
  }
  const stat = git("diff", "--numstat", BEFORE, AFTER, "--", file).trim().split(/\s+/);
  entries.push({
    file,
    added: Number(stat[0]) || 0,
    removed: Number(stat[1]) || 0,
    importsRemoved: [...v2].filter((n) => !v3.has(n)).sort(),
    importsAdded: [...v3].filter((n) => !v2.has(n)).sort(),
    components: Object.entries(fams)
      .map(([root, f]) => ({ root, v2: f.v2, v3: f.v3 }))
      .filter((c) => JSON.stringify(c.v2) !== JSON.stringify(c.v3))
      .sort((p, q) => p.root.localeCompare(q.root)),
    props: propChanges(file),
  });
}
mkdirSync(join(OUT, "report"), { recursive: true });
writeFileSync(join(OUT, "report", "changelog.json"), JSON.stringify({ before: BEFORE, after: AFTER, files: entries }));
const remaps = entries.reduce((n, e) => n + e.props.filter((p) => p.from && p.to).length, 0);
console.log(`${entries.length} changed files, ${remaps} prop remaps -> ${join(OUT, "report/changelog.json")}`);
