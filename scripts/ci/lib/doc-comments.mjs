// The doc-comment content gate over the TypeScript/JS surface — the TS half
// of tools/lints/docstring_slop.py + comment_slop.py. Reached through
// `checks.mjs doc-comments`; never run directly.
//
//   DS1  a /** */ block longer than 6 content lines
//   DS5  a one-line /** */ block that only restates the declaration below it
//   DS6  an @param whose description only restates the parameter name
//   CM1  more than 3 consecutive own-line // comments
//   CM2  a banner (// ----, // ====) or // Step N inside a function body
//
// Comments come from @babel/parser's token stream, never a regex over the
// source: "apps/web/src/**/*.tsx" in a string is not a JSDoc block. The file
// header (scripts/ci/CLAUDE.md requires one) and pragmas (biome-ignore,
// eslint-, @ts-, prettier-, NOSONAR) never count; banners outside functions
// are allowed, since a registry or a sample catalogue is meant to be sectioned.
import { readFileSync } from "node:fs";
import { parse } from "@babel/parser";
import traverse from "@babel/traverse";

const BLOCK_MAX_LINES = 6;
const RUN_MAX = 3;

const PARAM = /^@param\s+(?:\{[^}]*\}\s*)?(\w+)\s*-?\s*(.*)$/;
const BANNER = /^\s*([-=#*~_]{3,}|step\s*\d+\b)/i;
const PRAGMA = /^\s*(biome-ignore|eslint|@ts-|prettier-|NOSONAR)/;
const FILLER = new Set(
  "the a an of to for and or in on is this that with from if by its it whether value values object id name current given".split(" "),
);

const words = (text) =>
  new Set(
    text
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((w) => w && !FILLER.has(w)),
  );
const subset = (a, b) => a.size > 0 && [...a].every((w) => b.has(w));

/** A leading comment is the file header unless it sits directly on the first declaration. */
function isHeader(comment, firstStatement) {
  if (!firstStatement) return true;
  if (comment.end > firstStatement.start) return false;
  return firstStatement.type === "ImportDeclaration" || firstStatement.loc.start.line > comment.loc.end.line + 1;
}

function checkBlock(comment, lines, report) {
  const line = comment.loc.start.line;
  const body = comment.value
    .slice(1)
    .split("\n")
    .map((l) => l.replace(/^\s*\*\s?/, "").trim())
    .filter(Boolean);
  if (body.length > BLOCK_MAX_LINES) {
    report(line, "DS1", `JSDoc block is ${body.length} lines (max ${BLOCK_MAX_LINES}) — say what, not why`);
  }
  const below = (lines[comment.loc.end.line] ?? "").trim();
  if (body.length === 1 && !body[0].startsWith("@") && subset(words(body[0]), words(below))) {
    report(line, "DS5", "JSDoc only restates the declaration below it — delete it");
  }
  for (const text of body) {
    const param = PARAM.exec(text);
    if (param && subset(words(param[2]), words(param[1]))) {
      report(line, "DS6", `@param ${param[1]} only restates its name — drop it`);
    }
  }
}

function functionSpans(ast) {
  const spans = [];
  traverse.default(ast, {
    Function(nodePath) {
      const { loc } = nodePath.node.body;
      if (loc) spans.push([loc.start.line, loc.end.line]);
    },
  });
  return spans;
}

export function checkDocComments(path) {
  const src = readFileSync(path, "utf8");
  const lines = src.split("\n");
  const ast = parse(src, {
    sourceType: "module",
    plugins: ["typescript", "jsx", "decorators"],
    errorRecovery: true,
    sourceFilename: path,
  });
  const spans = functionSpans(ast);
  const firstStatement = ast.program.body[0];
  const findings = [];
  const report = (line, code, message) => findings.push({ path, line, code, message });

  let run = 0;
  let prev = -2;
  for (const comment of ast.comments) {
    if (isHeader(comment, firstStatement) || PRAGMA.test(comment.value)) continue;
    if (comment.type === "CommentBlock") {
      if (comment.value.startsWith("*")) checkBlock(comment, lines, report);
      continue;
    }
    const line = comment.loc.start.line;
    if (!lines[line - 1].trimStart().startsWith("//")) continue; // trailing comment
    run = line === prev + 1 ? run + 1 : 1;
    prev = line;
    if (run === RUN_MAX + 1) {
      report(line - RUN_MAX, "CM1", `comment block longer than ${RUN_MAX} lines — keep the fact, drop the story`);
    }
    if (BANNER.test(comment.value) && spans.some(([start, end]) => start < line && line < end)) {
      report(line, "CM2", "banner or step comment inside a function — split it instead of sectioning it");
    }
  }
  return findings;
}
