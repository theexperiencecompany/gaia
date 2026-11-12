// The HeroUI styling boundary behind `checks.mjs heroui-style-overrides`;
// never run directly. A component imported from "@heroui/react" takes its
// colour, background, border colour, radius and padding from the token bridge
// and the gaia layer in apps/web/src/app/styles/base.css, or from the shared
// variants (buttonVariants.ts, shape.ts, the parity class constants) — never
// from a className or style prop at the call site. Layout utilities stay free.
//
// A Biome GritQL plugin cannot express this: GritQL cannot regex the content of
// a string literal, so it cannot tell `rounded-lg` from `w-full` inside a
// className, nor follow cn()/clsx() arguments or an aliased import binding.
import { parse } from "@babel/parser";
import traverse from "@babel/traverse";

export const HEROUI_STYLE_BASELINE = "heroui-style-overrides.txt";

export const HEROUI_SCANNED_ROOTS = [
  "apps/web/src/",
  "libs/shared/ts/src/",
  "apps/desktop/src/",
];

// The files that own HeroUI's look; every override belongs in one of them.
export const HEROUI_SANCTIONED_FILES = new Set([
  "apps/web/src/components/shared/buttonVariants.ts",
  "apps/web/src/components/shared/shape.ts",
  "apps/web/src/components/shared/GaiaButton.tsx",
  "apps/web/src/components/shared/LinkButton.tsx",
  "apps/web/src/lib/heroui/accordionParity.ts",
  "apps/web/src/lib/heroui/tabsParity.ts",
]);

// Skeleton has no shape of its own: its radius is the placeholder's layout.
const UNSTYLED_COMPONENTS = new Set(["Skeleton"]);

const HEROUI = "@heroui/react";

const TEXT_NON_COLOR =
  /^text-(xs|sm|base|lg|[2-9]?xl|left|center|right|justify|start|end|wrap|nowrap|balance|pretty|ellipsis|clip|\[\d[^\]]*\]|\[length:[^\]]*\])$/;
const BORDER_NON_COLOR =
  /^border(-[xytrblse])?(-(\d+|\[\d[^\]]*\]|\[length:[^\]]*\]|solid|dashed|dotted|double|none|hidden|collapse|separate|spacing.*))?$/;
const PADDING = /^p[xytrblse]?-/;
const ROUNDED = /^rounded($|-)/;

const STYLE_KEY =
  /^(color|background.*|border|border(Top|Right|Bottom|Left|Inline|Block)(Start|End)?|border.*Color|border.*Radius|padding.*)$/;

/** The utility a class token names once its variants (hover:, md:, data-[x]:) and !/- are stripped. */
function utilityOf(token) {
  let depth = 0;
  let cut = 0;
  for (let i = 0; i < token.length; i++) {
    const c = token[i];
    if (c === "[" || c === "(") depth++;
    else if (c === "]" || c === ")") depth--;
    else if (c === ":" && depth === 0) cut = i + 1;
  }
  return token.slice(cut).replace(/^!/, "").replace(/!$/, "").replace(/^-/, "");
}

export function isStylingToken(token) {
  const utility = utilityOf(token);
  if (utility.startsWith("bg-")) return true;
  if (ROUNDED.test(utility) || PADDING.test(utility)) return true;
  if (utility.startsWith("text-")) return !TEXT_NON_COLOR.test(utility);
  if (utility.startsWith("border-")) return !BORDER_NON_COLOR.test(utility);
  return false;
}

/** Every string a className expression can evaluate to, read through cn()/clsx(), ternaries, arrays and render functions. */
function classStrings(node, out) {
  if (!node) return out;
  switch (node.type) {
    case "StringLiteral":
      out.push(node.value);
      break;
    case "TemplateLiteral":
      for (const quasi of node.quasis) out.push(quasi.value.cooked ?? "");
      for (const expr of node.expressions) classStrings(expr, out);
      break;
    case "JSXExpressionContainer":
    case "TSAsExpression":
    case "TSSatisfiesExpression":
    case "ParenthesizedExpression":
      classStrings(node.expression, out);
      break;
    case "CallExpression":
      for (const arg of node.arguments) classStrings(arg, out);
      break;
    case "ConditionalExpression":
      classStrings(node.consequent, out);
      classStrings(node.alternate, out);
      break;
    case "LogicalExpression":
    case "BinaryExpression":
      classStrings(node.left, out);
      classStrings(node.right, out);
      break;
    case "ArrayExpression":
      for (const el of node.elements) classStrings(el, out);
      break;
    case "ObjectExpression":
      for (const prop of node.properties) {
        if (prop.type !== "ObjectProperty") continue;
        if (prop.key.type === "StringLiteral") out.push(prop.key.value);
        else if (prop.key.type === "Identifier" && !prop.computed) out.push(prop.key.name);
      }
      break;
    case "ArrowFunctionExpression":
      classStrings(node.body, out);
      break;
    default:
      break;
  }
  return out;
}

function styleKeys(node) {
  const expr = node?.type === "JSXExpressionContainer" ? node.expression : node;
  if (expr?.type !== "ObjectExpression") return [];
  return expr.properties
    .filter((p) => p.type === "ObjectProperty" && !p.computed)
    .map((p) => (p.key.type === "Identifier" ? p.key.name : p.key.value))
    .filter((key) => typeof key === "string" && STYLE_KEY.test(key));
}

/** Local name -> HeroUI component name, for every capitalised binding imported from "@heroui/react". */
function heroBindings(ast) {
  const named = new Map();
  const namespaces = new Set();
  for (const stmt of ast.program.body) {
    if (stmt.type !== "ImportDeclaration" || stmt.source.value !== HEROUI) continue;
    for (const spec of stmt.specifiers) {
      if (spec.type === "ImportNamespaceSpecifier") namespaces.add(spec.local.name);
      if (spec.type !== "ImportSpecifier") continue;
      const imported = spec.imported.name ?? spec.imported.value;
      if (/^[A-Z]/.test(imported)) named.set(spec.local.name, imported);
    }
  }
  return { named, namespaces };
}

/** The HeroUI component a JSX tag names (`Modal.Body` -> "Modal.Body"), or null. */
function heroTag(name, { named, namespaces }) {
  const parts = [];
  let node = name;
  while (node.type === "JSXMemberExpression") {
    parts.unshift(node.property.name);
    node = node.object;
  }
  if (node.type !== "JSXIdentifier") return null;
  if (named.has(node.name)) return [named.get(node.name), ...parts].join(".");
  if (namespaces.has(node.name) && parts.length > 0) return parts.join(".");
  return null;
}

/** Each override as `{ line, entry }`; entry is `<file>:<Component>:<token or style key>`, the baseline's key. */
export function heroStyleOverridesIn(file, src) {
  const ast = parse(src, {
    sourceType: "module",
    plugins: ["typescript", "jsx", "decorators"],
    errorRecovery: true,
    sourceFilename: file,
  });
  const bindings = heroBindings(ast);
  if (bindings.named.size === 0 && bindings.namespaces.size === 0) return [];
  const found = [];
  traverse.default(ast, {
    JSXOpeningElement(nodePath) {
      const tag = heroTag(nodePath.node.name, bindings);
      if (!tag || UNSTYLED_COMPONENTS.has(tag.split(".")[0])) return;
      const line = nodePath.node.loc.start.line;
      for (const attr of nodePath.node.attributes) {
        if (attr.type !== "JSXAttribute") continue;
        if (attr.name.name === "className") {
          const tokens = classStrings(attr.value, []).flatMap((s) => s.split(/\s+/)).filter(Boolean);
          for (const token of tokens.filter(isStylingToken)) {
            found.push({ line, entry: `${file}:${tag}:${token}` });
          }
        } else if (attr.name.name === "style") {
          for (const key of styleKeys(attr.value)) {
            found.push({ line, entry: `${file}:${tag}:style.${key}` });
          }
        }
      }
    },
  });
  return found;
}
