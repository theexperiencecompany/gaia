/**
 * evlog map for the TypeScript bots — observability score for bot entry points.
 *
 * The implementation behind `node scripts/ci/checks.mjs evlog-map-bots`. It
 * lives here rather than inline in checks.mjs because the scanner alone is
 * ~1000 lines — inlining it would push checks.mjs past the 1200-line hard cap
 * that checks.mjs's own `file-sizes` subcommand enforces.
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
 *   node scripts/ci/checks.mjs evlog-map-bots                  # terminal report
 *   node scripts/ci/checks.mjs evlog-map-bots --json           # evlog.map.json schema on stdout
 *   node scripts/ci/checks.mjs evlog-map-bots --min-score 90   # exit 1 below N
 *   node scripts/ci/checks.mjs evlog-map-bots --min-entries 15 # exit 1 below N entry points
 *   node scripts/ci/checks.mjs evlog-map-bots --files-from F   # scan only listed files
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
import {
  analyzeBody,
  forEachChild,
  indexFunctions,
  parseSource,
  reachableFacts,
} from "./bots-facts.mjs";

// scripts/ci/lib/ -> repo root
const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
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
  "apps/bots/imessage/src",
  // The shared library is scanned for registrations too, not just for the
  // named boundaries below: the process signal/fault handlers, the AMQP
  // consumer and the shared HTTP routes all live here, and a scan that only
  // knew about per-bot adapters would call that whole surface "not an entry
  // point" and score a perfect 100 over it.
  "libs/shared/ts/src/bots",
];

/** Canonical field schema, parsed live so a new field is recognized on landing. */
const SCHEMA_FILE = "libs/shared/ts/src/bots/utils/wide-events.ts";
const SCHEMA_INTERFACE = "BotWideEventFields";

/**
 * Named shared boundaries: functions that are entry points in their own right
 * (a unit of work with several independent callers) rather than an SDK
 * registration a regex can find. Each is scored like any other entry, and the
 * set of them that PASSES the wide-event check becomes the cross-file
 * knowledge the per-file scan uses — a platform handler that calls one of these
 * is running inside a boundary with canonical context attached.
 *
 * That derivation is the point: nothing here is asserted to be instrumented.
 * Delete the boundary from `shutdown()` and it stops counting as one for the
 * signal handlers that call it, instead of silently vouching for them forever.
 */
const SHARED_ENTRY_POINTS = [
  {
    file: "libs/shared/ts/src/bots/adapter/base.ts",
    name: "dispatchCommand",
    kind: "dispatch",
  },
  {
    file: "libs/shared/ts/src/bots/adapter/base.ts",
    name: "boot",
    kind: "lifecycle",
  },
  {
    file: "libs/shared/ts/src/bots/adapter/base.ts",
    name: "shutdown",
    kind: "lifecycle",
  },
  {
    file: "libs/shared/ts/src/bots/adapter/base.ts",
    name: "resolveIncomingMedia",
    kind: "dispatch",
  },
  {
    file: "libs/shared/ts/src/bots/utils/streaming.ts",
    name: "handleStreamingChat",
    kind: "dispatch",
  },
];

/** SDK registration methods → entry-point kind. */
const REGISTRATION_METHODS = new Map([
  ["command", "command"],
  ["event", "event"],
  ["message", "event"],
  ["on", "event"],
  ["once", "event"],
  ["post", "webhook"],
  ["get", "webhook"],
  // Terminal error handlers: grammY's `bot.catch`, Bolt's `app.error`. Whatever
  // a middleware throws and nobody caught arrives here and nowhere else.
  ["catch", "error-handler"],
  ["error", "error-handler"],
  // AMQP: `channel.consume(queue, handler)` is the outbound worker's real
  // registration — the same shape as a platform handler, one layer down.
  ["consume", "worker"],
]);
/** Receivers (with a leading `this.` stripped) whose registrations count. */
const REGISTRATION_RECEIVERS = new Set([
  "client",
  "app",
  "bot",
  "botServer.app",
  "channel",
  "process",
]);

/**
 * `process.on(...)` names, and the kind each registers. These are the handlers
 * of last resort: without them Node prints a raw multi-line V8 stack and exits,
 * which is not JSON, not one line, and not attributable to any service — so a
 * crash is invisible to every dashboard AND breaks NDJSON framing for the
 * shipper. They are entry points exactly like a webhook is.
 */
const PROCESS_EVENT_KINDS = new Map([
  ["SIGINT", "signal"],
  ["SIGTERM", "signal"],
  ["SIGHUP", "signal"],
  ["unhandledRejection", "fault"],
  ["uncaughtException", "fault"],
  ["beforeExit", "signal"],
  ["exit", "signal"],
]);

/**
 * Routes with nothing to observe. `/health` answers a liveness probe with a
 * constant; a wide event per probe would be one event every few seconds per
 * bot, for a handler that cannot fail in an interesting way.
 */
const EXEMPT_ROUTES = new Set(["/health"]);

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
// Counterpart of `_PII_FIELDS` in tools/evlog_map/sensitivity.py.
const PII_TERMS = new Set(["email", "phone", "address", "ssn", "iban"]);

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
  return out.sort((a, b) => a.localeCompare(b));
}

function parseFile(absPath) {
  const text = readFileSync(absPath, "utf8");
  let program;
  try {
    program = parseSource(text);
  } catch {
    // Babel throws on syntax it cannot recover from; the ts compiler used to
    // return the file plus diagnostics. Same contract for the caller: the file
    // is unparsable, and the scan records it rather than failing the run.
    program = null;
  }
  return { sf: { program, sourceText: text }, text };
}

function lineOf(sf, node) {
  if (node.loc) return node.loc.start.line;
  // Babel gives us `loc` when the source has one; errorRecovery nodes may not.
  const upTo = (sf.sourceText ?? "").slice(0, node.start ?? 0);
  return upTo.split("\n").length;
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
  const anchors = new Set(anchorLines);
  for (const s of suppressions) {
    if (!s.reason) continue;
    if (s.checkId !== checkId && s.checkId !== ALL_CHECKS) continue;
    if (s.scope === "file") return s;
    const anchored = s.scope === "next-line" ? s.declaredAt + 1 : s.declaredAt;
    if (anchors.has(anchored)) return s;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Entry-point discovery
// ---------------------------------------------------------------------------

function registrationLabel(arg, sf) {
  if (!arg) return "<none>";
  if (arg.type === "StringLiteral") return arg.value;
  // No-substitution template literal — same as a plain string label.
  if (arg.type === "TemplateLiteral" && arg.expressions.length === 0) {
    return arg.quasis[0]?.value.raw ?? "<dynamic>";
  }
  if (arg.type === "MemberExpression" && arg.property.type === "Identifier") {
    return arg.property.name;
  }
  // A registration driven by a variable (`for (const signal of …) process.on(signal, …)`,
  // `bot.command(commandName, …)`) still has to be reported by something more
  // useful than "<dynamic>", or a loop is how an entry point stops being named.
  if (arg.type === "Identifier") return arg.name;
  if (arg.type === "ArrayExpression") {
    const first = arg.elements[0];
    const head = first && first.type === "StringLiteral" ? first.value : "<dynamic>";
    return arg.elements.length > 1
      ? `${head}+${arg.elements.length - 1}`
      : head;
  }
  return "<dynamic>";
}

function handlerArgument(call) {
  for (let i = call.arguments.length - 1; i >= 0; i--) {
    const arg = call.arguments[i];
    if (
      arg &&
      (arg.type === "ArrowFunctionExpression" || arg.type === "FunctionExpression")
    ) {
      return arg;
    }
  }
  return null;
}

/** Platform SDK, process and AMQP registrations in one file. */
function discoverRegistrations(sf) {
  const entries = [];
  const visit = (node) => {
    if (
      node.type === "CallExpression" &&
      node.callee.type === "MemberExpression"
    ) {
      const method = node.callee.property.type === "Identifier"
        ? node.callee.property.name
        : null;
      if (method === null) return;
      const receiver = sourceTextOf(sf, node.callee.object).replace(/^this\./, "");
      const label = registrationLabel(node.arguments[0], sf);
      // Everything registered on `process` is a process-level handler, never a
      // platform "event". The map names the two classes apart; a registration
      // the map cannot resolve — including one driven by a loop variable —
      // still counts, because a loop must not be a way to leave the map.
      const kind =
        receiver === "process"
          ? (PROCESS_EVENT_KINDS.get(label) ?? "signal")
          : REGISTRATION_METHODS.get(method);
      if (kind && REGISTRATION_RECEIVERS.has(receiver)) {
        const handler = handlerArgument(node);
        if (handler) {
          entries.push({
            name: `${method}(${label})`,
            kind,
            path: label,
            methods: kind === "webhook" ? [method.toUpperCase()] : [],
            line: lineOf(sf, node),
            node: handler,
            exempt: kind === "webhook" && EXEMPT_ROUTES.has(label),
          });
        }
      }
    }
    forEachChild(node, visit);
  };
  visit(sf.program);
  return entries;
}

function sourceTextOf(sf, node) {
  if (node.type === "Identifier") return node.name;
  return (sf.sourceText ?? "").slice(node.start ?? 0, node.end ?? 0);
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
  if (reasons.length > 0) {
    return { level: "high", label, reasons };
  }

  // PII tier — mirrors tools/evlog_map/sensitivity.py's `_PII_FIELDS`, so both
  // scanners report one ordered ladder ("low" | "medium" | "high") and their
  // maps stay comparable. Keep the two term lists in step.
  //
  // The Python side additionally requires a write call next to the PII field;
  // the bots have no equivalent database-write signal, so this tier is
  // term-only here. That makes it slightly broader, which is the right
  // direction for a tier that only raises attention.
  const piiTerms = [...words].filter((word) => PII_TERMS.has(word));
  if (piiTerms.length > 0) {
    return {
      level: "medium",
      label: "pii",
      reasons: piiTerms.map((term) => `pii: handler mentions "${term}"`),
    };
  }

  return { level: "low", label: "", reasons: [] };
}

function runRules(entry, ownFacts, reach, canonicalFields, wrappedSharedCalls) {
  const checks = {};
  const viaDispatch = [...reach.calls, ...reach.methodCalls].some((name) =>
    wrappedSharedCalls.has(name),
  );
  const wideEventOk = reach.hasBoundary || viaDispatch;

  checks["wide-event"] = wideEventOk
    ? { status: "pass", message: "", line: 0 }
    : {
        status: "fail",
        message:
          "handler never enters a wide-event boundary — wrap it in " +
          `withWideEvent() or route through one of: ${[...wrappedSharedCalls].sort((a, b) => a.localeCompare(b)).join(", ")}`,
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
            "catch block loses the caught error — record it on the event " +
            "(wideLog.error/warning, logger.error) or re-throw it (throw <caught>, " +
            "or 'throw new X(..., { cause: <caught> })' so the cause survives)",
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
  // Seeded from what is already in `warnings`: this runs once per entry and
  // the list accumulates across the whole scan, so the dedupe has to see
  // earlier entries' warnings too.
  const seen = new Set(warnings);
  const warnOnce = (warning) => {
    if (seen.has(warning)) return;
    seen.add(warning);
    warnings.push(warning);
  };
  for (const s of suppressions) {
    if (s.checkId !== ALL_CHECKS && !RULE_IDS.has(s.checkId)) {
      warnOnce(
        `${file}:${s.declaredAt} disables '${s.checkId}', which is not a check evlog-map-bots runs`,
      );
    }
    if (!s.reason) {
      warnOnce(
        `${file}:${s.declaredAt} disables a check with no '-- <reason>' — rejected, the check still applies`,
      );
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
  // Discovering nothing is NOT a perfect score — a blind scanner reports 100
  // over an empty map. Zero scores 0 so the --min-score gate catches discovery
  // collapse without a hand-maintained entry-count floor.
  if (scored.length === 0) return 0;
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
    if (
      node.type === "TSInterfaceDeclaration" &&
      node.id.type === "Identifier" &&
      node.id.name === SCHEMA_INTERFACE
    ) {
      fields = new Set(
        node.body.body.flatMap((member) => {
          if (member.type !== "TSPropertySignature" || !member.key) return [];
          return [
            member.key.type === "Identifier"
              ? member.key.name
              : (sf.sourceText ?? "").slice(
                  member.key.start ?? 0,
                  member.key.end ?? 0,
                ),
          ];
        }),
      );
    }
    forEachChild(node, visit);
  };
  visit(sf.program);
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
      node.type === "FunctionDeclaration" &&
      node.id?.type === "Identifier" &&
      node.id.name === name &&
      node.body
    ) {
      found = node;
      return;
    }
    if (
      node.type === "ClassMethod" &&
      node.key.type === "Identifier" &&
      node.key.name === name &&
      node.body
    ) {
      found = node;
      return;
    }
    forEachChild(node, visit);
  };
  visit(sf.program);
  return found;
}

/**
 * The subset of {@link SHARED_ENTRY_POINTS} that actually opens a wide-event
 * boundary today. Deliberately computed over the whole repo, ignoring
 * `--files-from`: a per-file scan still has to know that `dispatchCommand` is
 * instrumented, or every handler routing through it would read as dark.
 *
 * Suppressions are ignored on purpose — a waived boundary is a boundary the
 * scan agreed not to check, which is not the same as one that exists, and it
 * must not vouch for someone else.
 */
function verifiedSharedCalls(warnings) {
  const verified = new Set();
  for (const shared of SHARED_ENTRY_POINTS) {
    const { sf } = parseFile(path.join(REPO_ROOT, shared.file));
    const node = findSharedEntryNode(sf, shared.name);
    if (!node) {
      const warning = `${shared.file}: shared entry point '${shared.name}' not found — dispatch registry moved?`;
      if (!warnings.includes(warning)) warnings.push(warning);
      continue;
    }
    if (reachableFacts(node, indexFunctions(sf), sf).hasBoundary) {
      verified.add(shared.name);
    }
  }
  return verified;
}

function scan(fileFilter) {
  const entries = [];
  const warnings = [];
  const unparsable = [];
  const canonical = canonicalFieldNames();
  const wrappedSharedCalls = verifiedSharedCalls(warnings);

  const scoreFile = (relFile, discover) => {
    if (fileFilter && !fileFilter.has(relFile)) return;
    const absPath = path.join(REPO_ROOT, relFile);
    const { sf, text } = parseFile(absPath);
    if (sf.program == null) {
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
      record.checks = runRules(
        record,
        ownFacts,
        reach,
        canonical,
        wrappedSharedCalls,
      );
      applySuppressions(record, record.checks, suppressions, warnings, relFile);
      record.score = scoreEntry(record.checks);
      entries.push(record);
    }
  };

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

  for (const dir of BOT_SRC_DIRS) {
    for (const absFile of listTsFiles(path.join(REPO_ROOT, dir))) {
      scoreFile(path.relative(REPO_ROOT, absFile), discoverRegistrations);
    }
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
      .flatMap(([checkId, result]) =>
        result.status === "n/a"
          ? []
          : [`${RULE_TITLES[checkId] ?? checkId}:${result.status === "pass" ? "ok" : "x"}`],
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

export function runEvlogMapBots(argv) {
  const args = parseArgs(argv);
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
}
