import { globSync, readFileSync } from "node:fs";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss, { type Container, type Root } from "postcss";
import { describe, expect, it } from "vitest";

/**
 * A `var(--x)` with no fallback and no definition is invalid at computed-value
 * time, so the whole declaration silently drops: a transition, a border width
 * or a field background vanishes with no build error.
 */
const WEB_DIR = path.resolve(__dirname, "../..");
const STYLES = path.join(WEB_DIR, "src/app/styles");

// base.css ships on every route; each area sheet ships on top of it.
const AREAS = ["app", "marketing", "content"] as const;

// Tokens HeroUI's react-aria layer writes as inline style on the element it
// renders, so no stylesheet can define them.
const HEROUI_RUNTIME_TOKENS = new Set([
  // react-aria-components Popover.mjs + ComboBox.mjs: the trigger's measured width.
  "--trigger-width",
  // react-aria-components Popover.mjs + Tooltip.mjs: transform-origin at the trigger.
  "--trigger-anchor-point",
  // react-aria useDisclosure.mjs: setProperty() on the Accordion/Disclosure panel.
  "--disclosure-panel-height",
  // react-aria-components Modal.mjs: the visual viewport height on the overlay.
  "--visual-viewport-height",
]);

// Radix (the shadcn primitives in components/ui) writes --radix-* inline the same way.
const RADIX_RUNTIME_PREFIX = "--radix-";

const NO_FALLBACK_VAR = /var\(\s*(--[\w-]+)\s*\)/g;
// `{ "--x": ... }` style objects, `setProperty("--x", ...)`, next/font `variable: "--x"`.
const SOURCE_SET_VAR =
  /(?:["'](--[\w-]+)["']\s*:|setProperty\(\s*["'](--[\w-]+)["']|variable:\s*["'](--[\w-]+)["'])/g;

type Scope = "both" | "light" | "dark";

/** The theme a rule's selector chain is gated on; an ungated rule defines the token in both. */
function scopeOf(container: Container | undefined): Scope {
  const chain: string[] = [];
  for (let node = container; node && node.type !== "root"; ) {
    if (node.type === "rule")
      chain.push((node as { selector: string }).selector);
    node = node.parent as Container | undefined;
  }
  const selectors = chain.flatMap((s) => s.split(","));
  if (selectors.length === 0) return "both";
  const dark = (s: string) =>
    /\.dark\b|theme="?dark"?/.test(s) && !/:not\(\.dark\)/.test(s);
  const light = (s: string) =>
    /\.light\b|theme="?light"?|:not\(\.dark\)/.test(s);
  if (chain.some((rule) => rule.split(",").every(dark))) return "dark";
  if (chain.some((rule) => rule.split(",").every(light))) return "light";
  return "both";
}

function unresolvedTokens(roots: Root[], runtime: Set<string>): string[] {
  const used = new Set<string>();
  const scopes = new Map<string, Set<Scope>>();
  const define = (token: string, scope: Scope) => {
    if (!scopes.has(token)) scopes.set(token, new Set());
    scopes.get(token)?.add(scope);
  };
  for (const root of roots) {
    root.walkDecls((decl) => {
      if (decl.prop.startsWith("--"))
        define(decl.prop, scopeOf(decl.parent as Container));
      for (const [, token] of decl.value.matchAll(NO_FALLBACK_VAR))
        used.add(token);
    });
    root.walkAtRules("property", (rule) => define(rule.params.trim(), "both"));
  }
  const resolves = (token: string) => {
    const found = scopes.get(token);
    if (!found) return false;
    return found.has("both") || (found.has("light") && found.has("dark"));
  };
  return [...used]
    .filter(
      (token) => !runtime.has(token) && !token.startsWith(RADIX_RUNTIME_PREFIX),
    )
    .filter((token) => !resolves(token))
    .sort();
}

function sourceSetTokens(): Set<string> {
  const files = globSync("src/**/*.{ts,tsx}", { cwd: WEB_DIR });
  const tokens = new Set(HEROUI_RUNTIME_TOKENS);
  for (const file of files) {
    const source = readFileSync(path.join(WEB_DIR, file), "utf8");
    for (const match of source.matchAll(SOURCE_SET_VAR)) {
      tokens.add(match[1] ?? match[2] ?? match[3]);
    }
  }
  return tokens;
}

async function compile(sheet: string): Promise<Root> {
  const from = path.join(STYLES, `${sheet}.css`);
  const result = await postcss([tailwind()]).process(
    readFileSync(from, "utf8"),
    { from },
  );
  return result.root;
}

describe("unresolvedTokens", () => {
  const roots = (css: string) => [postcss.parse(css)];

  it("flags a token used with no definition", () => {
    expect(
      unresolvedTokens(roots(".a { color: var(--nope); }"), new Set()),
    ).toEqual(["--nope"]);
  });

  it("flags a token defined only for the dark theme", () => {
    const css = ".dark { --ink: #fff; } .a { color: var(--ink); }";
    expect(unresolvedTokens(roots(css), new Set())).toEqual(["--ink"]);
  });

  it("flags a token defined only for the light theme", () => {
    const css =
      '[data-theme="light"] { --ink: #000; } .a { color: var(--ink); }';
    expect(unresolvedTokens(roots(css), new Set())).toEqual(["--ink"]);
  });

  it("accepts :root, a light+dark pair, @property, a fallback and runtime tokens", () => {
    const css = [
      ":root { --a: 1px; }",
      ".light { --b: #000; } .dark { --b: #fff; }",
      "@property --c { syntax: '*'; inherits: false; initial-value: 0; }",
      ".button { --d: 2px; }",
      ".x { width: var(--a); color: var(--b); top: var(--c); left: var(--d);",
      "  height: var(--e, 0); min-width: var(--trigger-width); max-height: var(--radix-h); }",
    ].join("\n");
    expect(unresolvedTokens(roots(css), new Set(["--trigger-width"]))).toEqual(
      [],
    );
  });
});

describe("every token the shipped stylesheets read is defined", () => {
  const runtime = sourceSetTokens();

  it("base.css", async () => {
    expect(unresolvedTokens([await compile("base")], runtime)).toEqual([]);
  });

  for (const area of AREAS) {
    it(`base.css + ${area}.css`, async () => {
      const roots = [await compile("base"), await compile(area)];
      expect(unresolvedTokens(roots, runtime)).toEqual([]);
    });
  }
});
