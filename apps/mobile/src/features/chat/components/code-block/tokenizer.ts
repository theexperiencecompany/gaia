import type { TokenType } from "./syntax-theme";

export interface Token {
  type: TokenType | "plain";
  value: string;
}

// Language-specific keyword sets
const KEYWORDS_JS = new Set([
  "abstract",
  "arguments",
  "async",
  "await",
  "break",
  "case",
  "catch",
  "class",
  "const",
  "continue",
  "debugger",
  "default",
  "delete",
  "do",
  "else",
  "enum",
  "export",
  "extends",
  "finally",
  "for",
  "from",
  "function",
  "if",
  "implements",
  "import",
  "in",
  "instanceof",
  "interface",
  "let",
  "new",
  "of",
  "package",
  "private",
  "protected",
  "public",
  "return",
  "static",
  "super",
  "switch",
  "this",
  "throw",
  "try",
  "typeof",
  "var",
  "void",
  "while",
  "with",
  "yield",
  "as",
  "type",
  "declare",
  "readonly",
  "namespace",
  "module",
  "keyof",
  "infer",
  "satisfies",
]);

const KEYWORDS_PYTHON = new Set([
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
]);

const KEYWORDS_RUST = new Set([
  "as",
  "async",
  "await",
  "break",
  "const",
  "continue",
  "crate",
  "dyn",
  "else",
  "enum",
  "extern",
  "false",
  "fn",
  "for",
  "if",
  "impl",
  "in",
  "let",
  "loop",
  "match",
  "mod",
  "move",
  "mut",
  "pub",
  "ref",
  "return",
  "self",
  "Self",
  "static",
  "struct",
  "super",
  "trait",
  "true",
  "type",
  "unsafe",
  "use",
  "where",
  "while",
]);

const KEYWORDS_GO = new Set([
  "break",
  "case",
  "chan",
  "const",
  "continue",
  "default",
  "defer",
  "else",
  "fallthrough",
  "for",
  "func",
  "go",
  "goto",
  "if",
  "import",
  "interface",
  "map",
  "package",
  "range",
  "return",
  "select",
  "struct",
  "switch",
  "type",
  "var",
]);

const KEYWORDS_JAVA = new Set([
  "abstract",
  "assert",
  "boolean",
  "break",
  "byte",
  "case",
  "catch",
  "char",
  "class",
  "const",
  "continue",
  "default",
  "do",
  "double",
  "else",
  "enum",
  "extends",
  "final",
  "finally",
  "float",
  "for",
  "goto",
  "if",
  "implements",
  "import",
  "instanceof",
  "int",
  "interface",
  "long",
  "native",
  "new",
  "package",
  "private",
  "protected",
  "public",
  "return",
  "short",
  "static",
  "strictfp",
  "super",
  "switch",
  "synchronized",
  "this",
  "throw",
  "throws",
  "transient",
  "try",
  "void",
  "volatile",
  "while",
]);

const KEYWORDS_RUBY = new Set([
  "BEGIN",
  "END",
  "alias",
  "and",
  "begin",
  "break",
  "case",
  "class",
  "def",
  "defined?",
  "do",
  "else",
  "elsif",
  "end",
  "ensure",
  "false",
  "for",
  "if",
  "in",
  "module",
  "next",
  "nil",
  "not",
  "or",
  "redo",
  "rescue",
  "retry",
  "return",
  "self",
  "super",
  "then",
  "true",
  "undef",
  "unless",
  "until",
  "when",
  "while",
  "yield",
]);

const KEYWORDS_CSS = new Set([
  "import",
  "media",
  "keyframes",
  "font-face",
  "supports",
  "charset",
  "namespace",
  "page",
  "layer",
]);

const KEYWORDS_SQL = new Set([
  "select",
  "from",
  "where",
  "insert",
  "update",
  "delete",
  "create",
  "drop",
  "alter",
  "table",
  "index",
  "view",
  "join",
  "inner",
  "outer",
  "left",
  "right",
  "on",
  "and",
  "or",
  "not",
  "in",
  "is",
  "null",
  "like",
  "between",
  "exists",
  "having",
  "group",
  "by",
  "order",
  "asc",
  "desc",
  "limit",
  "offset",
  "union",
  "all",
  "distinct",
  "as",
  "set",
  "values",
  "into",
  "primary",
  "key",
  "foreign",
  "references",
  "constraint",
  "default",
  "check",
  "unique",
  "cascade",
  "begin",
  "commit",
  "rollback",
  "transaction",
  "grant",
  "revoke",
  "with",
  "case",
  "when",
  "then",
  "else",
  "end",
  "count",
  "sum",
  "avg",
  "min",
  "max",
  "if",
  "replace",
  "truncate",
  "database",
  "schema",
  "use",
]);

const KEYWORDS_SHELL = new Set([
  "if",
  "then",
  "else",
  "elif",
  "fi",
  "for",
  "while",
  "do",
  "done",
  "case",
  "esac",
  "in",
  "function",
  "return",
  "exit",
  "echo",
  "read",
  "local",
  "export",
  "source",
  "alias",
  "unalias",
  "set",
  "unset",
  "shift",
  "trap",
  "eval",
  "exec",
  "break",
  "continue",
  "cd",
  "pwd",
  "ls",
  "cat",
  "grep",
  "sed",
  "awk",
  "find",
  "xargs",
  "sudo",
  "apt",
  "npm",
  "yarn",
  "pnpm",
  "pip",
  "git",
  "docker",
  "curl",
  "wget",
  "mkdir",
  "rm",
  "cp",
  "mv",
  "chmod",
  "chown",
]);

const BOOLEANS = new Set([
  "true",
  "false",
  "null",
  "undefined",
  "nil",
  "None",
  "True",
  "False",
  "NaN",
  "Infinity",
]);

function getKeywords(language: string): Set<string> {
  switch (language.toLowerCase()) {
    case "js":
    case "javascript":
    case "jsx":
    case "ts":
    case "typescript":
    case "tsx":
      return KEYWORDS_JS;
    case "py":
    case "python":
      return KEYWORDS_PYTHON;
    case "rs":
    case "rust":
      return KEYWORDS_RUST;
    case "go":
    case "golang":
      return KEYWORDS_GO;
    case "java":
    case "kotlin":
    case "scala":
      return KEYWORDS_JAVA;
    case "rb":
    case "ruby":
      return KEYWORDS_RUBY;
    case "css":
    case "scss":
    case "less":
      return KEYWORDS_CSS;
    case "sql":
    case "mysql":
    case "postgresql":
    case "sqlite":
      return KEYWORDS_SQL;
    case "sh":
    case "bash":
    case "zsh":
    case "shell":
      return KEYWORDS_SHELL;
    default:
      return KEYWORDS_JS; // reasonable default
  }
}

function isCaseSensitive(language: string): boolean {
  const insensitive = new Set(["sql", "mysql", "postgresql", "sqlite"]);
  return !insensitive.has(language.toLowerCase());
}

type TokenKind = Token["type"];

/**
 * Result of a single tokenizer scan attempt.
 * `consumed` characters are appended to the current index; `stop` ends the line.
 */
interface ScanResult {
  tokens: Token[];
  consumed: number;
  stop?: boolean;
}

const STRING_PATTERNS: Record<string, RegExp> = {
  '"': /^"(?:[^"\\]|\\.)*"/,
  "'": /^'(?:[^'\\]|\\.)*'/,
  "`": /^`(?:[^`\\]|\\.)*`/,
};

const NUMBER_PATTERN =
  /^0[xX][0-9a-fA-F_]+|^0[bB][01_]+|^0[oO][0-7_]+|^\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?|^\.\d[\d_]*(?:[eE][+-]?\d+)?/;

const OPERATOR_PATTERN =
  /^(?:===|!==|==|!=|<=|>=|=>|&&|\|\||<<|>>|>>>|\?\?|\?\.|\.\.\.|\*\*|[+\-*/<>!&|?^~%=])/;

const IDENTIFIER_PATTERN = /^[a-zA-Z_$][\w$]*/;

function scanLineComment(line: string, i: number): ScanResult | null {
  const ch = line[i];
  if (
    (ch === "/" && line[i + 1] === "/") ||
    (ch === "#" && !isShebang(line, i) && !isInsideString(line, i))
  ) {
    return {
      tokens: [{ type: "comment", value: line.slice(i) }],
      consumed: line.length - i,
      stop: true,
    };
  }
  return null;
}

function scanBlockComment(line: string, i: number): ScanResult | null {
  if (!(line[i] === "/" && line[i + 1] === "*")) return null;
  const end = line.indexOf("*/", i + 2);
  if (end !== -1) {
    return {
      tokens: [{ type: "comment", value: line.slice(i, end + 2) }],
      consumed: end + 2 - i,
    };
  }
  return {
    tokens: [{ type: "comment", value: line.slice(i) }],
    consumed: line.length - i,
    stop: true,
  };
}

function scanDecorator(line: string, i: number): ScanResult | null {
  const rest = line.slice(i);
  if (!(line[i] === "@" && /^@\w+/.test(rest))) return null;
  const m = rest.match(/^@[\w.]+/);
  if (!m) return null;
  return {
    tokens: [{ type: "decorator", value: m[0] }],
    consumed: m[0].length,
  };
}

function scanString(line: string, i: number): ScanResult | null {
  const pattern = STRING_PATTERNS[line[i]];
  if (!pattern) return null;
  const m = line.slice(i).match(pattern);
  if (m) {
    return { tokens: [{ type: "string", value: m[0] }], consumed: m[0].length };
  }
  // Unterminated string - take rest of line
  return {
    tokens: [{ type: "string", value: line.slice(i) }],
    consumed: line.length - i,
    stop: true,
  };
}

function scanNumber(line: string, i: number): ScanResult | null {
  const ch = line[i];
  const isNumberStart =
    /[0-9]/.test(ch) || (ch === "." && /[0-9]/.test(line[i + 1] || ""));
  if (!isNumberStart) return null;
  const m = line.slice(i).match(NUMBER_PATTERN);
  if (!m) return null;
  return { tokens: [{ type: "number", value: m[0] }], consumed: m[0].length };
}

function wordTokenKind(
  word: string,
  wordToCheck: string,
  lookAhead: string,
  keywords: Set<string>,
): TokenKind {
  if (BOOLEANS.has(word)) return "boolean";
  if (keywords.has(wordToCheck)) return "keyword";
  if (lookAhead.startsWith("(")) return "function";
  if (/^[A-Z]/.test(word) && word.length > 1) return "type";
  return "plain";
}

function scanWord(
  line: string,
  i: number,
  keywords: Set<string>,
  caseSensitive: boolean,
): ScanResult | null {
  if (!/[a-zA-Z_$]/.test(line[i])) return null;
  const m = line.slice(i).match(IDENTIFIER_PATTERN);
  if (!m) return null;
  const word = m[0];
  const lookAhead = line.slice(i + word.length).trimStart();
  const wordToCheck = caseSensitive ? word : word.toLowerCase();
  return {
    tokens: [
      {
        type: wordTokenKind(word, wordToCheck, lookAhead, keywords),
        value: word,
      },
    ],
    consumed: word.length,
  };
}

function scanPropertyAccess(line: string, i: number): ScanResult | null {
  if (!(line[i] === "." && /[a-zA-Z_$]/.test(line[i + 1] || ""))) return null;
  const tokens: Token[] = [{ type: "punctuation", value: "." }];
  let consumed = 1;
  const m = line.slice(i + 1).match(IDENTIFIER_PATTERN);
  if (m) {
    const lookAhead = line.slice(i + 1 + m[0].length).trimStart();
    tokens.push({
      type: lookAhead.startsWith("(") ? "function" : "property",
      value: m[0],
    });
    consumed += m[0].length;
  }
  return { tokens, consumed };
}

function scanOperator(line: string, i: number): ScanResult | null {
  if (!/[=+\-*/<>!&|?^~%]/.test(line[i])) return null;
  const m = line.slice(i).match(OPERATOR_PATTERN);
  if (!m) return null;
  return { tokens: [{ type: "operator", value: m[0] }], consumed: m[0].length };
}

function scanPunctuation(line: string, i: number): ScanResult | null {
  if (!/[(){}[\],;:.]/.test(line[i])) return null;
  return { tokens: [{ type: "punctuation", value: line[i] }], consumed: 1 };
}

function scanJsxTag(line: string, i: number): ScanResult | null {
  const rest = line.slice(i);
  if (!(line[i] === "<" && /^<\/?[A-Za-z]/.test(rest))) return null;
  const tagMatch = rest.match(/^<\/?([A-Za-z][\w.-]*)/);
  if (!tagMatch) return null;
  const isClosing = rest.startsWith("</");
  return {
    tokens: [
      { type: "punctuation", value: isClosing ? "</" : "<" },
      { type: "tag", value: tagMatch[1] },
    ],
    consumed: (isClosing ? 2 : 1) + tagMatch[1].length,
  };
}

export function tokenizeLine(line: string, language: string): Token[] {
  if (line.length === 0) return [{ type: "plain", value: "" }];

  const tokens: Token[] = [];
  const rawKeywords = getKeywords(language);
  const caseSensitive = isCaseSensitive(language);
  // Precompute the effective keyword set once (case-insensitive langs lower-case).
  const keywords = caseSensitive
    ? rawKeywords
    : new Set([...rawKeywords].map((k) => k.toLowerCase()));
  let i = 0;

  while (i < line.length) {
    // Order matters: comments before operators, property access before
    // punctuation, and JSX tags before operators so `<Component>` is not eaten
    // as a `<` operator (a spaced comparison like `a < b` still falls through
    // to scanOperator since scanJsxTag requires a letter right after `<`).
    const result =
      scanLineComment(line, i) ??
      scanBlockComment(line, i) ??
      scanDecorator(line, i) ??
      scanString(line, i) ??
      scanNumber(line, i) ??
      scanWord(line, i, keywords, caseSensitive) ??
      scanPropertyAccess(line, i) ??
      scanJsxTag(line, i) ??
      scanOperator(line, i) ??
      scanPunctuation(line, i);

    if (result) {
      tokens.push(...result.tokens);
      i += result.consumed;
      if (result.stop) break;
    } else {
      // Whitespace or anything else: plain
      tokens.push({ type: "plain", value: line[i] });
      i++;
    }
  }

  return tokens;
}

// Helper: detect shebang line
function isShebang(line: string, pos: number): boolean {
  return pos === 0 && line.startsWith("#!");
}

// Simple heuristic to avoid treating # inside strings as comments
function isInsideString(line: string, pos: number): boolean {
  let inSingle = false;
  let inDouble = false;
  for (let j = 0; j < pos; j++) {
    if (line[j] === "'" && !inDouble && line[j - 1] !== "\\")
      inSingle = !inSingle;
    if (line[j] === '"' && !inSingle && line[j - 1] !== "\\")
      inDouble = !inDouble;
  }
  return inSingle || inDouble;
}
