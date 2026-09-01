/**
 * AST facts for the bots evlog map — same-file function indexing and the
 * control-flow analysis that decides whether an entry point records the
 * caught error on its wide event. Pure AST helpers (Babel parser/traverse),
 * no knowledge of where entry points live (that is evlog-map-bots.mjs's
 * job, dispatched as `checks.mjs evlog-map-bots`).
 *
 * The repo's TypeScript compiler is the native port (tsgo, TS 7), which ships
 * no JS compiler API, so the AST comes from @babel/parser + @babel/traverse —
 * both already workspace deps. The node-shape mappings used throughout:
 *   ts Identifier.text          -> Babel Identifier.name
 *   ts StringLiteral.text       -> Babel StringLiteral.value
 *   ts PropertyAccess.expression/name -> Babel MemberExpression.object/property
 *   ts NewExpression.expression -> Babel NewExpression.callee
 *   ts CallExpression.expression -> Babel CallExpression.callee
 *   ts ThrowStatement.expression -> Babel ThrowStatement.argument
 *   ts catch clause.variableDeclaration -> Babel CatchClause.param
 *   ts ClassDeclaration.members  -> Babel ClassDeclaration.body.body
 *   ts ObjectLiteral.properties  -> Babel ObjectExpression.properties
 */

import { parse } from "@babel/parser";
import traverse from "@babel/traverse";

const LOGGING_CALL_NAMES = new Set(["error", "warn", "warning"]);
/** `wideLog` methods that put the caught error on the wide event. */
const WIDE_EVENT_RECORDERS = new Set(["set", "setNs", "audit"]);

// ---------------------------------------------------------------------------
// Parsing + generic walking
// ---------------------------------------------------------------------------

/** Parse a TS file the way the scanner needs it: error-tolerant, no emit. */
export function parseSource(text) {
  return parse(text, {
    sourceType: "module",
    plugins: ["typescript"],
    errorRecovery: true,
  });
}

/** Walk every node of a Babel AST (analogue of the ts compiler's forEachChild). */
export function forEachChild(node, visit) {
  for (const key of Object.keys(node)) {
    if (key === "type" || key === "start" || key === "end" || key === "loc" || key === "leadingComments" || key === "trailingComments" || key === "innerComments" || key === "extra" || key === "comments") {
      continue;
    }
    const value = node[key];
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item && typeof item.type === "string") visit(item);
      }
    } else if (value && typeof value.type === "string") {
      visit(value);
    }
  }
}

// ---------------------------------------------------------------------------
// AST facts
// ---------------------------------------------------------------------------

/** Index of same-file function-like declarations, keyed by name. */
export function indexFunctions(sf) {
  const index = new Map();
  const visit = (node) => {
    if (node.type === "FunctionDeclaration" && node.id && node.body) {
      index.set(node.id.name, node);
    }
    if (node.type === "ClassDeclaration" && node.body) {
      for (const member of node.body.body) {
        if (
          member.type === "ClassMethod" &&
          member.body &&
          member.key &&
          member.key.type === "Identifier"
        ) {
          index.set(member.key.name, member);
        }
        if (
          (member.type === "ClassProperty" || member.type === "ClassPrivateProperty") &&
          member.value &&
          (member.value.type === "ArrowFunctionExpression" ||
            member.value.type === "FunctionExpression") &&
          member.key &&
          member.key.type === "Identifier"
        ) {
          index.set(member.key.name, member.value);
        }
      }
    }
    if (node.type === "VariableDeclaration") {
      for (const decl of node.declarations) {
        if (
          decl.init &&
          (decl.init.type === "ArrowFunctionExpression" ||
            decl.init.type === "FunctionExpression") &&
          decl.id &&
          decl.id.type === "Identifier"
        ) {
          index.set(decl.id.name, decl.init);
        }
      }
    }
    forEachChild(node, visit);
  };
  visit(sf.program);
  return index;
}

function objectLiteralKeys(node) {
  const keys = [];
  if (node && node.type === "ObjectExpression") {
    for (const prop of node.properties) {
      if (prop.type === "ObjectProperty") {
        if (prop.key.type === "Identifier") keys.push(prop.key.name);
        if (prop.key.type === "StringLiteral") keys.push(prop.key.value);
      }
    }
  }
  return keys;
}

/** The caught binding of `catch (err)`, or null for `catch {}` / a pattern. */
function catchBinding(clause) {
  const param = clause.param;
  if (param && param.type === "Identifier") return param.name;
  return null;
}

/**
 * Whether `throw <expr>` keeps the caught error alive.
 *
 * The JS analogue of tools/evlog_map's `_preserves_caught_error`. Python's
 * `raise X from e` sets `__cause__`; JS's equivalent is the `cause` option —
 * `throw new X(msg, { cause: err })` — which is what the log sink follows to
 * report what actually failed. `throw err` is the rethrow shape (JS has no
 * bare `throw`, so nothing maps to Python's bare `raise`). A `new X("...")`
 * that drops the caught error destroys its type and message before anything
 * reads them, exactly like `raise X(...)` with no `from`.
 */
function throwPreservesCause(expr, binding) {
  if (binding === null) return false;
  if (expr.type === "Identifier") return expr.name === binding;
  if (expr.type !== "NewExpression") return false;
  // Scan every argument rather than assuming Error's 2nd-arg options bag:
  // custom error classes put their options in other positions.
  for (const arg of expr.arguments ?? []) {
    if (!arg || arg.type !== "ObjectExpression") continue;
    for (const prop of arg.properties) {
      if (
        prop.type === "ObjectProperty" &&
        prop.key.type === "Identifier" &&
        prop.key.name === "cause"
      ) {
        if (prop.shorthand && binding === "cause") return true;
        if (
          prop.value.type === "Identifier" &&
          prop.value.name === binding
        ) {
          return true;
        }
      }
    }
  }
  return false;
}

/**
 * Whether a `catch` clause's body keeps the error it caught — it records it,
 * or re-throws it with the cause intact. A `return` records nothing, so on its
 * own it is a swallow: the handler reports failure with zero telemetry about
 * what failed. Mirrors `_scope_contains_error_handling` in tools/evlog_map.
 */
function catchClauseHandled(clause, sourceText) {
  const binding = catchBinding(clause);
  let handled = false;
  const visit = (child) => {
    if (handled) return;
    if (child.type === "ThrowStatement" && child.argument) {
      if (throwPreservesCause(child.argument, binding)) {
        handled = true;
        return;
      }
    }
    if (child.type === "CallExpression" && child.callee.type === "MemberExpression") {
      const method = child.callee.property.type === "Identifier"
        ? child.callee.property.name
        : null;
      if (method === null) return;
      const receiver = child.callee.object.type === "Identifier"
        ? child.callee.object.name
        : sourceSlice(sourceText, child.callee.object);
      if (
        LOGGING_CALL_NAMES.has(method) ||
        (receiver === "wideLog" && WIDE_EVENT_RECORDERS.has(method))
      ) {
        handled = true;
        return;
      }
    }
    forEachChild(child, visit);
  };
  visit(clause.body);
  return handled;
}

/** The source text of a node — Babel keeps offsets, not source slices. */
function sourceSlice(sourceText, node) {
  return sourceText.slice(node.start ?? 0, node.end ?? 0);
}

/** 1-based line of a node in the file's source text. */
function lineOf(sourceText, node) {
  if (node.loc) return node.loc.start.line;
  const upTo = (sourceText ?? "").slice(0, node.start ?? 0);
  return upTo.split("\n").length;
}

/** Facts about ONE function body (nested inline functions included). */
export function analyzeBody(node, sf) {
  const facts = {
    calls: new Set(),
    // Method names of calls on a non-`this` receiver (`adapter.shutdown()`).
    // Kept apart from `calls` because `calls` also drives same-file traversal,
    // where a bare method name would resolve against unrelated functions.
    methodCalls: new Set(),
    hasBoundary: false,
    fieldKeys: new Set(),
    callsAudit: false,
    catches: [],
    throws: [],
    words: new Set(),
  };
  const sourceText = sf.sourceText;
  const addWords = (raw) => {
    for (const word of raw
      .replaceAll(/([a-z0-9])([A-Z])/g, "$1 $2")
      .split(/[^A-Za-z]+/)) {
      if (word) facts.words.add(word.toLowerCase());
    }
  };
  const visit = (child) => {
    if (child.type === "Identifier") addWords(child.name);
    if (child.type === "StringLiteral") addWords(child.value);
    if (child.type === "CallExpression") {
      const callee = child.callee;
      if (callee.type === "Identifier") {
        facts.calls.add(callee.name);
        if (callee.name === "withWideEvent") {
          facts.hasBoundary = true;
          for (const key of objectLiteralKeys(child.arguments[1])) {
            // platform/component are the boundary's structural envelope, not
            // business context — counting them would make `context` vacuous.
            if (key === "platform" || key === "component") continue;
            facts.fieldKeys.add(key);
          }
        }
      }
      if (callee.type === "MemberExpression") {
        const method = callee.property.type === "Identifier"
          ? callee.property.name
          : null;
        if (method === null) return;
        const receiver = callee.object.type === "Identifier"
          ? callee.object.name
          : sourceSlice(sourceText, callee.object);
        if (receiver === "this") facts.calls.add(method);
        else facts.methodCalls.add(method);
        if (receiver === "wideLog") {
          if (method === "set") {
            for (const key of objectLiteralKeys(child.arguments[0])) {
              facts.fieldKeys.add(key);
            }
          }
          if (method === "setNs") {
            const ns = child.arguments[0];
            if (ns && ns.type === "StringLiteral") facts.fieldKeys.add(ns.value);
          }
          if (method === "audit") facts.callsAudit = true;
        }
      }
    }
    if (child.type === "CatchClause") {
      facts.catches.push({
        line: lineOf(sourceText, child),
        isEmpty: child.body.body.length === 0,
        handled: catchClauseHandled(child, sourceText),
      });
    }
    if (child.type === "ThrowStatement" && child.argument) {
      if (child.argument.type === "NewExpression") {
        const ctor = child.argument.callee;
        const firstArg = child.argument.arguments?.[0];
        facts.throws.push({
          line: lineOf(sourceText, child),
          callee: ctor.type === "Identifier" ? ctor.name : null,
          messageIsEmpty:
            firstArg === undefined ||
            (firstArg.type === "StringLiteral" && firstArg.value.trim() === ""),
          isRethrow: false,
        });
      } else {
        facts.throws.push({
          line: lineOf(sourceText, child),
          callee: null,
          messageIsEmpty: false,
          isRethrow: true,
        });
      }
    }
    forEachChild(child, visit);
  };
  visit(node);
  return facts;
}

/**
 * Facts for an entry point plus every same-file function it (transitively)
 * calls. The handler unit for the wide-event/context/audit checks — adapter
 * callbacks routinely delegate to same-file private methods, and stopping at
 * the callback body would score the delegation, not the handler.
 */
export function reachableFacts(entryNode, fileIndex, sf) {
  const merged = {
    calls: new Set(),
    methodCalls: new Set(),
    hasBoundary: false,
    fieldKeys: new Set(),
    callsAudit: false,
  };
  const seen = new Set();
  const queue = [entryNode];
  while (queue.length > 0) {
    const node = queue.pop();
    const facts = analyzeBody(node, sf);
    merged.hasBoundary ||= facts.hasBoundary;
    merged.callsAudit ||= facts.callsAudit;
    for (const call of facts.calls) merged.calls.add(call);
    for (const call of facts.methodCalls) merged.methodCalls.add(call);
    for (const key of facts.fieldKeys) merged.fieldKeys.add(key);
    for (const call of facts.calls) {
      if (seen.has(call)) continue;
      seen.add(call);
      const target = fileIndex.get(call);
      if (target) queue.push(target);
    }
  }
  return merged;
}
