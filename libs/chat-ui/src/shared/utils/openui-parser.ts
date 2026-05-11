/**
 * Minimal structural type for @openuidev/react-lang's Library.
 * Duck-typed to avoid a hard dep on a specific openui version.
 */
export interface OpenUILibraryLike {
  components: Record<string, { props: { shape: Record<string, unknown> } }>;
}

export interface ContentSegment {
  type: "markdown" | "openui";
  content: string;
  isComplete: boolean;
}

const OPENUI_OPEN = ":::openui";
const OPENUI_CLOSE = "\n:::";

/**
 * Parse response text into segments of markdown and OpenUI blocks.
 *
 * During streaming, an unclosed :::openui block is returned with
 * isComplete=false so the renderer can display a streaming state
 * instead of flashing raw syntax.
 */
export function parseOpenUISegments(
  text: string,
  isStreaming: boolean,
): ContentSegment[] {
  if (!text || !text.includes(OPENUI_OPEN)) {
    return [{ type: "markdown", content: text || "", isComplete: true }];
  }

  const segments: ContentSegment[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    const openIdx = text.indexOf(OPENUI_OPEN, cursor);

    if (openIdx === -1) {
      const remaining = text.slice(cursor);
      if (remaining) {
        segments.push({
          type: "markdown",
          content: remaining,
          isComplete: true,
        });
      }
      break;
    }

    if (openIdx > cursor) {
      const markdownBefore = text.slice(cursor, openIdx);
      if (markdownBefore.trim()) {
        segments.push({
          type: "markdown",
          content: markdownBefore,
          isComplete: true,
        });
      }
    }

    const contentStart = openIdx + OPENUI_OPEN.length;

    let closeIdx = -1;
    let searchFrom = contentStart;
    while (searchFrom < text.length) {
      const candidate = text.indexOf(OPENUI_CLOSE, searchFrom);
      if (candidate === -1) break;
      const afterClose = candidate + OPENUI_CLOSE.length;
      if (
        afterClose >= text.length ||
        !text.slice(afterClose).startsWith("openui")
      ) {
        closeIdx = candidate;
        break;
      }
      searchFrom = afterClose;
    }

    if (closeIdx !== -1) {
      const openUIContent = text.slice(contentStart, closeIdx).trim();
      if (openUIContent) {
        segments.push({
          type: "openui",
          content: openUIContent,
          isComplete: true,
        });
      }
      cursor = closeIdx + OPENUI_CLOSE.length;
    } else {
      const openUIContent = text.slice(contentStart).trim();
      if (openUIContent) {
        segments.push({
          type: "openui",
          content: openUIContent,
          isComplete: !isStreaming,
        });
      }
      break;
    }
  }

  return segments.filter((s) => s.content.trim().length > 0);
}

/**
 * Split text by NEW_MESSAGE_BREAK while preserving OpenUI fences.
 *
 * Breaks inside :::openui / ::: blocks are ignored so a fence is
 * never bisected across two bubbles.
 */
export function splitByBreaksPreservingFences(content: string): string[] {
  const BREAK = "<NEW_MESSAGE_BREAK>";
  if (!content?.trim()) return [];
  if (!content.includes(BREAK)) return [content];
  if (!content.includes(OPENUI_OPEN)) {
    return content
      .split(BREAK)
      .map((p) => p.trim())
      .filter((p) => p.length > 0);
  }

  const fenceRanges: Array<[number, number]> = [];
  let search = 0;
  while (search < content.length) {
    const openIdx = content.indexOf(OPENUI_OPEN, search);
    if (openIdx === -1) break;
    let closeIdx = -1;
    let from = openIdx + OPENUI_OPEN.length;
    while (from < content.length) {
      const candidate = content.indexOf(OPENUI_CLOSE, from);
      if (candidate === -1) break;
      const after = candidate + OPENUI_CLOSE.length;
      if (
        after >= content.length ||
        !content.slice(after).startsWith("openui")
      ) {
        closeIdx = candidate + OPENUI_CLOSE.length;
        break;
      }
      from = after;
    }
    if (closeIdx !== -1) {
      fenceRanges.push([openIdx, closeIdx]);
      search = closeIdx;
    } else {
      fenceRanges.push([openIdx, content.length]);
      break;
    }
  }

  const isInsideFence = (pos: number) =>
    fenceRanges.some(([s, e]) => pos >= s && pos < e);

  const parts: string[] = [];
  let cursor = 0;
  let breakIdx = content.indexOf(BREAK, cursor);
  while (breakIdx !== -1) {
    if (!isInsideFence(breakIdx)) {
      const part = content.slice(cursor, breakIdx).trim();
      if (part) parts.push(part);
      cursor = breakIdx + BREAK.length;
    }
    breakIdx = content.indexOf(BREAK, breakIdx + BREAK.length);
  }
  const tail = content.slice(cursor).trim();
  if (tail) parts.push(tail);

  return parts;
}

function splitTopLevelArgs(s: string): string[] {
  const args: string[] = [];
  let depth = 0;
  let inStr = false;
  let esc = false;
  let start = 0;

  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (esc) {
      esc = false;
      continue;
    }
    if (c === "\\" && inStr) {
      esc = true;
      continue;
    }
    if (c === '"') {
      inStr = !inStr;
      continue;
    }
    if (inStr) continue;
    if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === "," && depth === 0) {
      args.push(s.slice(start, i));
      start = i + 1;
    }
  }
  args.push(s.slice(start));
  return args;
}

function parseNamedArg(arg: string): { name: string; value: string } | null {
  const trimmed = arg.trim();
  const m = trimmed.match(/^([a-z_][a-zA-Z0-9_]*)\s*=\s*([\s\S]*)$/);
  if (!m) return null;
  return { name: m[1], value: m[2].trim() };
}

/**
 * Convert openui code that uses named args (`key=value`) into the
 * positional form the parser expects, using the library's schema field order.
 */
export function normalizeOpenUICode(
  code: string,
  library: OpenUILibraryLike,
): string {
  const lines = code.split("\n");

  return lines
    .map((line) => {
      const m = line.match(/^(\s*\w+\s*=\s*)([A-Z]\w*)\(([\s\S]*)\)(\s*)$/);
      if (!m) return line;

      const [, prefix, compName, argsStr, suffix] = m;
      const def = library.components[compName];
      if (!def) return line;

      const rawArgs = splitTopLevelArgs(argsStr);
      const parsed = rawArgs.map(parseNamedArg);

      if (parsed.every((p) => p === null)) return line;

      if (parsed.some((p) => p !== null) && parsed.some((p) => p === null))
        return line;

      const namedMap: Record<string, string> = {};
      for (const p of parsed as { name: string; value: string }[]) {
        namedMap[p.name] = p.value;
      }

      const fieldNames = Object.keys(
        (def.props as { shape: Record<string, unknown> }).shape,
      );
      const positionalArgs = fieldNames.map((f) => namedMap[f] ?? "null");

      while (
        positionalArgs.length > 0 &&
        positionalArgs[positionalArgs.length - 1] === "null"
      ) {
        positionalArgs.pop();
      }

      return `${prefix}${compName}(${positionalArgs.join(", ")})${suffix}`;
    })
    .join("\n");
}
