import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useRef, useState } from "react";

const MAX_VISIBLE_LINES = 8;

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/**
 * The newest lines of a running step's output, dimmed. Grows with its lines
 * up to {@link MAX_VISIBLE_LINES}; past that, ↑/↓ scroll and the hint says so.
 */
export const LogWindow: React.FC<{ logs: string[] }> = ({ logs }) => {
  const [scrollOffset, setScrollOffset] = useState(0);
  const height = Math.min(logs.length, MAX_VISIBLE_LINES);
  const scrollable = logs.length > MAX_VISIBLE_LINES;

  // New lines snap back to the bottom.
  const prevLenRef = useRef(logs.length);
  useEffect(() => {
    if (logs.length !== prevLenRef.current) {
      prevLenRef.current = logs.length;
      setScrollOffset(0);
    }
  }, [logs.length]);

  useInput((_input, key) => {
    if (!scrollable) return;
    if (key.upArrow) {
      setScrollOffset((o) => Math.min(o + 1, logs.length - height));
    } else if (key.downArrow) {
      setScrollOffset((o) => Math.max(0, o - 1));
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
