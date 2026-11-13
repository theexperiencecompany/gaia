import { readFileSync } from "node:fs";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss, { AtRule, type Node, type Root, Rule } from "postcss";
import { describe, expect, it } from "vitest";

/**
 * The gaia layer sits above `components`, so a gaia rule beats every HeroUI rule
 * on the same property whatever its specificity: `.button { border-radius }`
 * squashed `.button-group .button { rounded-none }` and `.button { width: auto }`
 * squashed `.button--full-width`. A HeroUI rule that refines one gaia restyles
 * (a modifier, a state, a parent) must be restated in the gaia layer, or it is dead.
 */
const STYLES = path.resolve(__dirname, "../app/styles");

// HeroUI variants no GAIA component renders, so the gaia layer has nothing to restate for them.
const UNRENDERED = [
  "table-root--secondary",
  "select--secondary",
  "[data-tree-column]",
  "[data-drop-target",
  '.slider[data-orientation="vertical"]',
];

type Styled = { selector: string; decls: Map<string, Set<string>> };

const RADIUS =
  /^border(-(top|bottom)-(left|right)|-(start|end)-(start|end))?-radius$/;

/** The property groups a declaration sets, so `rounded-s-3xl`'s longhands meet `border-radius`. */
function families(prop: string): string[] {
  if (prop.startsWith("--")) return [];
  if (RADIUS.test(prop)) return ["border-radius"];
  for (const box of ["padding", "margin"]) {
    if (!prop.startsWith(box)) continue;
    if (prop === box) return [`${box}-inline`, `${box}-block`];
    if (/-(inline|left|right)(-start|-end)?$/.test(prop))
      return [`${box}-inline`];
    if (/-(block|top|bottom)(-start|-end)?$/.test(prop))
      return [`${box}-block`];
  }
  return [prop];
}

const normalise = (value: string) =>
  value
    .replace(/\s+/g, " ")
    .replace(/\b0px\b/g, "0")
    .trim();

/** A rule's enclosing rules and at-rules, innermost first. */
function ancestors(rule: Rule): Node[] {
  const out: Node[] = [];
  for (
    let node = rule.parent as Node | undefined;
    node;
    node = node.parent as Node | undefined
  )
    out.push(node);
  return out;
}

/** The rule a nested rule sits in, through any @media or @supports between them. */
function parentRule(rule: Rule): Rule | null {
  return (
    ancestors(rule).find((node): node is Rule => node instanceof Rule) ?? null
  );
}

/** A rule's selectors with native nesting resolved against its parents. */
function fullSelectors(rule: Rule): string[] {
  const parent = parentRule(rule);
  if (!parent) return rule.selectors;
  return fullSelectors(parent).flatMap((outer) =>
    rule.selectors.map((inner) =>
      inner.includes("&") ? inner.replaceAll("&", outer) : `${outer} ${inner}`,
    ),
  );
}

function layerOf(rule: Rule): string | null {
  const layer = ancestors(rule).find(
    (node): node is AtRule => node instanceof AtRule && node.name === "layer",
  );
  return layer?.params ?? null;
}

function styledIn(roots: Root[], layer: string): Styled[] {
  const out: Styled[] = [];
  for (const root of roots) {
    root.walkRules((rule) => {
      if (layerOf(rule) !== layer) return;
      const decls = new Map<string, Set<string>>();
      for (const node of rule.nodes) {
        if (node.type !== "decl") continue;
        for (const family of families(node.prop)) {
          if (!decls.has(family)) decls.set(family, new Set());
          decls.get(family)?.add(normalise(node.value));
        }
      }
      if (decls.size === 0) return;
      for (const selector of fullSelectors(rule)) out.push({ selector, decls });
    });
  }
  return out;
}

/** What a selector requires of its subject and of the whole chain: classes (`a--b` implies `a`), attributes, pseudo-classes. */
function requirements(selector: string) {
  const bare = selector.replace(/:(has|not|is|where)\([^()]*\)/g, "");
  const compounds = bare
    .replace(/\s*([>+~])\s*/g, " ")
    .split(" ")
    .filter(Boolean);
  const tokens = (part: string) =>
    new Set(
      [...part.matchAll(/\.([\w-]+)|(\[[^\]]+\])|(:[\w-]+)/g)].flatMap(
        ([, cls, attr, pseudo]) =>
          cls
            ? cls.includes("--")
              ? [cls, cls.split("--")[0]]
              : [cls]
            : [attr ?? pseudo],
      ),
    );
  const subject = tokens(compounds.at(-1) ?? "");
  const all = new Set(compounds.flatMap((c) => [...tokens(c)]));
  return { subject, all, pseudoElement: selector.includes("::") };
}

const covers = (outer: Set<string>, inner: Set<string>) =>
  [...inner].every((token) => outer.has(token));

/** True when `c` styles the element `g` styles in a narrower case than `g` itself. */
function refines(c: string, g: string): boolean {
  if (c === g) return false;
  const cr = requirements(c);
  const gr = requirements(g);
  if (cr.pseudoElement || gr.pseudoElement || gr.subject.size === 0)
    return false;
  if (!covers(cr.subject, gr.subject) || !covers(cr.all, gr.all)) return false;
  // `.slider .slider__track` is HeroUI's base rule for the track, nested in its own block.
  const blocks = new Set(
    [...cr.subject]
      .filter((t) => t.includes("__"))
      .map((t) => t.split("__")[0]),
  );
  return [...cr.all].some((t) => !gr.all.has(t) && !blocks.has(t));
}

/** HeroUI refinements of a gaia-styled element whose value the gaia layer overrides and never restates. */
function shadowedRefinements(gaia: Styled[], components: Styled[]): string[] {
  const found = new Set<string>();
  for (const c of components) {
    if (UNRENDERED.some((variant) => c.selector.includes(variant))) continue;
    const cr = requirements(c.selector);
    for (const g of gaia) {
      if (!refines(c.selector, g.selector)) continue;
      for (const [family, values] of c.decls) {
        const gaiaValues = g.decls.get(family);
        if (!gaiaValues || covers(gaiaValues, values)) continue;
        const restated = gaia.some((r) => {
          const rr = requirements(r.selector);
          return (
            r.decls.has(family) &&
            covers(rr.subject, cr.subject) &&
            covers(rr.all, cr.all)
          );
        });
        if (!restated)
          found.add(`${c.selector} { ${family} } under gaia ${g.selector}`);
      }
    }
  }
  return [...found].sort();
}

async function compile(sheet: string): Promise<Root> {
  const from = path.join(STYLES, `${sheet}.css`);
  const result = await postcss([tailwind()]).process(
    readFileSync(from, "utf8"),
    {
      from,
    },
  );
  return result.root;
}

describe("shadowedRefinements", () => {
  const check = (css: string) => {
    const root = postcss.parse(css);
    return shadowedRefinements(
      styledIn([root], "gaia"),
      styledIn([root], "components"),
    );
  };

  it("flags a HeroUI modifier the gaia layer squashes", () => {
    expect(
      check(
        "@layer components { .button { width: fit-content } .button--full-width { width: 100% } }" +
          "@layer gaia { .button { width: auto } }",
      ),
    ).toEqual([".button--full-width { width } under gaia .button"]);
  });

  it("flags a parent compound the gaia layer squashes", () => {
    expect(
      check(
        "@layer components { .button-group .button { border-start-start-radius: 0 } }" +
          "@layer gaia { .button { border-radius: 1rem } }",
      ),
    ).toEqual([".button-group .button { border-radius } under gaia .button"]);
  });

  it("passes a restated refinement, an agreeing value and a sibling state", () => {
    expect(
      check(
        "@layer components { .button-group .button { border-radius: 0 }" +
          " .textfield--full-width { width: 100% } .select[data-invalid] .select__trigger { color: red } }" +
          "@layer gaia { .button { border-radius: 1rem } .button-group .button { border-radius: 0 }" +
          " .textfield { width: 100% } .select[data-open] .select__trigger { color: blue } }",
      ),
    ).toEqual([]);
  });
});

describe("the gaia layer leaves HeroUI's refinements alive", () => {
  for (const area of ["app", "marketing"]) {
    it(`base.css + ${area}.css`, async () => {
      const roots = [await compile("base"), await compile(area)];
      expect(
        shadowedRefinements(
          styledIn(roots, "gaia"),
          styledIn(roots, "components"),
        ),
      ).toEqual([]);
    });
  }
});
