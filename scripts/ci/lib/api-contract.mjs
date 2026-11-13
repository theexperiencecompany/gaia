/**
 * api-contract.mjs — the detector behind `checks.mjs api-schema-types` and
 * `checks.mjs api-client-imports`.
 *
 * Everything here is a pure function over a file's source text plus the
 * committed openapi.json: which declarations name a component schema, which
 * declarations sit in a directory that may only re-export generated names,
 * which declarations carry a schema's FIELDS under another name, and which
 * import statements reach the raw mobile request engine. The two subcommands
 * in checks.mjs own the file list, the baselines and the reporting; this
 * module owns what counts as a violation.
 *
 * It lives in lib/ for the reason the other lib/ modules do: inlining it would
 * put checks.mjs within a dozen lines of the 1200-line hard cap that
 * `checks.mjs file-sizes` itself enforces.
 */
import { existsSync, readFileSync } from "node:fs";

const GENERATED_DIR = "libs/shared/ts/src/api/generated/";
// Unlike the size gates, this one must read `.d.ts`: the generated file is
// already exempt by GENERATED_DIR, so every OTHER `.d.ts` is hand-written and
// a twin declared in one drifts exactly like a twin declared in a `.ts`.
const DTS_IGNORE_PATTERN = /\.d\.ts$/;

// The directories whose whole job is to name the API contract: a declaration
// there is a twin whatever it is called, so every interface/type must be a
// re-export or an alias of a generated name (.claude/rules/general.md).
const API_TYPE_DIRS = [
  /^apps\/web\/src\/features\/[^/]+\/api\//,
  /^apps\/web\/src\/types\/api\//,
  /^apps\/mobile\/src\/.*\/api\//,
  /^libs\/shared\/ts\/src\/(?:types|chat|bots\/api)\//,
];
const isApiTypeDir = (file) => API_TYPE_DIRS.some((rx) => rx.test(file));

// A hand-written twin usually renames the model rather than copying its name,
// so names alone miss it. Two declarations are the same model when their field
// SETS agree once `created_at`/`createdAt` are normalised to one spelling.
const TWIN_FIELD_RATIO = 0.8;
const TWIN_MIN_FIELDS = 3;
const normaliseField = (field) => field.replace(/_/g, "").toLowerCase();

const BASELINES = "scripts/ci/baselines/";

// A baseline lists the known violations this branch did not introduce. New ones
// fail; a line whose violation is gone is only reported as removable, so emptying
// a baseline never reds somebody else's PR.
function readBaseline(name) {
  const file = BASELINES + name;
  if (!existsSync(file)) return new Set();
  return new Set(
    readFileSync(file, "utf8")
      .split("\n")
      .map((line) => line.replace(/#.*$/, "").trim())
      .filter(Boolean),
  );
}

function reportBaseline(name, baseline, seen) {
  const stale = [...baseline].filter((entry) => !seen.has(entry));
  if (stale.length === 0) return;
  console.log(
    `\n⚠️  ${BASELINES}${name}: ${stale.length} line(s) no longer match anything — delete them:\n`,
  );
  for (const entry of stale) console.log(`  ${entry}`);
}

// `export interface TodoResponse {`, `type Workflow<T> =`, `declare interface X extends`.
// The trailing `{ < = extends` is what separates a declaration from the
// `type Foo,` line of a multi-line `import type` list.
const TYPE_DECLARATION =
  /^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type)\s+([A-Za-z0-9_]+)\s*(?:<|\{|=|extends\b)/gm;
// A bare alias of a generated type has no fields of its own, so it cannot drift;
// anything else bearing a schema name is a twin. The right-hand side may also be
// a local name bound by `import type { X as Y }`.
const GENERATED_IMPORT = /^import type \{([^}]*)\} from "[^"]*generated";/gm;
function generatedBindings(src, names) {
  const bound = new Set();
  for (const [, list] of src.matchAll(GENERATED_IMPORT)) {
    for (const entry of list.split(",")) {
      const [imported, local = imported] = entry.trim().split(/\s+as\s+/);
      if (names.has(imported)) bound.add(local);
    }
  }
  return bound;
}
const schemaAliasIn = (src, name, names) => {
  const alias = src.match(
    new RegExp(`^\\s*(?:export\\s+)?type\\s+${name}\\s*=\\s*([A-Za-z0-9_]+);`, "m"),
  );
  return alias !== null && (names.has(alias[1]) || generatedBindings(src, names).has(alias[1]));
};

function schemaComponents(openapiJson) {
  const doc = JSON.parse(readFileSync(openapiJson, "utf8"));
  return doc.components?.schemas ?? {};
}

function schemaFieldSets(schemas) {
  const sets = new Map();
  for (const [name, def] of Object.entries(schemas)) {
    const fields = Object.keys(def.properties ?? {});
    if (fields.length >= TWIN_MIN_FIELDS) {
      sets.set(name, new Set(fields.map(normaliseField)));
    }
  }
  return sets;
}

function schemaTwinsIn(src, names) {
  const found = [];
  for (const match of src.matchAll(TYPE_DECLARATION)) {
    const name = match[1];
    if (names.has(name) && !schemaAliasIn(src, name, names)) found.push(name);
  }
  return found;
}

// Every declaration in an API-type directory, with the aliases and re-exports
// filtered out. `export type { X } from "…"` never reaches here — the regex
// needs an identifier after `type`, and a re-export has a brace.
function handWrittenDeclsIn(src, names) {
  const found = [];
  for (const match of src.matchAll(TYPE_DECLARATION)) {
    const name = match[1];
    if (!schemaAliasIn(src, name, names)) found.push(name);
  }
  return found;
}

// `interface X {` / `interface X extends Y {` / `type X = {` — only the forms
// that open an object literal, since only those carry fields to compare.
const OBJECT_DECLARATION =
  /^\s*(?:export\s+)?(?:declare\s+)?(?:interface\s+([A-Za-z0-9_]+)[^{]*|type\s+([A-Za-z0-9_]+)(?:<[^=]*>)?\s*=\s*)\{/gm;
const FIELD_NAME = /^\s*(?:readonly\s+)?["']?([A-Za-z_$][A-Za-z0-9_$]*)["']?\s*\??\s*:/;

// The field names one brace level down from `open`. Nested objects, generics,
// tuples and call signatures all raise the depth, so only the declaration's own
// members are collected.
function topLevelFields(src, open) {
  const members = [];
  let depth = 0;
  let current = "";
  for (let i = open; i < src.length; i++) {
    const char = src[i];
    if (char === "{" || char === "(" || char === "[" || char === "<") {
      depth++;
      if (depth > 1) current += char;
    } else if (char === "}" || char === ")" || char === "]" || char === ">") {
      depth--;
      if (depth === 0) break;
      current += char;
    } else if (depth === 1 && (char === ";" || char === "," || char === "\n")) {
      members.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  const fields = [];
  for (const member of members) {
    const name = member.match(FIELD_NAME)?.[1];
    if (name) fields.push(normaliseField(name));
  }
  return fields;
}

function shapeTwinsIn(src, fieldSets) {
  const found = [];
  for (const match of src.matchAll(OBJECT_DECLARATION)) {
    const name = match[1] ?? match[2];
    const fields = new Set(topLevelFields(src, match.index + match[0].length - 1));
    if (fields.size < TWIN_MIN_FIELDS) continue;
    for (const [schema, schemaFields] of fieldSets) {
      if (schema === name) continue;
      let shared = 0;
      for (const field of fields) if (schemaFields.has(field)) shared++;
      const ratio = shared / Math.min(fields.size, schemaFields.size);
      if (ratio >= TWIN_FIELD_RATIO) {
        found.push({ name, schema, shared, of: Math.min(fields.size, schemaFields.size) });
        break;
      }
    }
  }
  return found;
}

// The web's API layer. `apiService` is the untyped request engine behind the
// path-typed client (`lib/api/typed.ts`); only this directory may touch it.
const WEB_API_LIB = "apps/web/src/lib/api/";
const WEB_SRC = "apps/web/src/";
const UNTYPED_CALL = /\bapiService\b/;

function untypedCallLines(file) {
  const lines = readFileSync(file, "utf8").split("\n");
  const hits = [];
  for (let index = 0; index < lines.length; index++) {
    if (UNTYPED_CALL.test(lines[index])) hits.push(index + 1);
  }
  return hits;
}

const isTestFile = (file) =>
  file.includes("/__tests__/") ||
  file.includes("/__mocks__/") ||
  /\.(?:test|spec)\.tsx?$/.test(file);

function isWebFeatureFile(file) {
  return file.startsWith(WEB_SRC) && !file.startsWith(WEB_API_LIB) && !isTestFile(file);
}

const MOBILE_SRC = "apps/mobile/src/";
const MOBILE_API_LIB = "apps/mobile/src/lib/";
const MOBILE_API_MODULE = "apps/mobile/src/lib/api";
const MOBILE_IMPORTS_BASELINE = "mobile-api-client-imports.txt";

// `import … from "x"` and `export … from "x"`, which is every way a module can
// reach another one's bindings. Matching the STATEMENT, not the identifier, is
// the point: a grep for `apiService` also hits a comment, a mock and a local.
const MODULE_SPECIFIER =
  /^\s*(?:import|export)\s[^;]*?from\s+["']([^"']+)["']/gm;

function resolveSpecifier(file, specifier) {
  if (specifier.startsWith("@/")) {
    return MOBILE_SRC + specifier.slice(2);
  }
  if (!specifier.startsWith(".")) return null;
  const parts = file.split("/").slice(0, -1);
  for (const part of specifier.split("/")) {
    if (part === "..") parts.pop();
    else if (part !== ".") parts.push(part);
  }
  return parts.join("/");
}

function rawClientImportLines(file, src) {
  const lines = [];
  for (const match of src.matchAll(MODULE_SPECIFIER)) {
    if (resolveSpecifier(file, match[1]) !== MOBILE_API_MODULE) continue;
    lines.push(src.slice(0, match.index).split("\n").length);
  }
  return lines;
}

export {
  BASELINES,
  DTS_IGNORE_PATTERN,
  GENERATED_DIR,
  MOBILE_API_LIB,
  MOBILE_IMPORTS_BASELINE,
  MOBILE_SRC,
  handWrittenDeclsIn,
  isApiTypeDir,
  isTestFile,
  isWebFeatureFile,
  rawClientImportLines,
  readBaseline,
  reportBaseline,
  schemaComponents,
  schemaFieldSets,
  schemaTwinsIn,
  shapeTwinsIn,
  untypedCallLines,
};
