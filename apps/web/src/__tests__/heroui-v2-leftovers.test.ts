import { globSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * v3 dropped these v2 APIs without a type error in every case: a prop v3 does
 * not read is spread onto the DOM, and a v2 variant name falls through to the
 * default look. Each one renders, just not the way the author meant.
 */
const REPO_ROOT = path.resolve(__dirname, "../../../..");
const SCANNED_ROOTS = [
  "apps/web/src",
  "libs/shared/ts/src",
  "apps/desktop/src",
];

const V2_PACKAGE = /from\s+["']@heroui\/(?!react["'/]|styles["'/])([\w-]+)/g;
const HEROUI_NAMED_IMPORT =
  /import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*["']@heroui\/[\w-]+["']/g;
const V2_ONLY_EXPORTS = new Set(["useDisclosure", "HeroUIProvider"]);
const V2_BUTTON_PROPS = new Set([
  "isLoading",
  "onClick",
  "startContent",
  "endContent",
  "radius",
  "color",
]);
// Props no v3 component reads.
const V2_ANY_PROPS = new Set(["classNames", "labelPlacement"]);
const V2_VARIANTS = new Set([
  "flat",
  "light",
  "bordered",
  "faded",
  "solid",
  "shadow",
  "underlined",
  "splitted",
]);

/** Local binding -> exported name, for each capitalised import from "@heroui/react". */
function heroBindings(source: string): Map<string, string> {
  const bindings = new Map<string, string>();
  const imports = source.matchAll(
    /import\s*\{([^}]*)\}\s*from\s*["']@heroui\/react["']/g,
  );
  for (const [, list] of imports) {
    for (const spec of list.split(",")) {
      const [imported, local = imported] = spec
        .replace(/^\s*type\s+/, "")
        .split(/\s+as\s+/)
        .map((s) => s.trim());
      if (/^[A-Z]/.test(imported)) bindings.set(local, imported);
    }
  }
  return bindings;
}

/** Index just past the quote or template literal starting at `start`. */
function skipString(source: string, start: number): number {
  const quote = source[start];
  let i = start + 1;
  while (i < source.length && source[i] !== quote)
    i += source[i] === "\\" ? 2 : 1;
  return i + 1;
}

/** The attribute text of a JSX opening tag, with every `{...}` and string body blanked. */
function openingTag(
  source: string,
  from: number,
): { flat: string; raw: string } {
  let depth = 0;
  let flat = "";
  let i = from;
  while (i < source.length) {
    const char = source[i];
    if (char === '"' || char === "'" || char === "`") {
      const end = skipString(source, i);
      flat += depth === 0 ? `${char}${" ".repeat(end - i - 2)}${char}` : "";
      i = end;
      continue;
    }
    if (char === "{") depth++;
    else if (char === "}") depth--;
    else if (char === ">" && depth === 0) break;
    if (depth === 0 && char !== "}") flat += char;
    i++;
  }
  return { flat, raw: source.slice(from, i) };
}

function attributeNames(flat: string): string[] {
  return [...flat.matchAll(/(?:^|\s)([A-Za-z][\w-]*)(?=\s*=|\s|\/|$)/g)].map(
    ([, name]) => name,
  );
}

function variantValues(raw: string): string[] {
  const at = raw.search(/(?:^|\s)variant\s*=/);
  if (at < 0) return [];
  const value = raw.slice(raw.indexOf("=", at) + 1).trimStart();
  const expr = value.startsWith("{")
    ? value.slice(0, openingTag(value, 0).raw.length)
    : value;
  const literal = value.startsWith("{")
    ? expr
    : (value.match(/^(["'])[^"']*\1/)?.[0] ?? "");
  return [...literal.matchAll(/["'`]([\w-]+)["'`]/g)].map(([, v]) => v);
}

function v2Leftovers(source: string): string[] {
  const found: string[] = [];
  const lineOf = (index: number) => source.slice(0, index).split("\n").length;
  for (const match of source.matchAll(V2_PACKAGE)) {
    found.push(`line ${lineOf(match.index)}: import from @heroui/${match[1]}`);
  }
  for (const match of source.matchAll(HEROUI_NAMED_IMPORT)) {
    for (const name of match[1]
      .split(",")
      .map((s) => s.trim().split(/\s+as\s+/)[0])) {
      if (V2_ONLY_EXPORTS.has(name))
        found.push(`line ${lineOf(match.index)}: ${name} from @heroui`);
    }
  }
  const bindings = heroBindings(source);
  if (bindings.size === 0) return found;
  for (const match of source.matchAll(/<([A-Z]\w*)((?:\.\w+)*)/g)) {
    const component = bindings.get(match[1]);
    if (!component) continue;
    const tag = `${component}${match[2]}`;
    const { flat, raw } = openingTag(source, match.index + match[0].length);
    const line = lineOf(match.index);
    for (const name of attributeNames(flat)) {
      const v2ButtonProp = tag === "Button" && V2_BUTTON_PROPS.has(name);
      if (v2ButtonProp || V2_ANY_PROPS.has(name))
        found.push(`line ${line}: <${tag} ${name}>`);
    }
    for (const value of variantValues(raw).filter((v) => V2_VARIANTS.has(v))) {
      found.push(`line ${line}: <${tag} variant="${value}">`);
    }
  }
  return found;
}

const heroFile = (jsx: string) =>
  `import { Button, Chip, Input, Tabs } from "@heroui/react";\nexport const A = () => (${jsx});\n`;

describe("v2Leftovers", () => {
  const red: [string, string][] = [
    ['import { Button } from "@heroui/button";', "import from @heroui/button"],
    ['import { cn } from "@heroui/theme";', "import from @heroui/theme"],
    [
      'import { useDisclosure } from "@heroui/react";',
      "useDisclosure from @heroui",
    ],
    [
      'import { HeroUIProvider } from "@heroui/system";',
      "HeroUIProvider from @heroui",
    ],
    [heroFile("<Button isLoading>x</Button>"), "<Button isLoading>"],
    [heroFile("<Button onClick={() => go()}>x</Button>"), "<Button onClick>"],
    [
      heroFile("<Button startContent={<Icon />}>x</Button>"),
      "<Button startContent>",
    ],
    [
      heroFile("<Button endContent={<Icon />}>x</Button>"),
      "<Button endContent>",
    ],
    [
      heroFile('<Button classNames={{ base: "x" }}>x</Button>'),
      "<Button classNames>",
    ],
    [heroFile('<Button radius="full">x</Button>'), "<Button radius>"],
    [heroFile('<Button color="primary">x</Button>'), "<Button color>"],
    [heroFile('<Input labelPlacement="outside" />'), "<Input labelPlacement>"],
    ...[...V2_VARIANTS].map((v): [string, string] => [
      heroFile(`<Chip variant="${v}">x</Chip>`),
      `<Chip variant="${v}">`,
    ]),
    [
      heroFile('<Tabs.List variant={open ? "underlined" : "primary"} />'),
      'variant="underlined"',
    ],
  ];
  for (const [source, expected] of red) {
    it(`flags ${expected}`, () => {
      expect(v2Leftovers(source).join("\n")).toContain(expected);
    });
  }

  it("flags an aliased HeroUI Button", () => {
    const source =
      'import { Button as B } from "@heroui/react";\nconst a = <B isLoading />;';
    expect(v2Leftovers(source)).toEqual(["line 2: <Button isLoading>"]);
  });

  it("passes v3 usage and components that are not HeroUI's", () => {
    const source = [
      'import { Button, Chip } from "@heroui/react";',
      'import { buttonVariants } from "@heroui/styles";',
      'import { GaiaButton } from "@/components/shared/GaiaButton";',
      "export const A = () => (",
      '  <Button variant="primary" isPending onPress={go} className="[&>svg]:w-4">x</Button>',
      '  <Chip variant="soft" color="accent">x</Chip>',
      '  <GaiaButton onClick={go} variant="flat" isLoading>x</GaiaButton>',
      '  <button onClick={go} color="red" type="button" />',
      ");",
    ].join("\n");
    expect(v2Leftovers(source)).toEqual([]);
  });
});

describe("no v2-era HeroUI usage is left in the tree", () => {
  const files = SCANNED_ROOTS.flatMap((root) =>
    globSync(`${root}/**/*.{ts,tsx}`, { cwd: REPO_ROOT }),
  ).filter((file) => !/\.(test|spec)\.tsx?$|\/__tests__\//.test(file));

  it("scans the source roots", () => {
    expect(files.length).toBeGreaterThan(500);
  });

  it("has no v2 HeroUI imports, props or variants", () => {
    const offenders = files.flatMap((file) =>
      v2Leftovers(readFileSync(path.join(REPO_ROOT, file), "utf8")).map(
        (where) => `${file}: ${where}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});
