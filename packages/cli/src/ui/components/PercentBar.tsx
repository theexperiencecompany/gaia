import { ProgressBar } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";

/** Leaves an 80-column terminal room for the caption beside it. */
const BAR_WIDTH = 30;

/**
 * A progress bar with what it measures beside it: the caption ("62%  410 /
 * 660 MB · about 1 min left"), or the bare percentage where there is none.
 */
export const PercentBar: React.FC<{ percent: number; caption?: string }> = ({
  percent,
  caption,
}) => (
  <Box>
    <Box width={BAR_WIDTH}>
      <ProgressBar value={percent} />
    </Box>
    <Text dimColor>{`  ${caption ?? `${percent}%`}`}</Text>
  </Box>
);
