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
      // No more OpenUI blocks — rest is markdown
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

    // Push markdown before the OpenUI block
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

    // Find the content start (after ":::openui\n" or ":::openui")
    const contentStart = openIdx + OPENUI_OPEN.length;

    // Find closing fence: look for "\n:::" that is NOT followed by "openui"
    let closeIdx = -1;
    let searchFrom = contentStart;
    while (searchFrom < text.length) {
      const candidate = text.indexOf(OPENUI_CLOSE, searchFrom);
      if (candidate === -1) break;
      // Make sure this ":::" is the closing fence, not another ":::openui"
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
      // Complete OpenUI block
      const openUIContent = text.slice(contentStart, closeIdx).trim();
      if (openUIContent) {
        segments.push({
          type: "openui",
          content: openUIContent,
          isComplete: true,
        });
      }
      // Move past the closing fence + newline
      cursor = closeIdx + OPENUI_CLOSE.length;
    } else {
      // Unclosed block — still streaming or malformed
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

  // Filter out empty segments
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
    // Fast path: no fences, split normally
    return content
      .split(BREAK)
      .map((p) => p.trim())
      .filter((p) => p.length > 0);
  }

  // Build a set of ranges [start, end) that are inside OpenUI fences
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
      // Unclosed fence — protect to end
      fenceRanges.push([openIdx, content.length]);
      break;
    }
  }

  const isInsideFence = (pos: number) =>
    fenceRanges.some(([s, e]) => pos >= s && pos < e);

  // Find break positions that are NOT inside fences
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
