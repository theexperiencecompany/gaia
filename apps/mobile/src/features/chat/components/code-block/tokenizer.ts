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

export function tokenizeLine(line: string, language: string): Token[] {
  if (line.length === 0) return [{ type: "plain", value: "" }];

  const tokens: Token[] = [];
  const keywords = getKeywords(language);
  const caseSensitive = isCaseSensitive(language);
  let i = 0;

  function push(type: Token["type"], value: string) {
    tokens.push({ type, value });
  }

  function _matchAt(pattern: RegExp): RegExpMatchArray | null {
    pattern.lastIndex = i;
    return pattern.exec(line);
  }

  while (i < line.length) {
    const ch = line[i];
    const rest = line.slice(i);

    // Single-line comment: // or #
    if (
      (ch === "/" && line[i + 1] === "/") ||
      (ch === "#" && !isShebang(line, i) && !isInsideString(line, i))
    ) {
      push("comment", line.slice(i));
      break;
    }

    // Block comment start /* ... (only captures to end of line)
    if (ch === "/" && line[i + 1] === "*") {
      const end = line.indexOf("*/", i + 2);
      if (end !== -1) {
        push("comment", line.slice(i, end + 2));
        i = end + 2;
        continue;
      }
      push("comment", line.slice(i));
      break;
    }

    // Decorator
    if (ch === "@" && /^@\w+/.test(rest)) {
      const m = rest.match(/^@[\w.]+/);
      if (m) {
        push("decorator", m[0]);
        i += m[0].length;
        continue;
      }
    }

    // Strings: double-quoted
    if (ch === '"') {
      const m = rest.match(/^"(?:[^"\\]|\\.)*"/);
      if (m) {
        push("string", m[0]);
        i += m[0].length;
        continue;
      }
      // Unterminated string - take rest of line
      push("string", line.slice(i));
      break;
    }

    // Strings: single-quoted
    if (ch === "'") {
      const m = rest.match(/^'(?:[^'\\]|\\.)*'/);
      if (m) {
        push("string", m[0]);
        i += m[0].length;
        continue;
      }
      push("string", line.slice(i));
      break;
    }

    // Template strings
    if (ch === "`") {
      const m = rest.match(/^`(?:[^`\\]|\\.)*`/);
      if (m) {
        push("string", m[0]);
        i += m[0].length;
        continue;
      }
      push("string", line.slice(i));
      break;
    }

    // Numbers
    if (/[0-9]/.test(ch) || (ch === "." && /[0-9]/.test(line[i + 1] || ""))) {
      const m = rest.match(
        /^0[xX][0-9a-fA-F_]+|^0[bB][01_]+|^0[oO][0-7_]+|^\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?/,
      );
      if (m) {
        push("number", m[0]);
        i += m[0].length;
        continue;
      }
    }

    // Words: keywords, booleans, types, functions
    if (/[a-zA-Z_$]/.test(ch)) {
      const m = rest.match(/^[a-zA-Z_$][\w$]*/);
      if (m) {
        const word = m[0];
        const lookAhead = line.slice(i + word.length).trimStart();

        const wordToCheck = caseSensitive ? word : word.toLowerCase();
        const keywordSet = caseSensitive
          ? keywords
          : new Set([...keywords].map((k) => k.toLowerCase()));

        if (BOOLEANS.has(word)) {
          push("boolean", word);
        } else if (keywordSet.has(wordToCheck)) {
          push("keyword", word);
        } else if (lookAhead.startsWith("(")) {
          push("function", word);
        } else if (/^[A-Z]/.test(word) && word.length > 1) {
          push("type", word);
        } else {
          push("plain", word);
        }
        i += word.length;
        continue;
      }
    }

    // Property access: .identifier
    if (ch === "." && /[a-zA-Z_$]/.test(line[i + 1] || "")) {
      push("punctuation", ".");
      i++;
      const m = line.slice(i).match(/^[a-zA-Z_$][\w$]*/);
      if (m) {
        const lookAhead = line.slice(i + m[0].length).trimStart();
        if (lookAhead.startsWith("(")) {
          push("function", m[0]);
        } else {
          push("property", m[0]);
        }
        i += m[0].length;
      }
      continue;
    }

    // Operators
    if (/[=+\-*/<>!&|?^~%]/.test(ch)) {
      // Grab multi-char operators
      const m = rest.match(
        /^(?:===|!==|==|!=|<=|>=|=>|&&|\|\||<<|>>|>>>|\?\?|\?\.|\.\.\.|\*\*|[+\-*/<>!&|?^~%=])/,
      );
      if (m) {
        push("operator", m[0]);
        i += m[0].length;
        continue;
      }
    }

    // Punctuation
    if (/[(){}[\],;:.]/.test(ch)) {
      push("punctuation", ch);
      i++;
      continue;
    }

    // JSX/HTML tag detection: < followed by letter or /
    if (ch === "<" && /^<\/?[A-Za-z]/.test(rest)) {
      const tagMatch = rest.match(/^<\/?([A-Za-z][\w.-]*)/);
      if (tagMatch) {
        push("punctuation", rest.startsWith("</") ? "</" : "<");
        i += rest.startsWith("</") ? 2 : 1;
        push("tag", tagMatch[1]);
        i += tagMatch[1].length;
        continue;
      }
    }

    // Whitespace or anything else: plain
    push("plain", ch);
    i++;
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
