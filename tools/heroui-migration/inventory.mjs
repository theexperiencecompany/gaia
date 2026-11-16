#!/usr/bin/env node
/**
 * HeroUI v2 -> v3 inventory scanner.
 * Zero dependencies. Walks the app source, finds every HeroUI import + JSX usage,
 * classifies each one by migration risk, and writes inventory.json.
 *
 * Usage:
 *   node tools/heroui-migration/inventory.mjs                 # scan default roots
 *   node tools/heroui-migration/inventory.mjs --json          # machine output only
 *   node tools/heroui-migration/inventory.mjs apps/web/src    # custom roots
 */
import { readdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { join, extname, relative } from "node:path";

const ROOTS = process.argv.slice(2).filter((a) => !a.startsWith("-"));
const SCAN_ROOTS = ROOTS.length ? ROOTS : ["apps/web/src", "libs"];
const JSON_ONLY = process.argv.includes("--json");

/** Migration metadata, sourced from the HeroUI v3 migration guides (MCP). */
const META = {
  // ---- Tier A: prop/variant swaps, mechanically codemodable ----
  Button: { tier: "A", v3: "Button", note: 'variant ensembles; isPending; no color/radius; no startContent' },
  Chip: { tier: "A", v3: "Chip", note: 'variant primary|secondary|tertiary|soft; color accent; use Chip.Label' },
  Spinner: { tier: "A", v3: "Spinner", note: "size/color trimmed" },
  Skeleton: { tier: "A", v3: "Skeleton", note: "isLoaded -> isLoading; animation prop renamed" },
  Kbd: { tier: "A", v3: "Kbd", note: "keys prop, compound Kbd.Content" },
  Link: { tier: "A", v3: "Link", note: "onPress, no underline variants" },
  Avatar: { tier: "A", v3: "Avatar", note: "compound: Avatar.Image / Avatar.Fallback" },
  Badge: { tier: "A", v3: "Badge", note: "colour/variant vocab updated; no radius" },

  // ---- Tier B: structural / compound component rewrite ----
  Input: { tier: "B", v3: "TextField + Label + Input + FieldError", note: "label/description/errorMessage become children; InputGroup for start/endContent" },
  Select: { tier: "B", v3: "Select (RAC)", note: "item id + textValue; Select.Popover; no SelectItem" },
  Dropdown: { tier: "B", v3: "Dropdown (RAC)", note: "items use id + textValue; Dropdown.Menu/Item compound" },
  Autocomplete: { tier: "B", v3: "ComboBox", note: "renamed component; item id + textValue" },
  Modal: { tier: "B", v3: "Modal", note: "compound Modal.Header/Body/Footer; backdrop unified; asChild removed" },
  Tabs: { tier: "B", v3: "Tabs", note: "Tab key->id; SelectionIndicator; compound panels" },
  Accordion: { tier: "B", v3: "Accordion", note: "item id + textValue; Accordion.Item" },
  Popover: { tier: "B", v3: "Popover", note: "Popover.Trigger/.Content; asChild removed" },
  Checkbox: { tier: "B", v3: "Checkbox", note: "compound Checkbox.Control/Indicator" },
  Radio: { tier: "B", v3: "RadioGroup + Radio", note: "RadioGroup wrapper required" },
  Switch: { tier: "B", v3: "Switch", note: "compound Switch.Control/Thumb" },
  Slider: { tier: "B", v3: "Slider", note: "compound Slider.Track/Thumb" },
  Card: { tier: "B", v3: "Card", note: "Card.Header/.Body/.Footer; no isPressable" },
  NumberInput: { tier: "B", v3: "NumberField", note: "renamed; compound" },
  Pagination: { tier: "B", v3: "Pagination", note: "RAC-based; item props + size/variant" },
  Progress: { tier: "A", v3: "ProgressBar", note: "renamed Progress -> ProgressBar; CircularProgress -> ProgressCircle" },
  Table: { tier: "B", v3: "Table", note: "RAC Table.Header/Column/Body/Row/Cell" },
  Snippet: { tier: "REMOVED", v3: "—", note: "removed in v3: use plain code block + copy button" },
  User: { tier: "REMOVED", v3: "—", note: "removed in v3: compose Avatar + text" },
  Divider: { tier: "A", v3: "Separator", note: "renamed: Divider -> Separator" },
  ScrollShadow: { tier: "A", v3: "ScrollShadow", note: "orientation prop only" },
  Tooltip: { tier: "A", v3: "Tooltip", note: "Tooltip.Trigger/.Content; delay prop renamed" },
};

/** Props that no longer exist in v3 (any component). */
const DROPPED_PROPS = ["color", "radius", "asChild", "classNames", "startContent", "endContent", "label", "description", "errorMessage", "labelPlacement", "isClearable"];
/** Props renamed 1:1 in v3. */
const RENAMED_PROPS = { isLoading: "isPending", onValueChange: "onChange", disableAnimation: "className-based", isReadOnly: "isReadOnly" };
/** Files that are pure config/global concerns. */
const CONFIG_PATTERNS = [
  [/HeroUIProvider/, "HeroUIProvider must be removed (no provider in v3)"],
  [/heroui\(\)/, "remove heroui() plugin from Tailwind config"],
  [/@heroui\/theme/, "swap @heroui/theme -> @heroui/styles"],
  [/framer-motion/, "framer-motion no longer required"],
  [/useDisclosure/, "useDisclosure -> useOverlayState"],
];

const CODE_EXT = new Set([".tsx", ".ts", ".jsx", ".js"]);
const DOC_EXT = new Set([".md", ".mdx"]);
const SKIP_DIRS = new Set(["node_modules", ".next", "dist", "build", ".turbo", "coverage", ".git", ".claude", ".agents"]);

function walk(dir, out = []) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    if (e.name.startsWith(".") && e.name !== ".") continue;
    if (SKIP_DIRS.has(e.name)) continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (CODE_EXT.has(extname(e.name))) out.push(p);
  }
  return out;
}

/** Extract the JSX opening tag body starting at `<Name`, respecting {} and quotes. */
function readTag(src, start) {
  let i = start;
  let brace = 0;
  let quote = null;
  while (i < src.length) {
    const c = src[i];
    if (quote) {
      if (c === "\\") i++;
      else if (c === quote) quote = null;
    } else if (c === '"' || c === "'" || c === "`") quote = c;
    else if (c === "{") brace++;
    else if (c === "}") brace--;
    else if (c === ">" && brace === 0) return src.slice(start, i + 1);
    i++;
  }
  return src.slice(start, Math.min(start + 4000, src.length));
}

const IMPORT_RE = /import\s+(?:type\s+)?(?:([\w*\s{},]+)\s+from\s+)?["'](@heroui\/[^"']+)["']/g;
const AT_REACT_RE = /import\s+(?:type\s+)?{([^}]+)}\s+from\s+["']@heroui\/react["']/g;

function parseImports(src) {
  const byPkg = {}; // pkg -> Set(names)
  const all = new Set();
  for (const m of src.matchAll(IMPORT_RE)) {
    const names = (m[1] || "")
      .replace(/[{}]/g, " ")
      .split(",")
      .map((s) => s.trim().split(/\s+as\s+/)[0].trim())
      .filter((s) => s && s !== "type");
    (byPkg[m[2]] ??= new Set());
    for (const n of names) {
      byPkg[m[2]].add(n);
      all.add(n);
    }
  }
  for (const m of src.matchAll(AT_REACT_RE)) {
    for (const raw of m[1].split(",")) {
      const n = raw.trim().split(/\s+as\s+/)[0].trim();
      if (n && n !== "type") all.add(n);
    }
  }
  return { byPkg, all };
}

function lineOf(src, idx) {
  let n = 1;
  for (let i = 0; i < idx; i++) if (src.charCodeAt(i) === 10) n++;
  return n;
}

function scanFile(path) {
  const src = readFileSync(path, "utf8");
  if (!src.includes("@heroui/")) return null;
  const { byPkg, all } = parseImports(src);
  const usages = [];

  for (const name of all) {
    if (!META[name]) continue;
    const tagRe = new RegExp(`<${name}(?=[\\s/>])`, "g");
    for (const m of src.matchAll(tagRe)) {
      const tag = readTag(src, m.index);
      const props = {};
      for (const p of tag.matchAll(/(\w+)(?:=(?:"([^"]*)"|'([^']*)'|\{([^}]*)\}))?/g)) {
        const key = p[1];
        if (key === name) continue;
        props[key] = p[2] ?? p[3] ?? (p[4] !== undefined ? "{expr}" : true);
      }
      usages.push({
        component: name,
        line: lineOf(src, m.index),
        tier: META[name].tier,
        v3: META[name].v3,
        dropped: Object.keys(props).filter((k) => DROPPED_PROPS.includes(k)),
        renamed: Object.keys(props).filter((k) => RENAMED_PROPS[k]).map((k) => `${k}->${RENAMED_PROPS[k]}`),
        selfClosing: /\/>$/.test(tag),
      });
    }
  }

  const globals = [];
  for (const [re, note] of CONFIG_PATTERNS) if (re.test(src)) globals.push(note);

  const hooks = [...all].filter((n) => /^use[A-Z]/.test(n));

  return {
    file: relative(process.cwd(), path),
    packages: Object.keys(byPkg),
    imports: [...all],
    hooks,
    globals: [...new Set(globals)],
    usages,
  };
}

const files = SCAN_ROOTS.flatMap((r) => walk(join(process.cwd(), r)));
const scanned = files.map(scanFile).filter(Boolean);

/** Docs that describe HeroUI usage also go stale in this migration. */
function scanDocs() {
  const files = [];
  const roots = ["docs", "apps/web", "libs", ".", "AGENTS.md", "README.md"].filter((r) => existsSync(r));
  const walkDocs = (dir) => {
    let entries;
    try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (SKIP_DIRS.has(e.name) || e.name === "tools") continue;
      const p = join(dir, e.name);
      if (e.isDirectory()) walkDocs(p);
      else if (DOC_EXT.has(extname(e.name))) files.push(p);
    }
  };
  for (const r of roots) {
    const st = statSync(r);
    if (st.isDirectory()) walkDocs(r);
    else if (DOC_EXT.has(extname(r))) files.push(r);
  }
  const out = [];
  for (const f of new Set(files)) {
    const src = readFileSync(f, "utf8");
    if (!/heroui|HeroUI/i.test(src)) continue;
    const mentions = {};
    for (const tag of src.matchAll(/\b(Button|Chip|Input|Modal|Select|Dropdown|Tabs|Accordion|Card|Table|Tooltip|Spinner|Skeleton|Avatar|Checkbox|Switch|Slider|Pagination|Progress|Badge|Kbd|Divider|Link|Popover|Textarea|Snippet|User)\b/g)) {
      mentions[tag[1]] = (mentions[tag[1]] || 0) + 1;
    }
    const historical = /(release-notes|CHANGELOG|content\/blog|\/blog\/)/i.test(f);
    const hasImports = /from\s+["']@heroui|@heroui\/(react|[a-z-]+)/.test(src);
    const kind = historical ? "historical" : hasImports ? "guide" : "mention";
    out.push({ file: relative(process.cwd(), f), kind, mentions });
  }
  return out;
}

// ---- aggregate ----
const byComponent = {};
for (const f of scanned) {
  for (const u of f.usages) {
    const b = (byComponent[u.component] ??= {
      component: u.component,
      tier: u.tier,
      v3: u.v3,
      note: META[u.component].note,
      sites: 0,
      files: new Set(),
      droppedProps: {},
      renamedProps: {},
    });
    b.sites++;
    b.files.add(f.file);
    for (const p of u.dropped) b.droppedProps[p] = (b.droppedProps[p] || 0) + 1;
    for (const p of u.renamed) b.renamedProps[p] = (b.renamedProps[p] || 0) + 1;
  }
}

const rows = Object.values(byComponent)
  .map((b) => ({ ...b, files: b.files.size }))
  .sort((a, b) => (a.tier === "REMOVED") - (b.tier === "REMOVED") || b.sites - a.sites);

const totals = {
  sourceFilesScanned: files.length,
  filesTouchingHeroUI: scanned.length,
  jsxSites: rows.reduce((n, r) => n + r.sites, 0),
  tierA: rows.filter((r) => r.tier === "A").reduce((n, r) => n + r.sites, 0),
  tierB: rows.filter((r) => r.tier === "B").reduce((n, r) => n + r.sites, 0),
  removed: rows.filter((r) => r.tier === "REMOVED").reduce((n, r) => n + r.sites, 0),
  globalFindingFiles: scanned.filter((f) => f.globals.length).length,
  hookImports: [...new Set(scanned.flatMap((f) => f.hooks))].sort(),
};

const docs = scanDocs();
totals.heroUIDocs = docs.length;
totals.heroUIDocsToUpdate = docs.filter((d) => d.kind === "guide").length;
totals.heroUIDocsHistorical = docs.filter((d) => d.kind === "historical").length;
const inventory = { generatedAt: new Date().toISOString(), totals, components: rows, files: scanned, docs };

const outPath = join(process.cwd(), "tools/heroui-migration/inventory.json");
writeFileSync(outPath, JSON.stringify(inventory, null, 2));

if (JSON_ONLY) {
  process.stdout.write(JSON.stringify(inventory, null, 2));
} else {
  const pad = (s, n) => String(s).padEnd(n);
  console.log(`\nHeroUI v2 -> v3 inventory   (${scanned.length}/${files.length} source files touched)\n`);
  console.log(pad("COMPONENT", 16) + pad("TIER", 9) + pad("SITES", 7) + pad("FILES", 7) + "NOTES");
  console.log("-".repeat(100));
  for (const r of rows) {
    const dp = Object.entries(r.droppedProps).map(([k, v]) => `${k}x${v}`).join(",");
    console.log(pad(r.component, 16) + pad(r.tier, 9) + pad(r.sites, 7) + pad(r.files, 7) + (dp || ""));
  }
  console.log("-".repeat(100));
  console.log(
    `total JSX sites: ${totals.jsxSites}  |  A(mechanical): ${totals.tierA}  B(structural): ${totals.tierB}  removed: ${totals.removed}`,
  );
  if (totals.hookImports.length) console.log(`hooks imported: ${totals.hookImports.join(", ")}`);
  const guides = docs.filter((d) => d.kind === "guide");
  const historical = docs.filter((d) => d.kind === "historical");
  if (docs.length) {
    console.log(`\ndocs referencing HeroUI: ${guides.length} to update, ${historical.length} historical (leave alone), ${docs.length - guides.length - historical.length} passing mentions`);
    for (const d of guides.slice(0, 12)) console.log(`  ${d.file}`);
  }
  console.log(`\nwrote ${outPath}`);
}
