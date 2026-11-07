#!/usr/bin/env node
/**
 * Fails when a Tailwind utility used in source emits no CSS.
 *
 * Tailwind v4 silently drops unknown utilities: `text-foreground-500` compiles
 * to nothing, the element inherits its parent's colour, and the page looks
 * plausible. The v2 -> v3 migration shipped several of these (grey body text
 * rendering white, v2 size/radius tokens vanishing) because nothing errored.
 *
 * Run after `next build`, against the emitted stylesheets:
 *   node scripts/audit-tailwind-classes.mjs
 *
 * Exit 1 with the offending classes when any real utility is orphaned.
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");
const CSS_DIR = path.join(ROOT, ".next", "static", "chunks");

/** Classes that are intentionally not Tailwind utilities (hooks, custom CSS). */
const ALLOW = new Set([
  // custom css hooks / state selectors defined in base.css or feature css
  "privacy-policy", "bot-actions", "group-topbtns", "markdown-table",
  "slash-command-dropdown", "tool-icon-btn", "chat-demo-input",
  "landing_img_container", "whats-new-content", "cv-auto", "cv-chat-message",
  "cv-notification-card", "cv-todo-item", "editor", "tiptap", "no-scrollbar",
  "scrollbar-faint", "scrollbar-hover", "electron-drag", "monospace",
  "heroimage", "navbar", "sidebar", "searchbar", "chat_bubble",
  "chat_bubble_container", "conversation_history", "imessage-bubble",
  "imessage-from-them", "imessage-from-me", "imessage-grouped-first",
  "imessage-grouped-last", "imessage-grouped-middle", "user_container_inner",
  "animate-scale-in", "animate-scale-in-blur", "bg-custom-gradient",
  "bg-custom-gradient2", "mcp-app-surface", "openui-document", "mail-editor",
  "ph-no-capture", "pdf_container", "searchbar_container", "hero-split-word",
  "hero-fade-in", "sbi-anim", "chat-bubble-pop", "chat-demo-tap",
  "openui-root", "prose-zinc",
]);

const CLASS_ATTR = /(?:className|class)\s*=\s*(?:"([^"]*)"|'([^']*)'|\{`([^`]*)`\}|\{"([^"]*)"\})/g;

function collectUsedClasses() {
  const used = new Map();
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(tsx|jsx|ts|js)$/.test(entry.name)) {
        const text = fs.readFileSync(full, "utf8");
        for (const m of text.matchAll(CLASS_ATTR)) {
          let raw = m[1] ?? m[2] ?? m[3] ?? m[4] ?? "";
          raw = raw.replace(/\$\{[^}]*\}/g, " ");
          for (const tok of raw.split(/\s+/)) {
            const cls = tok.trim();
            if (!cls || cls.length < 2 || /[<>={}()]/.test(cls)) continue;
            if (!used.has(cls)) used.set(cls, new Set());
            used.get(cls).add(path.relative(SRC, full));
          }
        }
      }
    }
  };
  walk(SRC);
  return used;
}

function readEmittedCss() {
  if (!fs.existsSync(CSS_DIR)) {
    console.error(`No build output at ${CSS_DIR}. Run \`next build\` first.`);
    process.exit(2);
  }
  return fs
    .readdirSync(CSS_DIR)
    .filter((f) => f.endsWith(".css"))
    .map((f) => fs.readFileSync(path.join(CSS_DIR, f), "utf8"))
    .join("\n");
}

const escapeSelector = (cls) =>
  cls.replace(/[^a-zA-Z0-9_-]/g, (ch) => `\\${ch}`);

/** Only test tokens that look like real utilities, not custom hooks. */
function isUtilityLike(cls) {
  if (ALLOW.has(cls)) return false;
  // strip variants and important markers: dark:hover:text-red-500
  const base = cls.split(":").pop().replace(/^!/, "").replace(/!$/, "");
  if (!base) return false;
  if (/^(prose|group|peer|data|aria|has|not)-/.test(base)) return true;
  // utilities carry a dash, a bracket, or a known bare name
  return (
    base.includes("-") ||
    base.includes("[") ||
    /^(flex|grid|block|hidden|inline|contents|relative|absolute|fixed|sticky|static|italic|underline|truncate|uppercase|capitalize|transition|transform|grow|shrink|border|rounded|shadow|outline|ring|container|sr-only)$/.test(
      base,
    )
  );
}

const used = collectUsedClasses();
const css = readEmittedCss();

const orphans = [];
for (const [cls, files] of used) {
  if (!isUtilityLike(cls)) continue;
  const base = cls.split(":").pop().replace(/^!/, "").replace(/!$/, "");
  if (
    css.includes(`.${escapeSelector(base)}`) ||
    css.includes(`.${escapeSelector(cls)}`)
  ) {
    continue;
  }
  orphans.push({ cls, files: [...files].slice(0, 3), count: files.size });
}

orphans.sort((a, b) => b.count - a.count || a.cls.localeCompare(b.cls));

const checked = [...used.keys()].filter(isUtilityLike).length;
if (orphans.length === 0) {
  console.log(`✓ ${checked} utilities all emit CSS.`);
  process.exit(0);
}

console.error(
  `\n✗ ${orphans.length} of ${checked} utilities emit NO CSS — they render as inherited/unstyled.\n` +
    `  Tailwind v4 drops unknown utilities silently. Add the token, fix the\n` +
    `  class, or allowlist it in scripts/audit-tailwind-classes.mjs.\n`,
);
for (const o of orphans) {
  console.error(`  ${String(o.count).padStart(3)}x  ${o.cls}`);
  for (const f of o.files) console.error(`        ${f}`);
}
console.error("");
process.exit(1);
