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
 * Hidden during the Welcome step.
 * @param props - Footer properties
 * @param props.status - Status message
 * @param props.step - Current step name
 */
export const Footer: React.FC<FooterProps> = ({ status, step }) => {
  if (step.toLowerCase() === "welcome") return null;
  return (
    <Box width="100%" paddingX={1} marginTop={1}>
      <Text color="gray" dimColor>
        {status}
      </Text>
    </Box>
  );
};
