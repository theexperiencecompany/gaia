/**
 * HeroUI v2 -> v3 codemod, driven by decisions.json (generated from the real
 * v2/v3 type definitions in variants.mjs).
 *
 * Scope is deliberately conservative: it only does rewrites whose result is
 * unambiguous. Anything structural (compound components, overlay state, item
 * identity) is logged to manual-review.log instead of guessed at.
 *
 *   npx jscodeshift -t codemods/v3-props.cjs --parser=tsx --extensions=tsx apps/web/src
 */
const fs = require("node:fs");
const path = require("node:path");

const HERE = __dirname;
const LOG = path.join(process.cwd(), "tools/heroui-migration/manual-review.log");
const log = (line) => fs.appendFileSync(LOG, line + "\n");

let DECISIONS = { drop: {}, decisions: {} };
try {
  DECISIONS = JSON.parse(fs.readFileSync(path.join(HERE, "..", "decisions.json"), "utf8"));
} catch {
  /* run variants.mjs first for full coverage */
}

const { drop = {}, decisions = {} } = DECISIONS;

/** Documented Button table: colour folds INTO variant, so map the pair. */
const BUTTON_PAIRS = {
  "default|solid": "primary", "primary|solid": "primary", "secondary|solid": "secondary",
  "success|solid": "primary", "warning|solid": "primary", "danger|solid": "danger",
  "primary|bordered": "secondary", "primary|light": "tertiary", "primary|flat": "tertiary",
  "primary|faded": "secondary", "primary|ghost": "ghost", "danger|flat": "danger-soft",
  "danger|bordered": "danger-soft", "default|bordered": "secondary", "default|flat": "tertiary",
  "default|light": "tertiary", "default|ghost": "ghost", "secondary|flat": "tertiary",
  "secondary|light": "tertiary", "secondary|bordered": "secondary",
};
const V3_BUTTON_VARIANTS = new Set(["primary", "secondary", "tertiary", "outline", "ghost", "danger", "danger-soft"]);

const CHIP_VARIANT = { solid: "primary", bordered: "secondary", faded: "secondary", flat: "tertiary", light: "tertiary", shadow: "primary", dot: "primary" };
const V3_CHIP_VARIANTS = new Set(["primary", "secondary", "tertiary", "soft"]);
const CHIP_COLOR = { primary: "accent", secondary: "accent" };

/** Props that carry content/structure and can't be mechanically moved. */
const MANUAL_PROPS = ["startContent", "endContent", "classNames", "label", "description", "errorMessage", "labelPlacement", "isClearable", "content", "title"];
const RENAME = { isLoading: "isPending", onValueChange: "onChange" };

const attrsOf = (el) => (el.attributes || []).filter((a) => a.type === "JSXAttribute");
const getAttr = (el, n) => attrsOf(el).find((a) => a.name.name === n);
function attrValue(attr) {
  if (!attr || !attr.value) return null;
  if (attr.value.type === "StringLiteral") return attr.value.value;
  if (attr.value.type === "JSXExpressionContainer") return `{${attr.value.expression.type}}`;
  return null;
}
function setAttr(j, el, name, val) {
  const existing = getAttr(el, name);
  if (existing) existing.value = j.stringLiteral(val);
  else el.attributes.push(j.jsxAttribute(j.jsxIdentifier(name), j.stringLiteral(val)));
}
function dropAttr(el, name) {
  el.attributes = el.attributes.filter((a) => !(a.type === "JSXAttribute" && a.name.name === name));
}

module.exports = function transform(file, api) {
  const j = api.jscodeshift;
  const root = j(file.source);
  let changed = false;
  const rel = path.relative(process.cwd(), file.path);
  const line = (el) => el.loc?.start?.line ?? "?";

  const visit = (name, fn) => {
    root.findJSXElements(name).forEach((p) => {
      // p.node is the JSXElement; attributes live on openingElement
      if (fn(p.node.openingElement, p.node)) changed = true;
    });
  };

  const componentNames = new Set([
    ...Object.keys(drop),
    ...Object.keys(decisions),
    "Button", "Chip", "Divider", "Input", "Select", "Tabs", "Accordion", "Modal",
    "Card", "Switch", "Checkbox", "Avatar", "Popover", "Dropdown", "Slider", "Spinner",
    "Badge", "Link", "Kbd", "Skeleton", "Tooltip", "ScrollShadow", "Table", "Pagination",
  ]);

  for (const name of componentNames) {
    visit(name, (el) => {
      const lower = name.charAt(0).toLowerCase() + name.slice(1);
      let local = false;

      // 1. decisions: explicit value maps per (component, prop)
      for (const [prop, map] of Object.entries(decisions[name] || {})) {
        const v = attrValue(getAttr(el, prop));
        if (v && map[v] && map[v] !== v) {
          setAttr(j, el, prop, map[v]);
          local = true;
        }
      }

      // 2. Button: joint colour x variant
      if (name === "Button") {
        const color = attrValue(getAttr(el, "color"));
        const variant = attrValue(getAttr(el, "variant"));
        if (color !== null || variant !== null) {
          const mapped = BUTTON_PAIRS[`${color ?? "primary"}|${variant ?? "solid"}`];
          if (mapped) {
            setAttr(j, el, "variant", mapped);
            if (color !== null) dropAttr(el, "color");
            local = true;
          } else if (color !== null) {
            log(`${rel}:${line(el)}  Button: UNMAPPED color="${color}" variant="${variant ?? ""}" — decide manually`);
          }
        }
        if (getAttr(el, "size") && attrValue(getAttr(el, "size")) === "icon") {
          setAttr(j, el, "size", "md");
          el.attributes.push(j.jsxAttribute(j.jsxIdentifier("isIconOnly"), null));
          local = true;
        }
        if (getAttr(el, "isLoading")) {
          getAttr(el, "isLoading").name = j.jsxIdentifier("isPending");
          local = true;
        }
      }

      // 3. Chip vocabularies
      if (name === "Chip") {
        const variant = attrValue(getAttr(el, "variant"));
        if (variant && !V3_CHIP_VARIANTS.has(variant)) {
          setAttr(j, el, "variant", CHIP_VARIANT[variant] || "primary");
          local = true;
        }
        const color = attrValue(getAttr(el, "color"));
        if (color && CHIP_COLOR[color]) {
          setAttr(j, el, "color", CHIP_COLOR[color]);
          local = true;
        }
      }

      // 4. props the v3 component no longer accepts
      for (const prop of drop[lower] || []) {
        if (prop === "color" && name === "Chip") continue;
        if (getAttr(el, prop)) {
          dropAttr(el, prop);
          local = true;
        }
      }

      // 5. flag anything we refuse to guess at
      for (const prop of MANUAL_PROPS) {
        if (getAttr(el, prop) && !(drop[lower] || []).includes(prop)) {
          log(`${rel}:${line(el)}  ${name}: ${prop}= needs manual rewrite`);
        }
      }
      return local;
    });
  }

  // Divider -> Separator
  root.find(j.ImportDeclaration).forEach((p) => {
    if (p.node.source.value !== "@heroui/divider" && p.node.source.value !== "@heroui/react") return;
    for (const s of p.node.specifiers || []) {
      if (s.imported?.name === "Divider") {
        s.imported.name = "Separator";
        if (!s.local || s.local.name === "Divider") s.local = j.identifier("Separator");
        changed = true;
      }
    }
  });
  root.findJSXElements("Divider").forEach((p) => {
    p.node.openingElement.name = j.jsxIdentifier("Separator");
    if (p.node.closingElement) p.node.closingElement.name = j.jsxIdentifier("Separator");
    changed = true;
  });

  // generic renames
  root.find(j.JSXAttribute).forEach((p) => {
    const n = p.node.name.name;
    if (RENAME[n]) {
      p.node.name = j.jsxIdentifier(RENAME[n]);
      changed = true;
    }
  });

  return changed ? root.toSource({ quote: "double" }) : undefined;
};
