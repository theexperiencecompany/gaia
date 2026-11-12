/**
 * What HtmlArtifact markup may contain. It renders in a sandbox with GAIA's artifact
 * stylesheet and runtime (public/artifact/), so the model writes structure and classes only:
 * no script, no styling of its own, no network. Calculator formulas use the runtime's grammar.
 */

const FORBIDDEN: readonly [RegExp, string][] = [
  [/<script\b/i, "has a <script>; the runtime is the only script"],
  [/<style\b/i, "has a <style>; use the artifact classes"],
  [/\sstyle\s*=/i, "has a style= attribute; use the artifact classes"],
  [
    /\son[a-z]+\s*=/i,
    "has an on* event attribute; the runtime wires interaction",
  ],
  [
    /<(link|iframe|object|embed|base|meta|img|video|audio|source)\b/i,
    "loads content; it may not",
  ],
  [
    /(href|src|action|formaction|srcset)\s*=\s*["']?\s*(https?:|\/\/|javascript:|data:)/i,
    "points at a URL; it may not",
  ],
];

const FORMULA_ATTR = /data-formula\s*=\s*"([^"]*)"/gi;
const INPUT_NAME =
  /<(?:input|select)\b[^>]*\bname\s*=\s*"([a-z_][a-z0-9_]*)"/gi;
const FORMULA_TOKEN = /\d+(?:\.\d+)?|[a-z_][a-z0-9_]*|\*\*|[-+*/(),]|\s+/gy;
const FUNCTIONS = new Set([
  "min",
  "max",
  "round",
  "abs",
  "floor",
  "ceil",
  "pow",
  "sqrt",
]);

function formulaProblems(html: string): string[] {
  const names = new Set([...html.matchAll(INPUT_NAME)].map((m) => m[1]));
  const problems: string[] = [];
  for (const [, formula] of html.matchAll(FORMULA_ATTR)) {
    FORMULA_TOKEN.lastIndex = 0;
    const tokens = formula.match(FORMULA_TOKEN) ?? [];
    if (tokens.join("") !== formula) {
      problems.push(
        `formula "${formula}" uses characters outside + - * / ** ( ) ,`,
      );
      continue;
    }
    for (const token of tokens) {
      if (/^[a-z_]/.test(token) && !names.has(token) && !FUNCTIONS.has(token)) {
        problems.push(
          `formula "${formula}" names "${token}", which is no input`,
        );
      }
    }
  }
  return problems;
}

/** Everything wrong with one HtmlArtifact's markup. */
export function htmlProblems(html: string): string[] {
  return [
    ...FORBIDDEN.filter(([pattern]) => pattern.test(html)).map(
      ([, why]) => `html ${why}`,
    ),
    ...formulaProblems(html),
  ];
}
