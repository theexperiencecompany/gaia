#!/usr/bin/env node
/**
 * Fails when a utility class used in source emits no CSS.
 *
 * Tailwind v4 drops unknown utilities without a word: `text-foreground-500`
 * compiles to nothing, the element inherits, and the page looks plausible.
 * The v2 -> v3 migration shipped dozens of these.
 *
 * Why this version: the first cut matched escaped selector strings with
 * `css.includes(".w-1/2")`, which reported `w-60`, `w-1/2` and `w-[390px]` as
 * missing. Selector text is not a class list — Tailwind escapes `[`, `/`, `.`
 * and friends, and arbitrary values contain punctuation that no string match
 * survives. So parse the CSS and compare normalised class tokens instead.
 *
 * Run after `next build`:
 *   node scripts/audit-tailwind-classes.mjs
 */
import fs from "node:fs";
import path from "node:path";
import postcss from "postcss";

const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");
const NEXT_DIR = path.join(ROOT, ".next");

/**
 * Custom class names defined in our own CSS (hooks, not utilities). Anything
 * here is expected to have no Tailwind selector; they are matched by the
 * `definedCustomClasses` pass below instead.
 */
const CUSTOM_PREFIX_HINTS = [
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
  "openui-root", "whats-new-content", "cv-chat-message",
];

/** Dev-only routes are excluded from production and never ship. */
const IGNORED_PATH = /[\\/]dev[\\/]|\.dev\.tsx?$/;

const CLASS_ATTR =
  /(?:className|class)\s*=\s*(?:"([^"]*)"|'([^']*)'|\{`([^`]*)`\}|\{"([^"]*)"\})/g;

function collectUsedClasses() {
  const used = new Map();
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(tsx|jsx|ts|js)$/.test(entry.name) && !IGNORED_PATH.test(full)) {
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

/** Every class selector in the built CSS, unescaped back to source form. */
function collectEmittedClasses() {
  const files = [];
  const walk = (dir) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".css")) files.push(full);
    }
  };
  walk(NEXT_DIR);
  if (files.length === 0) {
    console.error(`No CSS under ${NEXT_DIR}. Run \`next build\` first.`);
    process.exit(2);
  }

  const emitted = new Set();
  const UNESCAPE = /\\(.)/g;
  for (const file of files) {
    const root = postcss.parse(fs.readFileSync(file, "utf8"), { from: file });
    root.walkRules((rule) => {
      for (const sel of rule.selectors) {
        for (const m of sel.matchAll(/\.((?:\\.|[^\s.:>+~,[\]()#*])+)/g)) {
          const token = m[1].replace(UNESCAPE, "$1");
          emitted.add(token);
          // Tailwind emits `hover:opacity-90` as `.hover\\:opacity-90:hover`.
          // The source side is compared variant-stripped, so the emitted side
          // has to offer the bare form too, or every variant looks orphaned.
          const bare = bareClass(token);
          if (bare !== token) emitted.add(bare);
        }
      }
    });
  }
  return emitted;
}

/** Variants (`dark:`, `hover:`) compile to a plain class, not a variant class. */
function bareClass(cls) {
  return cls
    .replace(/^!/, "")
    .replace(/!$/, "")
    .split(":")
    .pop()
    .replace(/^(group|peer)-(\[[^\]]+\]|[a-z-]+):/, "");
}

function looksLikeUtility(cls) {
  if (CUSTOM_PREFIX_HINTS.includes(cls)) return false;
  const base = bareClass(cls);
  if (!base || CUSTOM_PREFIX_HINTS.includes(base)) return false;
  if (/^(prose|group|peer|data|aria|has|not|supports|motion)-/.test(base)) {
    return true;
  }
  if (base.includes("-") || base.includes("[")) return true;
  return /^(flex|grid|block|hidden|inline|contents|relative|absolute|fixed|sticky|static|italic|underline|truncate|uppercase|capitalize|transition|transform|grow|shrink|border|rounded|shadow|outline|ring|container|sr-only)$/.test(
    base,
  );
}

const used = collectUsedClasses();
const emitted = collectEmittedClasses();

const orphans = [];
let checked = 0;
for (const [cls, files] of used) {
  if (!looksLikeUtility(cls)) continue;
  checked += 1;
  if (emitted.has(bareClass(cls))) continue;
  orphans.push({ cls, files: [...files].slice(0, 3), count: files.size });
}

orphans.sort((a, b) => b.count - a.count || a.cls.localeCompare(b.cls));

if (orphans.length === 0) {
  console.log(`✓ ${checked} utilities all resolve to CSS.`);
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
