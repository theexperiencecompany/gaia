import { Box, Text } from "ink";
import type React from "react";
import type { CommandEnding } from "../../lib/command-ending.js";
import { THEME_COLOR } from "../constants.js";

/** The run's last lines: the one next action, then its alternates dimmed. */
export const Ending: React.FC<{ ending: CommandEnding }> = ({ ending }) => (
  <Box flexDirection="column" marginTop={1}>
    {/* A target too long to share the lead's line moves under it whole, never split. */}
    <Box flexWrap="wrap" columnGap={2}>
      <Text>{ending.lead}</Text>
      <Text bold color={THEME_COLOR}>
        {ending.target}
      </Text>
    </Box>
    {(ending.also ?? []).map((line) => (
      <Text key={line} dimColor>
        {line}
      </Text>
    ))}
  </Box>
);
