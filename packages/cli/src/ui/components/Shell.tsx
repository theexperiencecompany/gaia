import { Box, Text } from "ink";
import type React from "react";
import type { ReactNode } from "react";
import { MARK, THEME_COLOR } from "../constants.js";
import { Footer } from "./Footer.js";
import { Header } from "./Header.js";

/** One stepper entry: the flow's step id and the word the bar shows for it. */
interface StepDef {
  id: string;
  label: string;
}

const INIT_STEPS: readonly StepDef[] = [
  { id: "Welcome", label: "Welcome" },
  { id: "Prerequisites", label: "Prereqs" },
  { id: "Setup Mode", label: "Mode" },
  { id: "Repository Setup", label: "Repo" },
  { id: "Environment Setup", label: "Env" },
  { id: "Install Tools", label: "Tools" },
  { id: "Project Setup", label: "Setup" },
  { id: "Finished", label: "Done" },
];

export const SETUP_STEPS: readonly StepDef[] = [
  { id: "Detect Repo", label: "Detect" },
  { id: "Prerequisites", label: "Prereqs" },
  { id: "Environment Setup", label: "Env" },
  { id: "Project Setup", label: "Setup" },
  { id: "Finished", label: "Done" },
];

interface ShellProps {
  children: ReactNode;
  status: string;
  step: string;
  steps?: readonly StepDef[];
}

const Stepper: React.FC<{ currentStep: string; steps: readonly StepDef[] }> = ({
  currentStep,
  steps,
}) => {
  const currentIndex = steps.findIndex((s) => s.id === currentStep);
  // Reaching the last step finishes it: "Done" is ticked, not pending.
  const finished = currentIndex === steps.length - 1;

  return (
    <Box marginBottom={1} flexWrap="wrap">
      {steps.map(({ id, label }, i) => {
        const isDone = i < currentIndex || finished;
        const isActive = i === currentIndex && !finished;

        return (
          <Box key={id} flexShrink={0}>
            {i > 0 && <Text color="gray"> · </Text>}
            {isDone && (
              <Text color="green">
                {MARK.ok} {label}
              </Text>
            )}
            {isActive && (
              <Text color={THEME_COLOR} bold>
                {label}
              </Text>
            )}
            {!isDone && !isActive && <Text color="gray">{label}</Text>}
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
