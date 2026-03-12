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
