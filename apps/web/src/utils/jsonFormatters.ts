/**
 * JSON formatting utilities
 * Handles parsing, validation, and formatting of JSON data
 */

/**
 * Check if a value is a plain object (not null, not array)
 */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Check if an object is a TextContent-like object (has type="text" and text property)
 * This is more specific than just checking for a "text" property to avoid
 * incorrectly extracting text from objects that happen to have a "text" field
 * (e.g., Twitter DM inputs with { text: "message", recipient_id: "..." })
 */
function isTextContentObject(value: Record<string, unknown>): boolean {
  return (
    "type" in value &&
    value.type === "text" &&
    "text" in value &&
    typeof value.text === "string"
  );
}

/**
 * Safely parse JSON string, returns null if invalid
 */
function safeJsonParse(value: string): unknown | null {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

/**
 * Check if a string looks like JSON (starts with { or [)
 */
function looksLikeJson(value: string): boolean {
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

interface NormalizedValue {
  data: unknown;
  isStructured: boolean;
}

/**
 * Normalize an extracted text payload: parse it as JSON when possible, else
 * treat JSON-looking text as preformatted, otherwise return it as plain text.
 */
function normalizeExtractedText(text: string): NormalizedValue {
  const parsed = safeJsonParse(text);
  if (parsed !== null && (isPlainObject(parsed) || Array.isArray(parsed))) {
    return { data: parsed, isStructured: true };
  }
  // Even if not valid JSON, if it looks like JSON, show as preformatted
  if (looksLikeJson(text)) {
    return { data: text, isStructured: true };
  }
  return { data: text, isStructured: false };
}

function normalizeArray(value: unknown[]): NormalizedValue {
  if (value.length === 0) {
    return { data: [], isStructured: true };
  }
  // Check if it's an array of TextContent-like objects (must have type="text" AND text property)
  if (isPlainObject(value[0]) && isTextContentObject(value[0])) {
    const texts = value
      .map((item) =>
        isPlainObject(item) && isTextContentObject(item)
          ? String(item.text)
          : String(item),
      )
      .join("\n");
    // The extracted text might be JSON
    return normalizeExtractedText(texts);
  }
  // Regular array - return as structured data
  return { data: value, isStructured: true };
}

function normalizeObject(value: Record<string, unknown>): NormalizedValue {
  // If it's a TextContent-like object (type="text" + text property), extract the text
  if (isTextContentObject(value)) {
    return normalizeExtractedText(value.text as string);
  }
  // Regular object - return as structured data
  return { data: value, isStructured: true };
}

function normalizeString(value: string): NormalizedValue {
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
    return normalizeExtractedText(extracted);
  }

  // Even without TextContent wrapper, if it looks like JSON, show as preformatted
  if (looksLikeJson(value)) {
    return { data: value, isStructured: true };
  }

  return { data: value, isStructured: false };
}

/**
 * Normalize any value to a displayable format
 * Returns { data, isStructured } where:
 * - data: the normalized value (object/array for structured, string for text)
 * - isStructured: true if it should be displayed as preformatted/code
 */
export function normalizeValue(value: unknown): NormalizedValue {
  // Handle null/undefined
  if (value == null) {
    return { data: "", isStructured: false };
  }

  if (Array.isArray(value)) {
    return normalizeArray(value);
  }

  if (isPlainObject(value)) {
    return normalizeObject(value);
  }

  if (typeof value === "string") {
    return normalizeString(value);
  }

  // Fallback for other types (numbers, booleans, etc.)
  return { data: String(value), isStructured: false };
}
