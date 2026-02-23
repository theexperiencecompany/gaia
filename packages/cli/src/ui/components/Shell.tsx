import { Box, Text } from "ink";
import type React from "react";
import type { ReactNode } from "react";
import { THEME_COLOR } from "../constants.js";
import { Footer } from "./Footer.js";
import { Header } from "./Header.js";

export const INIT_STEPS = [
  "Welcome",
  "Prerequisites",
  "Setup Mode",
  "Repository Setup",
  "Environment Setup",
  "Install Tools",
  "Project Setup",
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

const STEP_LABELS: Record<string, string> = {
  Welcome: "Welcome",
  Prerequisites: "Prereqs",
  "Setup Mode": "Mode",
  "Repository Setup": "Repo",
  "Environment Setup": "Env",
  "Install Tools": "Tools",
  "Project Setup": "Setup",
  "Detect Repo": "Detect",
  Finished: "Done",
};

const Stepper: React.FC<StepperProps> = ({ currentStep, steps }) => {
  const currentIndex = steps.indexOf(currentStep);

  return (
    <Box marginBottom={1} flexWrap="nowrap">
      {steps.map((step, i) => {
        const isDone = i < currentIndex;
        const isActive = i === currentIndex;
        const label = STEP_LABELS[step] ?? step;

        return (
          <Box key={step} flexShrink={0}>
            {i > 0 && (
              <Text color="gray" dimColor>
                {" "}
                ·{" "}
              </Text>
            )}
            {isDone && <Text color="green">✓ {label}</Text>}
            {isActive && (
              <Text color={THEME_COLOR} bold>
                {label}
              </Text>
            )}
            {!isDone && !isActive && (
              <Text color="gray" dimColor>
                {label}
              </Text>
            )}
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
