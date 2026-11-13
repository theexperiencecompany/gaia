// The HeroUI usage rules behind `checks.mjs heroui-style-overrides` and
// `checks.mjs heroui-usage`; never run directly. Both read one parse of each
// file and one binding table, so an aliased import, a namespace import or a
// class list held in a constant is seen the same way by every rule.
//
// heroui-style-overrides: a component imported from "@heroui/react" (or a GAIA
// wrapper around one) takes its colour, background, border colour, radius and
// padding from the token bridge and gaia layer in apps/web/src/app/styles, or
// from a variant function in components/shared — never from a className or
// style prop at the call site, whether written inline or held in a constant.
// Layout utilities stay free.
//
// heroui-usage: no v2 HeroUI API, every control rendered with its parts, and
// the GAIA wrapper wherever one replaces a bare HeroUI component.
//
// A Biome GritQL plugin cannot express these: GritQL cannot regex the content
// of a string literal, nor follow cn()/clsx() arguments, constants or an
// aliased import binding.
import { existsSync, readFileSync } from "node:fs";
import { posix } from "node:path";
import { parse } from "@babel/parser";
import traverse from "@babel/traverse";

export const HEROUI_STYLE_BASELINE = "heroui-style-overrides.txt";

export const HEROUI_SCANNED_ROOTS = [
  "apps/web/src/",
  "libs/shared/ts/src/",
  "apps/desktop/src/",
];

export const HEROUI_WRAPPER_DIR = "apps/web/src/components/shared/";

// The wrappers whose whole job is HeroUI's look; their own className is the design system.
export const HEROUI_SANCTIONED_FILES = new Set([
  `${HEROUI_WRAPPER_DIR}GaiaButton.tsx`,
  `${HEROUI_WRAPPER_DIR}LinkButton.tsx`,
]);

// A bare HeroUI component -> the GAIA wrapper that replaces it everywhere but its own file.
const REQUIRED_WRAPPERS = new Map([
  ["Button", "GaiaButton"],
  ["Select.Value", "GaiaSelectValue"],
  ["ListBox.Item", "GaiaListBoxItem"],
]);

// A collapsing part keeps its own padding and margin when closed, so its spacing goes on the content inside.
const COLLAPSING_PARTS = new Set(["Accordion.Panel", "Disclosure.Panel"]);
const BOX_SPACING = /^-?(p|m)[xytrblse]?-|^space-[xy]-/;

// v3 renders only the parts a Switch or Checkbox is given: self-closing, it renders an empty div.
const PART_CONTROLS = new Set(["Switch", "Checkbox"]);

const V2_ONLY_EXPORTS = new Set(["useDisclosure", "HeroUIProvider"]);
const V2_BUTTON_PROPS = new Set([
  "isLoading",
  "onClick",
  "startContent",
  "endContent",
  "radius",
  "color",
]);
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

const VARIANT_MODULE = /\/(\w+Variants|shape)$/;

// Skeleton has no shape of its own: its radius is the placeholder's layout.
const UNSTYLED_COMPONENTS = new Set(["Skeleton"]);

const HEROUI = "@heroui/react";
const HEROUI_PACKAGES = /^@heroui\/([\w-]+)/;
const V3_PACKAGES = new Set(["react", "styles"]);

const TEXT_NON_COLOR =
  /^text-(xs|sm|base|lg|[2-9]?xl|left|center|right|justify|start|end|wrap|nowrap|balance|pretty|ellipsis|clip|\[\d[^\]]*\]|\[length:[^\]]*\])$/;
const BORDER_NON_COLOR =
  /^border(-[xytrblse])?(-(\d+|\[\d[^\]]*\]|\[length:[^\]]*\]|solid|dashed|dotted|double|none|hidden|collapse|separate|spacing.*))?$/;
const PADDING = /^p[xytrblse]?-/;
const ROUNDED = /^rounded($|-)/;

const STYLE_KEY =
  /^(color|background.*|border|border(Top|Right|Bottom|Left|Inline|Block)(Start|End)?|border.*Color|border.*Radius|padding.*)$/;

const MODULE_EXTENSIONS = [".ts", ".tsx", "/index.ts", "/index.tsx"];

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

/** The repo path (no extension) an import names, for the alias and relative forms. */
function importTarget(file, source) {
  if (source.startsWith("@/") && file.startsWith("apps/web/src/")) {
    return `apps/web/src/${source.slice(2)}`;
  }
  if (source.startsWith(".")) return posix.join(posix.dirname(file), source);
  return null;
}

function moduleFile(target) {
  if (existsSync(target) && /\.tsx?$/.test(target)) return target;
  return MODULE_EXTENSIONS.map((ext) => target + ext).find((f) => existsSync(f)) ?? null;
}

function parseTsx(file, src) {
  return parse(src, {
    sourceType: "module",
    plugins: ["typescript", "jsx", "decorators"],
    errorRecovery: true,
    sourceFilename: file,
  });
}

/** One parsed module: its AST, const initialisers and import bindings, shared by every rule. */
class Module {
  static #cache = new Map();

  static load(file, src) {
    if (src === undefined && Module.#cache.has(file)) return Module.#cache.get(file);
    const module = new Module(file, src ?? readFileSync(file, "utf8"));
    if (src === undefined) Module.#cache.set(file, module);
    return module;
  }

  constructor(file, src) {
    this.file = file;
    this.ast = parseTsx(file, src);
    this.consts = new Map();
    this.imports = new Map();
    this.heroNamed = new Map();
    this.heroNamespaces = new Set();
    for (const stmt of this.ast.program.body) {
      if (stmt.type !== "ImportDeclaration") continue;
      for (const spec of stmt.specifiers) {
        const imported =
          spec.type === "ImportSpecifier" ? (spec.imported.name ?? spec.imported.value) : null;
        this.imports.set(spec.local.name, { source: stmt.source.value, imported });
        if (stmt.source.value !== HEROUI) continue;
        if (spec.type === "ImportNamespaceSpecifier") this.heroNamespaces.add(spec.local.name);
        if (imported && /^[A-Z]/.test(imported)) this.heroNamed.set(spec.local.name, imported);
      }
    }
    traverse.default(this.ast, {
      VariableDeclarator: (path) => {
        const { id, init } = path.node;
        if (path.parent.kind === "const" && id.type === "Identifier" && init) {
          this.consts.set(id.name, init);
        }
      },
    });
  }

  /** The module an imported binding comes from, and the name it has there; null for packages. */
  importedConst(name) {
    const binding = this.imports.get(name);
    if (!binding?.imported) return null;
    const target = importTarget(this.file, binding.source);
    const file = target && moduleFile(target);
    return file ? { module: Module.load(file), name: binding.imported } : null;
  }

  /** The expression a const name is bound to here or in the module it is imported from. */
  resolve(name, seen) {
    const key = `${this.file}#${name}`;
    if (seen.has(key)) return null;
    seen.add(key);
    if (this.consts.has(name)) return { module: this, node: this.consts.get(name) };
    const imported = this.importedConst(name);
    return imported ? imported.module.resolve(imported.name, seen) : null;
  }
}

/** Every string a className expression can evaluate to, read through constants, cn()/clsx(), ternaries, arrays and render functions. */
function classStrings(module, node, out, seen = new Set()) {
  if (!node) return out;
  const recurse = (child) => classStrings(module, child, out, seen);
  switch (node.type) {
    case "StringLiteral":
      out.push(node.value);
      break;
    case "TemplateLiteral":
      for (const quasi of node.quasis) out.push(quasi.value.cooked ?? "");
      node.expressions.forEach(recurse);
      break;
    case "JSXExpressionContainer":
    case "TSAsExpression":
    case "TSSatisfiesExpression":
    case "ParenthesizedExpression":
      recurse(node.expression);
      break;
    case "Identifier": {
      const bound = module.resolve(node.name, seen);
      if (bound && bound.node.type !== "ObjectExpression") {
        classStrings(bound.module, bound.node, out, seen);
      }
      break;
    }
    case "MemberExpression": {
      if (node.computed || node.object.type !== "Identifier") break;
      const bound = module.resolve(node.object.name, seen);
      if (bound?.node.type !== "ObjectExpression") break;
      const prop = bound.node.properties.find(
        (p) => p.type === "ObjectProperty" && (p.key.name ?? p.key.value) === node.property.name,
      );
      if (prop) classStrings(bound.module, prop.value, out, seen);
      break;
    }
    case "CallExpression":
      node.arguments.forEach(recurse);
      break;
    case "ConditionalExpression":
      recurse(node.consequent);
      recurse(node.alternate);
      break;
    case "LogicalExpression":
    case "BinaryExpression":
      recurse(node.left);
      recurse(node.right);
      break;
    case "ArrayExpression":
      node.elements.forEach(recurse);
      break;
    case "ObjectExpression":
      for (const prop of node.properties) {
        if (prop.type !== "ObjectProperty") continue;
        const key = prop.key.type === "StringLiteral" ? prop.key.value : prop.key.name;
        // A variant call's className option ({ className: "bg-x" }) is a class list; other keys are cn() conditions.
        if (key === "className" && !prop.computed) recurse(prop.value);
        else if (prop.key.type === "StringLiteral") out.push(prop.key.value);
        else if (prop.key.type === "Identifier" && !prop.computed) out.push(prop.key.name);
      }
      break;
    case "ArrowFunctionExpression":
      recurse(node.body);
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

function mentionsIdentifier(node, name) {
  if (!node || typeof node !== "object") return false;
  if (node.type === "Identifier" && node.name === name) return true;
  return Object.entries(node).some(
    ([key, child]) =>
      key !== "loc" &&
      (Array.isArray(child)
        ? child.some((c) => mentionsIdentifier(c, name))
        : child?.type && mentionsIdentifier(child, name)),
  );
}

function exportedComponentName(stmt) {
  if (stmt?.type !== "ExportNamedDeclaration") return null;
  const decl = stmt.declaration;
  const name =
    decl?.type === "FunctionDeclaration"
      ? decl.id?.name
      : decl?.type === "VariableDeclaration"
        ? decl.declarations[0]?.id?.name
        : null;
  return name && /^[A-Z]/.test(name) ? name : null;
}

/** The HeroUI (or wrapper) component a JSX tag names (`Modal.Body` -> "Modal.Body"), or null. */
function heroTag(name, module, wrappers) {
  const parts = [];
  let node = name;
  while (node.type === "JSXMemberExpression") {
    parts.unshift(node.property.name);
    node = node.object;
  }
  if (node.type !== "JSXIdentifier") return null;
  if (module.heroNamed.has(node.name)) {
    return [module.heroNamed.get(node.name), ...parts].join(".");
  }
  if (module.heroNamespaces.has(node.name) && parts.length > 0) return parts.join(".");
  const binding = module.imports.get(node.name);
  const target = binding?.imported && importTarget(module.file, binding.source);
  if (target && wrappers.get(target)?.has(binding.imported)) {
    return [binding.imported, ...parts].join(".");
  }
  return null;
}

/** The components a shared file exports that pass their own className to a HeroUI or variant-styled element. */
export function heroWrappersIn(file, src) {
  const module = Module.load(file, src);
  const variantFns = new Set(
    [...module.imports]
      .filter(([, b]) => VARIANT_MODULE.test(b.source))
      .map(([local]) => local),
  );
  const wrappers = new Set();
  traverse.default(module.ast, {
    JSXOpeningElement(nodePath) {
      const top = nodePath.findParent((p) => p.parentPath?.isProgram());
      const component = exportedComponentName(top?.node);
      if (!component) return;
      const attrs = nodePath.node.attributes;
      const classAttr = attrs.find((a) => a.type === "JSXAttribute" && a.name.name === "className");
      const classExpr = classAttr?.value?.expression;
      const styled =
        heroTag(nodePath.node.name, module, new Map()) !== null ||
        (classExpr?.type === "CallExpression" && variantFns.has(classExpr.callee.name));
      const forwards =
        mentionsIdentifier(classAttr?.value, "className") ||
        attrs.some((a) => a.type === "JSXSpreadAttribute");
      if (styled && forwards) wrappers.add(component);
    },
  });
  return wrappers;
}

/** Each override as `{ line, entry }`; entry is `<file>:<Component>:<token or style key>`, the baseline's key. */
export function heroStyleOverridesIn(file, src, wrappers) {
  const module = Module.load(file, src);
  const found = [];
  traverse.default(module.ast, {
    JSXOpeningElement(nodePath) {
      const tag = heroTag(nodePath.node.name, module, wrappers);
      if (!tag || UNSTYLED_COMPONENTS.has(tag.split(".")[0])) return;
      const line = nodePath.node.loc.start.line;
      for (const attr of nodePath.node.attributes) {
        if (attr.type !== "JSXAttribute") continue;
        if (attr.name.name === "className") {
          const tokens = classStrings(module, attr.value, [])
            .flatMap((s) => s.split(/\s+/))
            .filter(Boolean);
          for (const token of new Set(tokens.filter(isStylingToken))) {
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

function attrStringValues(module, attr) {
  if (!attr.value) return [];
  if (attr.value.type === "StringLiteral") return [attr.value.value];
  return classStrings(module, attr.value, []);
}

/** Each v2 leftover, missing control part or bare component a GAIA wrapper replaces, as `{ line, message }`. */
export function heroUsageIn(file, src) {
  const module = Module.load(file, src);
  const found = [];
  for (const stmt of module.ast.program.body) {
    if (stmt.type !== "ImportDeclaration") continue;
    const pkg = stmt.source.value.match(HEROUI_PACKAGES)?.[1];
    if (!pkg) continue;
    const line = stmt.loc.start.line;
    if (!V3_PACKAGES.has(pkg)) found.push({ line, message: `import from @heroui/${pkg}` });
    for (const spec of stmt.specifiers) {
      const imported = spec.type === "ImportSpecifier" ? (spec.imported.name ?? spec.imported.value) : null;
      if (V2_ONLY_EXPORTS.has(imported)) found.push({ line, message: `${imported} from @heroui` });
    }
  }
  const ownWrapper = (wrapper) => file === `${HEROUI_WRAPPER_DIR}${wrapper}.tsx`;
  let firstColumnLine = null;
  let hasRowHeader = false;
  traverse.default(module.ast, {
    JSXOpeningElement(nodePath) {
      const tag = heroTag(nodePath.node.name, module, new Map());
      if (!tag) return;
      const line = nodePath.node.loc.start.line;
      if (tag === "Table.Column") {
        firstColumnLine ??= line;
        hasRowHeader ||= nodePath.node.attributes.some(
          (a) => a.type === "JSXAttribute" && a.name.name === "isRowHeader",
        );
      }
      const wrapper = REQUIRED_WRAPPERS.get(tag);
      if (wrapper && !ownWrapper(wrapper)) {
        found.push({ line, message: `<${tag}>: use ${wrapper} (components/shared/${wrapper}.tsx)` });
      }
      if (PART_CONTROLS.has(tag) && nodePath.node.selfClosing) {
        found.push({ line, message: `<${tag} />: render its ${tag}.Control, or it draws nothing` });
      }
      for (const attr of nodePath.node.attributes) {
        if (attr.type !== "JSXAttribute") continue;
        const name = attr.name.name;
        if (COLLAPSING_PARTS.has(tag) && name === "className") {
          const spacing = classStrings(module, attr.value, [])
            .flatMap((c) => c.split(/\s+/))
            .filter((token) => BOX_SPACING.test(utilityOf(token)));
          if (spacing.length > 0) {
            found.push({
              line,
              message: `<${tag} className="${spacing.join(" ")}">: it keeps this when collapsed; put it on an element inside the panel`,
            });
          }
        }
        if ((tag === "Button" && V2_BUTTON_PROPS.has(name)) || V2_ANY_PROPS.has(name)) {
          found.push({ line, message: `<${tag} ${name}>: a v2 prop v3 does not read` });
        }
        if (name !== "variant") continue;
        for (const value of attrStringValues(module, attr).filter((v) => V2_VARIANTS.has(v))) {
          found.push({ line, message: `<${tag} variant="${value}">: a v2 variant v3 does not have` });
        }
      }
    },
  });
  if (firstColumnLine !== null && !hasRowHeader) {
    found.push({
      line: firstColumnLine,
      message: "<Table.Column>: mark one column isRowHeader, or the table throws at render",
    });
  }
  return found;
}
