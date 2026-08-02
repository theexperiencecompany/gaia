#!/usr/bin/env node
/**
 * evlog map for the TypeScript bots — observability score for bot entry points.
 *
 * The bots-side counterpart of tools/evlog_map (a Python port of evlog's `map`
 * command), targeting the bots' wide-event runtime
 * (libs/shared/ts/src/bots/utils/wide-events.ts). It statically answers: if a
 * bot misbehaves in production tonight, which handlers will be able to tell
 * you why?
 *
 * Entry points are the platform handler registrations in each bot adapter
 * (`client.on(...)`, `app.command(...)`, `bot.on(...)`, webhook routes) plus
 * the shared dispatch boundaries in libs/shared/ts/src/bots. Check ids,
 * weights, grade bands, sensitivity double-weighting, and the JSON schema all
 * mirror tools/evlog_map so tooling can merge the two maps (framework:
 * "bots-ts").
 *
 * Usage:
 *   node scripts/ci/evlog-map-bots.mjs                # terminal report
 *   node scripts/ci/evlog-map-bots.mjs --json         # evlog.map.json schema on stdout
 *   node scripts/ci/evlog-map-bots.mjs --min-score 90 # exit 1 below N
 *   node scripts/ci/evlog-map-bots.mjs --min-entries 15 # exit 1 below N entry points
 *   node scripts/ci/evlog-map-bots.mjs --files-from F # scan only listed files
 *
 * Suppressions (same contract as tools/evlog_map, `//` instead of `#`):
 *   // evlog-map-disable-next-line audit -- covered elsewhere
 *   // evlog-map-disable-line context -- same, on the flagged line
 *   // evlog-map-disable context, error-handling -- waive in this file
 * A suppressed check reports "n/a" (never "pass") so waived coverage stays
 * visible, and a directive naming an unknown check id is surfaced as a
 * warning. The `--` reason is mandatory: a directive without one waives
 * nothing and is reported, so no requirement is dropped anonymously.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

// Real TypeScript AST via the workspace's own compiler — no extra deps.
const require = createRequire(import.meta.url);
const ts = require("typescript");

const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);

// ---------------------------------------------------------------------------
// Adapter knowledge — where entry points live and what "wrapped" means
// ---------------------------------------------------------------------------

const BOT_SRC_DIRS = [
  "apps/bots/discord/src",
  "apps/bots/slack/src",
  "apps/bots/telegram/src",
  "apps/bots/whatsapp/src",
];

/** Canonical field schema, parsed live so a new field is recognized on landing. */
const SCHEMA_FILE = "libs/shared/ts/src/bots/utils/wide-events.ts";
const SCHEMA_INTERFACE = "BotWideEventFields";

/**
 * The shared dispatch boundaries wrapped in withWideEvent(). A platform
 * handler that routes through one of these runs inside a wide-event boundary
 * with canonical context attached (command/user_hash/... in base.ts, the full
 * chat context in streaming.ts) — this is the one piece of cross-file
 * knowledge the per-file scan encodes, mirroring how tools/evlog_map knows
 * about wide_task()/the HTTP middleware.
 */
const SHARED_ENTRY_POINTS = [
  {
    file: "libs/shared/ts/src/bots/adapter/base.ts",
    name: "dispatchCommand",
    kind: "dispatch",
  },
  {
    file: "libs/shared/ts/src/bots/utils/streaming.ts",
    name: "handleStreamingChat",
    kind: "dispatch",
  },
  {
    file: "libs/shared/ts/src/bots/consumer/outbound-consumer.ts",
    name: "handle",
    kind: "worker",
  },
];
const WRAPPED_DISPATCH_CALLS = new Set([
  "dispatchCommand",
  "handleStreamingChat",
]);

/** SDK registration methods → entry-point kind. */
const REGISTRATION_METHODS = new Map([
  ["command", "command"],
  ["event", "event"],
  ["message", "event"],
  ["on", "event"],
  ["once", "event"],
  ["post", "webhook"],
  ["get", "webhook"],
]);
/** Receivers (with a leading `this.` stripped) whose registrations count. */
const REGISTRATION_RECEIVERS = new Set(["client", "app", "bot", "botServer.app"]);

/** Connection-lifecycle events have nothing to instrument — the bots' /health. */
const LIFECYCLE_EVENTS = new Set(["ClientReady", "ready"]);

// ---------------------------------------------------------------------------
// Rules — evlog's ids and weights
// ---------------------------------------------------------------------------

const WEIGHTS = {
  "wide-event": 40,
  audit: 25,
  "structured-errors": 20,
  context: 15,
  "error-handling": 15,
};
const RULE_IDS = new Set(Object.keys(WEIGHTS));
const RULE_TITLES = {
  "wide-event": "logger",
  context: "context",
  "structured-errors": "errors",
  audit: "audit",
  "error-handling": "catch",
};
const GRADE_BANDS = [
  [90, "excellent"],
  [70, "good"],
  [50, "needs-work"],
];
const SENSITIVE_WEIGHT = 2;

/** Whole-word sensitivity terms (matched on camelCase-split identifiers). */
const HIGH_TERMS = new Map([
  ["auth", "auth"],
  ["token", "auth"],
  ["signature", "auth"],
  ["secret", "auth"],
  ["login", "auth"],
  ["password", "auth"],
  ["payment", "money"],
  ["billing", "money"],
  ["subscription", "money"],
  ["checkout", "money"],
]);
const GENERIC_ERRORS = new Set(["Error", "TypeError", "RangeError"]);
const LOGGING_CALL_NAMES = new Set(["error", "warn", "warning"]);

// ---------------------------------------------------------------------------
// File utilities
// ---------------------------------------------------------------------------

function listTsFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      out.push(...listTsFiles(full));
      continue;
    }
    if (!name.endsWith(".ts")) continue;
    if (name.endsWith(".d.ts") || name.endsWith(".test.ts")) continue;
    out.push(full);
  }
  return out.sort();
}

function parseFile(absPath) {
  const text = readFileSync(absPath, "utf8");
  const sf = ts.createSourceFile(absPath, text, ts.ScriptTarget.Latest, true);
  return { sf, text };
}

function lineOf(sf, node) {
  return sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
}

// ---------------------------------------------------------------------------
// Suppression directives
// ---------------------------------------------------------------------------

const DIRECTIVE =
  /\/\/\s*evlog-map-disable(?<scope>-next-line|-line)?(?<ids>[ \t]+[\w\-, \t]*?)?(?:--(?<reason>.*))?$/;
const ALL_CHECKS = "*";

function collectSuppressions(text) {
  const suppressions = [];
  text.split("\n").forEach((line, idx) => {
    const match = DIRECTIVE.exec(line);
    if (!match) return;
    const scope =
      match.groups.scope === "-next-line"
        ? "next-line"
        : match.groups.scope === "-line"
          ? "line"
          : "file";
    // Empty when the directive omitted its `--` reason — such a directive
    // suppresses nothing (see findSuppression) and is reported instead.
    const reason = (match.groups.reason ?? "").trim();
    const ids = (match.groups.ids ?? "")
      .split(/[\s,]+/)
      .map((part) => part.trim())
      .filter(Boolean);
    for (const checkId of ids.length > 0 ? ids : [ALL_CHECKS]) {
      suppressions.push({ checkId, declaredAt: idx + 1, reason, scope });
    }
  });
  return suppressions;
}

function findSuppression(suppressions, checkId, anchorLines) {
  for (const s of suppressions) {
    if (!s.reason) continue;
    if (s.checkId !== checkId && s.checkId !== ALL_CHECKS) continue;
    if (s.scope === "file") return s;
    const anchored = s.scope === "next-line" ? s.declaredAt + 1 : s.declaredAt;
    if (anchorLines.includes(anchored)) return s;
  }
  return null;
}

// ---------------------------------------------------------------------------
// AST facts
// ---------------------------------------------------------------------------

/** Index of same-file function-like declarations, keyed by name. */
function indexFunctions(sf) {
  const index = new Map();
  const visit = (node) => {
    if (ts.isFunctionDeclaration(node) && node.name && node.body) {
      index.set(node.name.text, node);
    }
    if (ts.isClassDeclaration(node)) {
      for (const member of node.members) {
        if (
          ts.isMethodDeclaration(member) &&
          member.body &&
          ts.isIdentifier(member.name)
        ) {
          index.set(member.name.text, member);
        }
        if (
          ts.isPropertyDeclaration(member) &&
          member.initializer &&
          (ts.isArrowFunction(member.initializer) ||
            ts.isFunctionExpression(member.initializer)) &&
          ts.isIdentifier(member.name)
        ) {
          index.set(member.name.text, member.initializer);
        }
      }
    }
    if (ts.isVariableStatement(node)) {
      for (const decl of node.declarationList.declarations) {
        if (
          decl.initializer &&
          (ts.isArrowFunction(decl.initializer) ||
            ts.isFunctionExpression(decl.initializer)) &&
          ts.isIdentifier(decl.name)
        ) {
          index.set(decl.name.text, decl.initializer);
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return index;
}

function objectLiteralKeys(node) {
  const keys = [];
  if (node && ts.isObjectLiteralExpression(node)) {
    for (const prop of node.properties) {
      if (
        (ts.isPropertyAssignment(prop) || ts.isShorthandPropertyAssignment(prop)) &&
        ts.isIdentifier(prop.name)
      ) {
        keys.push(prop.name.text);
      }
      if (ts.isPropertyAssignment(prop) && ts.isStringLiteral(prop.name)) {
        keys.push(prop.name.text);
      }
    }
  }
  return keys;
}

function subtreeContainsHandling(node) {
  let handled = false;
  const visit = (child) => {
    if (handled) return;
    if (ts.isThrowStatement(child) || ts.isReturnStatement(child)) {
      handled = true;
      return;
    }
    if (
      ts.isCallExpression(child) &&
      ts.isPropertyAccessExpression(child.expression) &&
      LOGGING_CALL_NAMES.has(child.expression.name.text)
    ) {
      handled = true;
      return;
    }
    ts.forEachChild(child, visit);
  };
  visit(node);
  return handled;
}

/** Facts about ONE function body (nested inline functions included). */
function analyzeBody(node, sf) {
  const facts = {
    calls: new Set(),
    hasBoundary: false,
    fieldKeys: new Set(),
    callsAudit: false,
    catches: [],
    throws: [],
    words: new Set(),
  };
  const addWords = (raw) => {
    for (const word of raw
      .replaceAll(/([a-z0-9])([A-Z])/g, "$1 $2")
      .split(/[^A-Za-z]+/)) {
      if (word) facts.words.add(word.toLowerCase());
    }
  };
  const visit = (child) => {
    if (ts.isIdentifier(child)) addWords(child.text);
    if (ts.isStringLiteral(child)) addWords(child.text);
    if (ts.isCallExpression(child)) {
      const callee = child.expression;
      if (ts.isIdentifier(callee)) {
        facts.calls.add(callee.text);
        if (callee.text === "withWideEvent") {
          facts.hasBoundary = true;
          for (const key of objectLiteralKeys(child.arguments[1])) {
            // platform/component are the boundary's structural envelope, not
            // business context — counting them would make `context` vacuous.
            if (key === "platform" || key === "component") continue;
            facts.fieldKeys.add(key);
          }
        }
      }
      if (ts.isPropertyAccessExpression(callee)) {
        const method = callee.name.text;
        const receiver = callee.expression.getText(sf);
        if (receiver === "this") facts.calls.add(method);
        if (receiver === "wideLog") {
          if (method === "set") {
            for (const key of objectLiteralKeys(child.arguments[0])) {
              facts.fieldKeys.add(key);
            }
          }
          if (method === "setNs") {
            const ns = child.arguments[0];
            if (ns && ts.isStringLiteral(ns)) facts.fieldKeys.add(ns.text);
          }
          if (method === "audit") facts.callsAudit = true;
        }
      }
    }
    if (ts.isCatchClause(child)) {
      facts.catches.push({
        line: lineOf(sf, child),
        isEmpty: child.block.statements.length === 0,
        handled: subtreeContainsHandling(child.block),
      });
    }
    if (ts.isThrowStatement(child) && child.expression) {
      if (ts.isNewExpression(child.expression)) {
        const ctor = child.expression.expression;
        const firstArg = child.expression.arguments?.[0];
        facts.throws.push({
          line: lineOf(sf, child),
          callee: ts.isIdentifier(ctor) ? ctor.text : null,
          messageIsEmpty:
            firstArg === undefined ||
            (ts.isStringLiteral(firstArg) && firstArg.text.trim() === ""),
          isRethrow: false,
        });
      } else {
        facts.throws.push({
          line: lineOf(sf, child),
          callee: null,
          messageIsEmpty: false,
          isRethrow: true,
        });
      }
    }
    ts.forEachChild(child, visit);
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
function reachableFacts(entryNode, fileIndex, sf) {
  const merged = {
    calls: new Set(),
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

// ---------------------------------------------------------------------------
// Entry-point discovery
// ---------------------------------------------------------------------------

function registrationLabel(arg, sf) {
  if (!arg) return "<none>";
  if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) {
    return arg.text;
  }
  if (ts.isPropertyAccessExpression(arg)) return arg.name.text;
  if (ts.isArrayLiteralExpression(arg)) {
    const first = arg.elements[0];
    const head =
      first && ts.isStringLiteral(first) ? first.text : "<dynamic>";
    return arg.elements.length > 1
      ? `${head}+${arg.elements.length - 1}`
      : head;
  }
  return "<dynamic>";
}

function handlerArgument(call) {
  for (let i = call.arguments.length - 1; i >= 0; i--) {
    const arg = call.arguments[i];
    if (ts.isArrowFunction(arg) || ts.isFunctionExpression(arg)) return arg;
  }
  return null;
}

/** Platform SDK registrations in one adapter file. */
function discoverRegistrations(sf) {
  const entries = [];
  const visit = (node) => {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression)
    ) {
      const method = node.expression.name.text;
      const kind = REGISTRATION_METHODS.get(method);
      const receiver = node.expression.expression
        .getText(sf)
        .replace(/^this\./, "");
      if (kind && REGISTRATION_RECEIVERS.has(receiver)) {
        const handler = handlerArgument(node);
        if (handler) {
          const label = registrationLabel(node.arguments[0], sf);
          entries.push({
            name: `${method}(${label})`,
            kind,
            path: label,
            methods: kind === "webhook" ? [method.toUpperCase()] : [],
            line: lineOf(sf, node),
            node: handler,
            exempt: LIFECYCLE_EVENTS.has(label),
          });
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return entries;
}

// ---------------------------------------------------------------------------
// Rules
// ---------------------------------------------------------------------------

function classifySensitivity(entry, ownFacts) {
  // Same locality as tools/evlog_map: the handler's own body plus its
  // registration label (the bots' "route path"), split into whole words.
  const words = new Set(ownFacts.words);
  for (const word of (entry.path ?? "")
    .replaceAll(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[^A-Za-z]+/)) {
    if (word) words.add(word.toLowerCase());
  }
  const reasons = [];
  let label = "";
  for (const [term, termLabel] of HIGH_TERMS) {
    if (words.has(term)) {
      reasons.push(`term "${term}" in handler`);
      if (!label || termLabel === "money") label = termLabel;
    }
  }
  return reasons.length > 0
    ? { level: "high", label, reasons }
    : { level: "low", label: "", reasons: [] };
}

function runRules(entry, ownFacts, reach, canonicalFields) {
  const checks = {};
  const viaDispatch = [...reach.calls].some((name) =>
    WRAPPED_DISPATCH_CALLS.has(name),
  );
  const wideEventOk = reach.hasBoundary || viaDispatch;

  checks["wide-event"] = wideEventOk
    ? { status: "pass", message: "", line: 0 }
    : {
        status: "fail",
        message:
          "handler never enters a wide-event boundary — wrap it in " +
          "withWideEvent() or route through dispatchCommand/handleStreamingChat",
        line: entry.line,
      };

  if (entry.kind !== "worker") {
    if (!wideEventOk) {
      checks.context = { status: "n/a", message: "", line: 0 };
    } else if (
      [...reach.fieldKeys].some((key) => canonicalFields.has(key))
    ) {
      checks.context = { status: "pass", message: "", line: 0 };
    } else if (viaDispatch) {
      // The wrapped shared dispatcher attaches canonical context
      // (command/user_hash/chat metrics) to the event this handler runs in.
      checks.context = { status: "pass", message: "", line: 0 };
    } else {
      checks.context = {
        status: "fail",
        message:
          "wideLog.set() uses no canonical BotWideEventFields key — fields " +
          "outside the schema are invisible to the shared dashboards",
        line: entry.line,
      };
    }
  }

  const realThrows = ownFacts.throws.filter((t) => !t.isRethrow);
  if (realThrows.length > 0) {
    const bare = realThrows.find(
      (t) => t.callee !== null && GENERIC_ERRORS.has(t.callee) && t.messageIsEmpty,
    );
    checks["structured-errors"] = bare
      ? {
          status: "fail",
          message: `throws bare new ${bare.callee}() without a message — the error explains nothing`,
          line: bare.line,
        }
      : { status: "pass", message: "", line: 0 };
  } else {
    checks["structured-errors"] = { status: "n/a", message: "", line: 0 };
  }

  if (entry.kind !== "worker") {
    if (entry.sensitivity.level !== "high") {
      checks.audit = { status: "n/a", message: "", line: 0 };
    } else if (reach.callsAudit) {
      checks.audit = { status: "pass", message: "", line: 0 };
    } else {
      checks.audit = {
        status: "fail",
        message: `${entry.sensitivity.label || "sensitive"} handler with no wideLog.audit(...) — no audit trail`,
        line: entry.line,
      };
    }
  }

  if (ownFacts.catches.length > 0) {
    let finding = null;
    for (const clause of ownFacts.catches) {
      if (clause.isEmpty) {
        finding = { message: "empty catch block swallows errors", line: clause.line };
        break;
      }
      if (!clause.handled) {
        finding = {
          message:
            "catch block neither records the error on the event " +
            "(wideLog.error/warning) nor re-throws or returns",
          line: clause.line,
        };
        break;
      }
    }
    checks["error-handling"] = finding
      ? { status: "fail", message: finding.message, line: finding.line }
      : { status: "pass", message: "", line: 0 };
  } else {
    checks["error-handling"] = { status: "n/a", message: "", line: 0 };
  }

  return checks;
}

function applySuppressions(entry, checks, suppressions, warnings, file) {
  for (const [checkId, result] of Object.entries(checks)) {
    if (result.status !== "fail") continue;
    const anchors = [result.line, entry.line].filter((line) => line > 0);
    const suppression = findSuppression(suppressions, checkId, anchors);
    if (suppression) {
      checks[checkId] = {
        status: "n/a",
        message: `disabled: ${suppression.reason}`,
        line: suppression.declaredAt,
        suppressed: true,
      };
    }
  }
  for (const s of suppressions) {
    if (s.checkId !== ALL_CHECKS && !RULE_IDS.has(s.checkId)) {
      const warning = `${file}:${s.declaredAt} disables '${s.checkId}', which is not a check evlog-map-bots runs`;
      if (!warnings.includes(warning)) warnings.push(warning);
    }
    if (!s.reason) {
      const warning = `${file}:${s.declaredAt} disables a check with no '-- <reason>' — rejected, the check still applies`;
      if (!warnings.includes(warning)) warnings.push(warning);
    }
  }
}

/** `[checks waived, files they sit in]` across the scan. */
function waivedChecks(entries) {
  let waived = 0;
  const files = new Set();
  for (const entry of entries) {
    for (const result of Object.values(entry.checks)) {
      if (!result.suppressed) continue;
      waived += 1;
      files.add(entry.file);
    }
  }
  return [waived, files.size];
}

// ---------------------------------------------------------------------------
// Scoring — evlog's math
// ---------------------------------------------------------------------------

function scoreEntry(checks) {
  let score = 100;
  for (const [checkId, result] of Object.entries(checks)) {
    if (result.status === "fail") score -= WEIGHTS[checkId] ?? 10;
  }
  return Math.max(0, score);
}

function scoreGlobal(entries) {
  const scored = entries.filter((entry) => !entry.exempt);
  if (scored.length === 0) return 100;
  let totalWeight = 0;
  let weightedSum = 0;
  for (const entry of scored) {
    const weight = entry.sensitivity.level === "high" ? SENSITIVE_WEIGHT : 1;
    totalWeight += weight;
    weightedSum += entry.score * weight;
  }
  return Math.round(weightedSum / totalWeight);
}

function gradeFromScore(score) {
  for (const [threshold, grade] of GRADE_BANDS) {
    if (score >= threshold) return grade;
  }
  return "at-risk";
}

function classifyObservability(entry) {
  if (entry.exempt) return "exempt";
  const wide = entry.checks["wide-event"];
  const context = entry.checks.context;
  const wideOk = wide !== undefined && wide.status === "pass";
  // A suppressed context check is waived, not covered — that entry is
  // "partial", so the headline coverage number cannot absorb waivers.
  const contextOk = context === undefined || context.status === "pass";
  if (wideOk && contextOk) return "instrumented";
  if (wideOk) return "partial";
  return "dark";
}

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------

function canonicalFieldNames() {
  const { sf } = parseFile(path.join(REPO_ROOT, SCHEMA_FILE));
  let fields = null;
  const visit = (node) => {
    if (ts.isInterfaceDeclaration(node) && node.name.text === SCHEMA_INTERFACE) {
      fields = new Set(
        node.members
          .filter((member) => ts.isPropertySignature(member) && member.name)
          .map((member) => member.name.getText(sf)),
      );
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  if (!fields || fields.size === 0) {
    throw new Error(`${SCHEMA_INTERFACE} not found in ${SCHEMA_FILE}`);
  }
  return fields;
}

function findSharedEntryNode(sf, name) {
  let found = null;
  const visit = (node) => {
    if (found) return;
    if (
      ts.isFunctionDeclaration(node) &&
      node.name?.text === name &&
      node.body
    ) {
      found = node;
      return;
    }
    if (
      ts.isMethodDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === name &&
      node.body
    ) {
      found = node;
      return;
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

function scan(fileFilter) {
  const entries = [];
  const warnings = [];
  const unparsable = [];
  const canonical = canonicalFieldNames();

  const scoreFile = (relFile, discover) => {
    if (fileFilter && !fileFilter.has(relFile)) return;
    const absPath = path.join(REPO_ROOT, relFile);
    const { sf, text } = parseFile(absPath);
    if (sf.parseDiagnostics?.length > 0) {
      unparsable.push(relFile);
      return;
    }
    const found = discover(sf);
    if (found.length === 0) return;
    const fileIndex = indexFunctions(sf);
    const suppressions = collectSuppressions(text);
    for (const entry of found) {
      const record = {
        file: relFile,
        line: entry.line,
        name: entry.name,
        kind: entry.kind,
        methods: entry.methods,
        path: entry.path,
        exempt: entry.exempt ?? false,
        checks: {},
        suggestions: {},
        score: 100,
        sensitivity: { level: "low", label: "", reasons: [] },
      };
      if (record.exempt) {
        entries.push(record);
        continue;
      }
      const ownFacts = analyzeBody(entry.node, sf);
      record.sensitivity = classifySensitivity(record, ownFacts);
      const reach = reachableFacts(entry.node, fileIndex, sf);
      record.checks = runRules(record, ownFacts, reach, canonical);
      applySuppressions(record, record.checks, suppressions, warnings, relFile);
      record.score = scoreEntry(record.checks);
      entries.push(record);
    }
  };

  for (const dir of BOT_SRC_DIRS) {
    for (const absFile of listTsFiles(path.join(REPO_ROOT, dir))) {
      scoreFile(path.relative(REPO_ROOT, absFile), discoverRegistrations);
    }
  }

  for (const shared of SHARED_ENTRY_POINTS) {
    scoreFile(shared.file, (sf) => {
      const node = findSharedEntryNode(sf, shared.name);
      if (!node) {
        warnings.push(
          `${shared.file}: shared entry point '${shared.name}' not found — dispatch registry moved?`,
        );
        return [];
      }
      return [
        {
          name: shared.name,
          kind: shared.kind,
          path: shared.name,
          methods: [],
          line: lineOf(sf, node),
          node,
          exempt: false,
        },
      ];
    });
  }

  const score = scoreGlobal(entries);
  return {
    entries,
    score,
    grade: gradeFromScore(score),
    unparsable,
    warnings,
  };
}

// ---------------------------------------------------------------------------
// Reports — same shapes as tools/evlog_map
// ---------------------------------------------------------------------------

const SENSITIVITY_BADGES = { money: "$", auth: "A", pii: "@" };

function routeLabel(entry) {
  const badge = SENSITIVITY_BADGES[entry.sensitivity.label] ?? " ";
  return `${badge} ${entry.kind} ${entry.path || entry.name}`;
}

function topIssue(entry) {
  for (const checkId of Object.keys(WEIGHTS)) {
    const result = entry.checks[checkId];
    if (result !== undefined && result.status === "fail") return result.message;
  }
  return "ok";
}

function renderTerminal(result) {
  const lines = [];
  const counts = { instrumented: 0, partial: 0, dark: 0, exempt: 0 };
  for (const entry of result.entries) counts[classifyObservability(entry)]++;
  const scored = result.entries.filter((entry) => !entry.exempt);

  lines.push(
    `evlog map (bots) — observability score: ${result.score}/100 (${result.grade})`,
  );
  lines.push(
    `${scored.length} entry points: ${counts.instrumented} instrumented, ` +
      `${counts.partial} partial, ${counts.dark} dark (${counts.exempt} exempt)`,
  );
  const [waived, waivedFiles] = waivedChecks(result.entries);
  if (waived > 0) {
    lines.push(`${waived} check(s) waived across ${waivedFiles} file(s)`);
  }
  if (result.unparsable.length > 0) {
    lines.push(`warning: ${result.unparsable.length} file(s) failed to parse`);
  }
  for (const warning of result.warnings) lines.push(`warning: ${warning}`);

  const failing = scored
    .filter((entry) => entry.score < 100)
    .sort(
      (a, b) =>
        Number(a.sensitivity.level !== "high") -
          Number(b.sensitivity.level !== "high") || a.score - b.score,
    );
  if (failing.length > 0) {
    lines.push("");
    lines.push("FIX FIRST");
    for (const entry of failing.slice(0, 3)) {
      lines.push(
        `  ${String(entry.score).padStart(3)}  ${routeLabel(entry)}  (${entry.file}:${entry.line})`,
      );
      lines.push(`       ${topIssue(entry)}`);
    }
    const rest = failing.slice(3);
    if (rest.length > 0) {
      lines.push("");
      lines.push(`THEN (${rest.length} more)`);
      const byIssue = new Map();
      for (const entry of rest) {
        const issue = topIssue(entry);
        byIssue.set(issue, (byIssue.get(issue) ?? 0) + 1);
      }
      for (const [issue, count] of [...byIssue].sort((a, b) => b[1] - a[1])) {
        lines.push(`  ${String(count).padStart(3)}x  ${issue}`);
      }
    }
  }

  const chips = (entry) =>
    Object.entries(entry.checks)
      .filter(([, result]) => result.status !== "n/a")
      .map(
        ([checkId, result]) =>
          `${RULE_TITLES[checkId] ?? checkId}:${result.status === "pass" ? "ok" : "x"}`,
      )
      .join("  ");
  lines.push("");
  for (const entry of [...scored].sort((a, b) => a.score - b.score)) {
    lines.push(
      `  ${String(entry.score).padStart(3)}  ${routeLabel(entry)}  ${chips(entry)}  (${entry.file}:${entry.line})`,
    );
  }
  return lines.join("\n");
}

/** The evlog.map.json contract — same keys as tools/evlog_map's to_json. */
function toJson(result) {
  return {
    score: result.score,
    grade: result.grade,
    framework: "bots-ts",
    // How much surface the scan actually found. A 100/100 over an empty map
    // is not a pass — consumers gate on this too (`--min-entries`).
    entryCount: result.entries.filter((entry) => !entry.exempt).length,
    entries: result.entries.map((entry) => ({
      file: entry.file,
      line: entry.line,
      name: entry.name,
      kind: entry.kind,
      methods: entry.methods,
      path: entry.path,
      score: entry.score,
      exempt: entry.exempt,
      observability: classifyObservability(entry),
      sensitivity: {
        level: entry.sensitivity.level,
        label: entry.sensitivity.label,
        reasons: entry.sensitivity.reasons,
      },
      checks: Object.fromEntries(
        Object.entries(entry.checks).map(([checkId, result_]) => [
          checkId,
          {
            status: result_.status,
            message: result_.message,
            line: result_.line,
          },
        ]),
      ),
      suggestions: entry.suggestions,
    })),
    unparsable: result.unparsable,
    warnings: result.warnings,
  };
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = {
    json: false,
    minScore: null,
    minEntries: null,
    filesFrom: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--json") args.json = true;
    else if (arg === "--min-score") args.minScore = Number(argv[++i]);
    else if (arg === "--min-entries") args.minEntries = Number(argv[++i]);
    else if (arg === "--files-from") args.filesFrom = argv[++i];
    else {
      console.error(`unknown argument: ${arg}`);
      process.exit(2);
    }
  }
  if (args.minScore !== null && Number.isNaN(args.minScore)) {
    console.error("--min-score requires a number");
    process.exit(2);
  }
  if (args.minEntries !== null && Number.isNaN(args.minEntries)) {
    console.error("--min-entries requires a number");
    process.exit(2);
  }
  return args;
}

function readFileFilter(source) {
  const raw =
    source === "-" ? readFileSync(0, "utf8") : readFileSync(source, "utf8");
  const files = raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => path.relative(REPO_ROOT, path.resolve(REPO_ROOT, line)));
  return new Set(files);
}

const args = parseArgs(process.argv.slice(2));
const fileFilter = args.filesFrom ? readFileFilter(args.filesFrom) : null;
const result = scan(fileFilter);

if (args.json) {
  console.log(JSON.stringify(toJson(result), null, 2));
} else {
  console.log(renderTerminal(result));
}

let failed = false;
if (args.minScore !== null && result.score < args.minScore) {
  console.error(
    `\nobservability score ${result.score} is below the required minimum ${args.minScore}`,
  );
  failed = true;
}
if (args.minEntries !== null) {
  // The score says nothing about what was never discovered: a refactor that
  // hides bot registrations reads as a perfect run, because an empty map
  // scores 100. Assert the surface is still there before trusting the number.
  const entryCount = result.entries.filter((entry) => !entry.exempt).length;
  if (entryCount < args.minEntries) {
    console.error(
      `\ndiscovery found ${entryCount} scored entry point(s), below --min-entries ` +
        `${args.minEntries} — the scan is not seeing the surface`,
    );
    failed = true;
  }
}
if (failed) process.exit(1);
