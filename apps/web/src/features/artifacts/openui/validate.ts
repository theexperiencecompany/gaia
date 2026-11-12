/**
 * Validate an artifact program against the library and its brief: arity and unknown
 * components (parser), every element's props against its zod schema, statement names from the
 * fixed list, every slot resolving, every typed number grounded in the brief, and exactly one
 * program. Node-safe; the server runs it through tools/artifact-validate.
 */
import { createParser } from "@openuidev/react-lang";
import type { z } from "zod";
import {
  buildIndex,
  extractProgram,
  type GroundingIndex,
  type GroundNode,
  resolveText,
  sourceNumbers,
  ungrounded,
} from "./grounding";
import { STATEMENT_NAMES } from "./kinds";
import { artifactSpecLibrary } from "./specLibrary";
import { ARTIFACT_ROOT } from "./specs";

export interface ValidationResult {
  ok: boolean;
  /** The program extracted from the reply: from the first root statement, statements only. */
  program: string;
  problems: string[];
  /** Each statement's `text` prop with its slots filled, for logs and tests. */
  resolved: Record<string, string>;
  statements: number;
  /** Rendered component count (every element in the tree, the root included). */
  components: number;
}

const MAX_ISSUES_PER_ELEMENT = 3;
const ROOT_LINE = /^root\s*=/gm;

const parser = createParser(artifactSpecLibrary.toJSONSchema(), ARTIFACT_ROOT);
const schemas: Record<string, z.ZodType> = Object.fromEntries(
  Object.entries(artifactSpecLibrary.components).map(([name, def]) => [
    name,
    def.props as unknown as z.ZodType,
  ]),
);

function elements(root: unknown): GroundNode[] {
  const out: GroundNode[] = [];
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      value.forEach(walk);
      return;
    }
    if (!value || typeof value !== "object") return;
    const node = value as GroundNode;
    if (node.type === "element") out.push(node);
    Object.values(node.props ?? {}).forEach(walk);
  };
  walk(root);
  return out;
}

function propProblems(nodes: GroundNode[]): string[] {
  return nodes.flatMap((node) => {
    const schema = schemas[node.typeName ?? ""];
    if (!schema) return [];
    const result = schema.safeParse(node.props);
    if (result.success) return [];
    const label = `${node.statementId ?? node.typeName} = ${node.typeName}(...)`;
    return result.error.issues
      .slice(0, MAX_ISSUES_PER_ELEMENT)
      .map(
        (issue) =>
          `${label}: ${issue.path.join(".") || "props"}: ${issue.message}`,
      );
  });
}

function namingProblems(nodes: GroundNode[]): string[] {
  return nodes.flatMap((node) => {
    const base = STATEMENT_NAMES[node.typeName ?? ""];
    if (
      !base ||
      !node.statementId ||
      new RegExp(`^${base}\\d+$`).test(node.statementId)
    ) {
      return [];
    }
    return [
      `${node.statementId} = ${node.typeName}(...): name it ${base}1, ${base}2, ... as the statement-name list says`,
    ];
  });
}

interface GroundingScope {
  id: string;
  index: GroundingIndex;
  source: Set<string>;
  problems: string[];
  resolved: Record<string, string>;
}

function checkText(scope: GroundingScope, value: string, path: string): void {
  const r = resolveText(value, scope.index);
  for (const slot of r.unknown) {
    scope.problems.push(
      `${scope.id}.${path}: {${slot}} is not a slot; slots are {statement.key} from the Grounded figures list`,
    );
  }
  for (const n of ungrounded(value, scope.source)) {
    scope.problems.push(
      `${scope.id}.${path}: ${n} is not in the source data; state it with a slot such as {funnel1.maxDrop}, {line1.avg~} for a rounded figure, or leave it out`,
    );
  }
  if (path === "text") scope.resolved[scope.id] = r.text;
}

/** Walk one statement's props; nested elements are their own statements and are skipped. */
function checkValue(scope: GroundingScope, value: unknown, path: string): void {
  if (typeof value === "string") {
    checkText(scope, value, path);
  } else if (typeof value === "number") {
    if (ungrounded(String(value), scope.source).length) {
      scope.problems.push(
        `${scope.id}.${path}: ${value} is not in the source data`,
      );
    }
  } else if (Array.isArray(value)) {
    value.forEach((item, i) => checkValue(scope, item, `${path}.${i}`));
  } else if (
    value &&
    typeof value === "object" &&
    (value as GroundNode).type !== "element"
  ) {
    for (const [key, item] of Object.entries(value))
      checkValue(scope, item, `${path}.${key}`);
  }
}

/** Slot and number grounding over every string and number a statement carries. */
function groundingProblems(
  root: unknown,
  brief: string,
): { problems: string[]; resolved: Record<string, string> } {
  const index = buildIndex(root);
  const source = sourceNumbers(brief);
  const problems: string[] = [];
  const resolved: Record<string, string> = {};
  for (const [id, node] of index) {
    const scope: GroundingScope = { id, index, source, problems, resolved };
    for (const [key, value] of Object.entries(node.props ?? {}))
      checkValue(scope, value, key);
  }
  return { problems, resolved };
}

function messageOf(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return JSON.stringify(error);
}

/** Extract the program from a model reply and run every check on it. */
export function validateArtifact(
  reply: string,
  brief: string,
): ValidationResult {
  const program = extractProgram(reply);
  const result = parser.parse(program);
  const nodes = elements(result.root);
  const roots = (program.match(ROOT_LINE) ?? []).length;
  const grounding = groundingProblems(result.root, brief);
  const problems = [
    ...namingProblems(nodes),
    ...grounding.problems,
    ...propProblems(nodes),
    ...(roots > 1
      ? [`the program is written ${roots} times; write it once`]
      : []),
    ...result.meta.errors.map(messageOf),
    ...result.meta.unresolved.map(
      (name) => `"${name}" is referenced but never defined`,
    ),
    ...(result.root ? [] : ["no root Artifact statement"]),
  ];
  return {
    ok: problems.length === 0,
    program,
    problems,
    resolved: grounding.resolved,
    statements: result.meta.statementCount,
    components: nodes.length,
  };
}
