/**
 * JSON formatting utilities
 * Handles parsing, validation, and formatting of JSON data
 */

/**
 * Check if a value is a plain object (not null, not array)
 */
export function isPlainObject(
  value: unknown,
): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Safely parse JSON string, returns null if invalid
 */
export function safeJsonParse(value: string): unknown | null {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

/**
 * Check if a string looks like JSON (starts with { or [)
 */
export function looksLikeJson(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

/**
 * Format a JSON-like string with proper indentation
 * Works even with incomplete/truncated JSON
 */
export function formatJsonLikeString(str: string): string {
  // First try to parse and stringify (handles valid JSON perfectly)
  const parsed = safeJsonParse(str);
  if (parsed !== null) {
    return JSON.stringify(parsed, null, 2);
  }

  // For invalid/truncated JSON, manually format it
  let result = "";
  let indentLevel = 0;
  let inString = false;
  let escaped = false;
  const indent = "  ";

  for (let i = 0; i < str.length; i++) {
    const char = str[i];

    // Handle escape sequences in strings
    if (escaped) {
      result += char;
      escaped = false;
      continue;
    }

    if (char === "\\" && inString) {
      result += char;
      escaped = true;
      continue;
    }

    // Toggle string mode on unescaped quotes
    if (char === '"' && !escaped) {
      inString = !inString;
      result += char;
      continue;
    }

    // If inside a string, just append the character
    if (inString) {
      result += char;
      continue;
    }

    // Handle structural characters outside of strings
    switch (char) {
      case "{":
      case "[":
        result += char;
        indentLevel++;
        result += `\n${indent.repeat(indentLevel)}`;
        break;
      case "}":
      case "]":
        indentLevel = Math.max(0, indentLevel - 1);
        result += `\n${indent.repeat(indentLevel)}${char}`;
        break;
      case ",":
        result += `${char}\n${indent.repeat(indentLevel)}`;
        break;
      case ":":
        result += ": ";
        break;
      case " ":
      case "\n":
      case "\r":
      case "\t":
        // Skip whitespace outside strings (we're adding our own)
        break;
      default:
        result += char;
    }
  }

  return result;
}

/**
 * Normalize any value to a displayable format
 * Returns { data, isStructured } where:
 * - data: the normalized value (object/array for structured, string for text)
 * - isStructured: true if it should be displayed as preformatted/code
 */
export function normalizeValue(value: unknown): {
  data: unknown;
  isStructured: boolean;
} {
  // Handle null/undefined
  if (value == null) {
    return { data: "", isStructured: false };
  }

  // Handle arrays
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return { data: [], isStructured: true };
    }
    // Check if it's an array of TextContent-like objects with 'text' property
    if (isPlainObject(value[0]) && "text" in value[0]) {
      const texts = value
        .map((item) =>
          isPlainObject(item) && "text" in item
            ? String(item.text)
            : String(item),
        )
        .join("\n");
      // The extracted text might be JSON
      const parsed = safeJsonParse(texts);
      if (parsed !== null && (isPlainObject(parsed) || Array.isArray(parsed))) {
        return { data: parsed, isStructured: true };
      }
      // Even if not valid JSON, if it looks like JSON, show as preformatted
      if (looksLikeJson(texts)) {
        return { data: texts, isStructured: true };
      }
      return { data: texts, isStructured: false };
    }
    // Regular array - return as structured data
    return { data: value, isStructured: true };
  }

  // Handle plain objects
  if (isPlainObject(value)) {
    // If it has a 'text' property, extract it (TextContent-like)
    if ("text" in value && typeof value.text === "string") {
      const parsed = safeJsonParse(value.text);
      if (parsed !== null && (isPlainObject(parsed) || Array.isArray(parsed))) {
        return { data: parsed, isStructured: true };
      }
      // Even if not valid JSON, if it looks like JSON, show as preformatted
      if (looksLikeJson(value.text)) {
        return { data: value.text, isStructured: true };
      }
      return { data: value.text, isStructured: false };
    }
    // Regular object - return as structured data
    return { data: value, isStructured: true };
  }

  // Handle strings
  if (typeof value === "string") {
    // Try to parse as JSON first
    const parsed = safeJsonParse(value);
    if (parsed !== null && (isPlainObject(parsed) || Array.isArray(parsed))) {
      return { data: parsed, isStructured: true };
    }

    // Handle Python TextContent string format: [TextContent(type='text', text='...')]
    const textContentMatch = value.match(
      /\[TextContent\([^)]*text='([\s\S]*)'\s*(?:,\s*\w+=\w+)*\)\]/,
    );
    if (textContentMatch) {
      const extracted = textContentMatch[1]
        .replace(/''/g, "'")
        .replace(/\\'/g, "'");
      const innerParsed = safeJsonParse(extracted);
      if (
        innerParsed !== null &&
        (isPlainObject(innerParsed) || Array.isArray(innerParsed))
      ) {
        return { data: innerParsed, isStructured: true };
      }
      // Even if not valid JSON (e.g., truncated), if it looks like JSON, show as preformatted
      if (looksLikeJson(extracted)) {
        return { data: extracted, isStructured: true };
      }
      return { data: extracted, isStructured: false };
    }

    // Even without TextContent wrapper, if it looks like JSON, show as preformatted
    if (looksLikeJson(value)) {
      return { data: value, isStructured: true };
    }

    return { data: value, isStructured: false };
  }

  // Fallback for other types (numbers, booleans, etc.)
  return { data: String(value), isStructured: false };
}
