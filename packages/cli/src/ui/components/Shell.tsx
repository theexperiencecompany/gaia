import type { ReactNode } from "react";
import type React from "react";
import { Box, Text } from "ink";
import { Header } from "./Header.js";
import { Footer } from "./Footer.js";
import { THEME_COLOR } from "../constants.js";

export const INIT_STEPS = [
  "Welcome",
  "Prerequisites",
  "Repository Setup",
  "Environment Setup",
  "Finished",
] as const;

export const SETUP_STEPS = [
  "Detect Repo",
  "Prerequisites",
  "Environment Setup",
  "Project Setup",
  "Finished",
] as const;

interface ShellProps {
  children: ReactNode;
  status: string;
  step: string;
  steps?: readonly string[];
}

interface StepperProps {
  currentStep: string;
  steps: readonly string[];
}

const Stepper: React.FC<StepperProps> = ({ currentStep, steps }) => {
  const currentIndex = steps.indexOf(currentStep);

  return (
    <Box marginBottom={1}>
      {steps.map((step, index) => {
        const isActive = step === currentStep;
        const isDone = currentIndex > index;

        return (
          <Box key={step} marginRight={2}>
            <Text color={isActive ? THEME_COLOR : isDone ? "green" : "gray"}>
              {isDone ? "✓ " : isActive ? "● " : "○ "}
              {step}
            </Text>
            {index < steps.length - 1 && <Text color="gray"> › </Text>}
          </Box>
        );
      })}
    </Box>
  );
};

export const Shell: React.FC<ShellProps> = ({
  children,
  status,
  step,
  steps = INIT_STEPS,
}) => {
  return (
    <Box flexDirection="column" height="100%" width="100%">
      <Box flexGrow={1} flexDirection="column">
        <Header />
        <Stepper currentStep={step} steps={steps} />
        <Box flexDirection="column" flexGrow={1}>
          {children}
        </Box>
      </Box>
      <Footer status={status} step={step} />
    </Box>
  );
};
