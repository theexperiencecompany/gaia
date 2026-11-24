import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";

/**
 * The Tailwind utilities a rendered page uses that none of its stylesheets define.
 *
 * Tailwind emits a class only when a file its `@source` lines name contains it,
 * so an element rendered from an unlisted file ships unstyled with a green
 * build. Whether a class is a utility is Tailwind's own answer, compiled against
 * base.css's theme, so component and marker classes need no list here.
 */
const BASE_CSS = path.resolve(
  import.meta.dirname,
  "../../src/app/styles/base.css",
);

const IDENT = String.raw`(?:\\[0-9a-fA-F]{1,6} ?|\\.|[\w-]|\P{ASCII})+`;
const CLASS = new RegExp(String.raw`\.(${IDENT})`, "gu");
const LONE_CLASS = new RegExp(String.raw`^\.(${IDENT})$`, "u");
const ESCAPE = /\\([0-9a-fA-F]{1,6}) ?|\\(.)/gu;

function unescapeIdent(ident: string): string {
  return ident.replace(ESCAPE, (_, hex: string | undefined, char: string) =>
    hex ? String.fromCodePoint(Number.parseInt(hex, 16)) : char,
  );
}

/** The class names a selector mentions, unescaped. */
export function classesIn(selector: string): string[] {
  return [...selector.matchAll(CLASS)].map(([, ident]) => unescapeIdent(ident));
}

/** The candidates Tailwind emits a rule for under base.css's theme, variants and plugins. */
export async function tailwindUtilities(
  candidates: string[],
): Promise<Set<string>> {
  const dir = mkdtempSync(path.join(tmpdir(), "tw-candidates-"));
  try {
    const scanned = path.join(dir, "candidates.html");
    writeFileSync(scanned, candidates.join("\n"));
    const probe = [
      `@reference "${BASE_CSS}";`,
      `@source "${scanned}";`,
      "@tailwind utilities;",
    ].join("\n");
    const { root } = await postcss([
      tailwind({ base: dir, optimize: false }),
    ]).process(probe, { from: path.join(dir, "probe.css") });
    // Unoptimized, a utility is one top-level rule on its own class, its variants nested inside.
    const emitted = new Set<string>();
    for (const node of root.nodes) {
      const lone = node.type === "rule" && LONE_CLASS.exec(node.selector);
      if (lone) emitted.add(unescapeIdent(lone[1]));
    }
    return new Set(candidates.filter((candidate) => emitted.has(candidate)));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** What a loaded page rendered: every class on an element, and every style rule's selector. */
export interface RenderedStyles {
  classes: string[];
  selectors: string[];
}

/** The rendered classes that are Tailwind utilities and that no selector on the page mentions. */
export async function unstyledUtilities({
  classes,
  selectors,
}: RenderedStyles): Promise<string[]> {
  const styled = new Set(selectors.flatMap(classesIn));
  const unstyled = classes.filter((name) => !styled.has(name));
  const utilities = await tailwindUtilities(unstyled);
  return unstyled
    .filter((name) => utilities.has(name))
    .sort((a, b) => a.localeCompare(b));
}
