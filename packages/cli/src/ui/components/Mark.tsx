import { Box, Text } from "ink";
import type React from "react";
import { MARK, MARK_COLOR, type MarkKind } from "../constants.js";

/** One status mark (ok, fail, warn, skip) in its colour, followed by a space. */
export const Mark: React.FC<{ kind: MarkKind }> = ({ kind }) => (
  <Box marginRight={1}>
    <Text color={MARK_COLOR[kind]}>{MARK[kind]}</Text>
  </Box>
);
