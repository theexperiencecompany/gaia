/**
 * Shell component providing the main layout structure.
 * @module components/Shell
 */

import type { ReactNode } from "react";
import type React from "react";
import { Box, Text } from "ink";
import { Header } from "./Header.js";
import { Footer } from "./Footer.js";
import { THEME_COLOR } from "../constants.js";

/**
 * Props for the Shell component.
 */
interface ShellProps {
  /** Content to render in the main area */
  children: ReactNode;
  /** Current status message for the footer */
  status: string;
  /** Current step in the setup flow */
  step: string;
}

/** Ordered list of setup steps for the stepper display */
const SETUP_STEPS = [
  "Welcome",
  "Prerequisites",
  "Repository Setup",
  "Environment Setup",
  "Finished",
] as const;

/**
 * Props for the Stepper component.
 */
interface StepperProps {
  /** Name of the currently active step */
  currentStep: string;
}

/**
 * Stepper component showing progress through setup steps.
 * Displays checkmarks for completed steps and highlights the current step.
 * @param props - Stepper properties
 * @param props.currentStep - The currently active step name
 */
const Stepper: React.FC<StepperProps> = ({ currentStep }) => {
  const currentIndex = SETUP_STEPS.indexOf(
    currentStep as (typeof SETUP_STEPS)[number]
  );

  return (
    <Box marginBottom={1}>
      {SETUP_STEPS.map((step, index) => {
        const isActive = step === currentStep;
        const isDone = currentIndex > index;

        return (
          <Box key={step} marginRight={2}>
            <Text color={isActive ? THEME_COLOR : isDone ? "green" : "gray"}>
              {isDone ? "✔ " : isActive ? "● " : "○ "}
              {step}
            </Text>
            {index < SETUP_STEPS.length - 1 && <Text color="gray"> › </Text>}
          </Box>
        );
      })}
    </Box>
  );
};

/**
 * Main shell component that wraps the entire CLI interface.
 * Provides header, stepper, content area, and footer.
 * @param props - Shell properties
 * @param props.children - Main content to render
 * @param props.status - Status message for footer
 * @param props.step - Current step for stepper
 */
export const Shell: React.FC<ShellProps> = ({ children, status, step }) => {
  return (
    <Box flexDirection="column" height="100%" width="100%">
      <Box flexGrow={1} flexDirection="column">
        <Header />
        <Stepper currentStep={step} />
        <Box flexDirection="column" flexGrow={1}>
          {children}
        </Box>
      </Box>
      <Footer status={status} step={step} />
    </Box>
  );
};
