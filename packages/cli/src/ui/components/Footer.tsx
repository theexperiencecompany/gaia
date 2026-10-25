/**
 * Footer component for the CLI interface.
 * @module components/Footer
 */

import { Box, Text } from "ink";
import type React from "react";

/**
 * Props for the Footer component.
 */
interface FooterProps {
  /** Current status message to display */
  status: string;
  /** Current step in the setup flow */
  step: string;
}

/**
 * Footer component displaying current step and status.
 * Hidden on the Welcome and Finished steps.
 * @param props - Footer properties
 * @param props.status - Status message
 * @param props.step - Current step name
 */
/** Welcome has nothing to report yet; Finished says it all in its summary. */
const HIDDEN_ON_STEPS = new Set(["Welcome", "Finished"]);

export const Footer: React.FC<FooterProps> = ({ status, step }) => {
  if (HIDDEN_ON_STEPS.has(step)) return null;
  return (
    <Box width="100%" paddingX={1} marginTop={1}>
      <Text color="gray" dimColor>
        {status}
      </Text>
    </Box>
  );
};
