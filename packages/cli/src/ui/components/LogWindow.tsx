import { Box, Text, useInput } from "ink";
import type React from "react";
import { useState } from "react";

const MAX_VISIBLE_LINES = 8;

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/**
 * The newest lines of a running step's output, dimmed. Grows with its lines
 * up to {@link MAX_VISIBLE_LINES}; past that, ↑/↓ scroll and the hint says so.
 */
export const LogWindow: React.FC<{ logs: string[] }> = ({ logs }) => {
  // The offset belongs to the line count it was scrolled at, so new lines snap back to the bottom.
  const [scroll, setScroll] = useState({ offset: 0, lineCount: logs.length });
  const scrollOffset = scroll.lineCount === logs.length ? scroll.offset : 0;
  const height = Math.min(logs.length, MAX_VISIBLE_LINES);
  const scrollable = logs.length > MAX_VISIBLE_LINES;

  useInput((_input, key) => {
    if (!scrollable) return;
    if (key.upArrow) {
      setScroll({
        offset: Math.min(scrollOffset + 1, logs.length - height),
        lineCount: logs.length,
      });
    } else if (key.downArrow) {
      setScroll({
        offset: Math.max(0, scrollOffset - 1),
        lineCount: logs.length,
      });
    }
  });

  const start = Math.max(0, logs.length - height - scrollOffset);
  const visible = logs.slice(start, start + height);

  return (
    <Box flexDirection="column" marginTop={1} marginLeft={1}>
      {start > 0 && (
        <Text color="gray">{plural(start, "earlier line")} (↑ to scroll)</Text>
      )}
      {visible.map((line, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: logs are append-only
        <Text key={start + i} color="gray" wrap="truncate">
          {line}
        </Text>
      ))}
      {scrollOffset > 0 && (
        <Text color="gray">{plural(scrollOffset, "newer line")} (↓)</Text>
      )}
    </Box>
  );
};
