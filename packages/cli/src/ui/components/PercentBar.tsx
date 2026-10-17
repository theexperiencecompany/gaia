import { ProgressBar } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";

/** Fits an 80-column terminal next to the percentage. */
const BAR_WIDTH = 40;

/** A progress bar with its percentage written beside it. */
export const PercentBar: React.FC<{ percent: number }> = ({ percent }) => (
  <Box>
    <Box width={BAR_WIDTH}>
      <ProgressBar value={percent} />
    </Box>
    <Text color="gray"> {percent}%</Text>
  </Box>
);
