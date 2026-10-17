import { Spinner } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import { formatElapsed, type RunStep } from "../../lib/run-steps.js";

import { Mark } from "./Mark.js";
import { PercentBar } from "./PercentBar.js";

/** Label column width: the longest label plus room before the timer. */
const LABEL_WIDTH = 40;
const TICK_MS = 1000;

/** Re-render every second while something runs, so its timer moves. */
function useNow(running: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [running]);
  return now;
}

function elapsed(step: RunStep, now: number): string {
  if (step.startedAt === undefined) return "";
  return formatElapsed((step.endedAt ?? now) - step.startedAt);
}

const StepMark: React.FC<{ step: RunStep; waiting: boolean }> = ({
  step,
  waiting,
}) => {
  if (step.state === "done") return <Mark kind="ok" />;
  if (step.state === "failed") return <Mark kind="fail" />;
  if (step.state === "active" && !waiting) {
    return (
      <Box marginRight={1}>
        <Spinner />
      </Box>
    );
  }
  return <Mark kind="pending" />;
};

export const StepRow: React.FC<{
  step: RunStep;
  now: number;
  waiting: boolean;
  status: string;
}> = ({ step, now, waiting, status }) => {
  const running = step.state === "active";
  const label = step.state === "done" ? step.doneLabel : step.label;
  const detail = step.detail ?? (running ? status : undefined);
  return (
    <Box flexDirection="column">
      <Box>
        <StepMark step={step} waiting={waiting} />
        <Box width={LABEL_WIDTH}>
          <Text
            color={step.state === "pending" ? "gray" : undefined}
            bold={running}
          >
            {label}
          </Text>
        </Box>
        <Text color="gray">{elapsed(step, now)}</Text>
      </Box>
      {running && step.percent !== undefined && (
        <Box marginLeft={2}>
          <PercentBar percent={step.percent} />
        </Box>
      )}
      {running && detail && (
        <Box marginLeft={2}>
          <Text color="gray" wrap="truncate">
            {detail}
          </Text>
        </Box>
      )}
      {running && step.hint && (
        <Box marginLeft={2}>
          <Text color="gray" dimColor>
            {step.hint}
          </Text>
        </Box>
      )}
    </Box>
  );
};

/**
 * The leading run of finished steps, which never change again, and the rest.
 * Finished rows belong in Ink's Static output: a live frame as tall as the
 * terminal makes Ink clear the whole screen, scrollback included, on every redraw.
 */
export function splitFinished(steps: RunStep[]): {
  finished: RunStep[];
  live: RunStep[];
} {
  const firstLive = steps.findIndex((step) => step.state !== "done");
  const at = firstLive === -1 ? steps.length : firstLive;
  return { finished: steps.slice(0, at), live: steps.slice(at) };
}

/**
 * The run's steps, one row each: a mark (✓ done, ✗ failed, a spinner while it
 * runs, ○ waiting or not started), its label and its own timer. The running
 * row shows its progress, detail and hint underneath.
 */
export const StepList: React.FC<{
  steps: RunStep[];
  /** True while the run waits on the user: the running row stops spinning. */
  waiting: boolean;
  /** Shown under the running row when the step has no detail of its own. */
  status: string;
}> = ({ steps, waiting, status }) => {
  const now = useNow(steps.some((s) => s.state === "active"));
  return (
    <Box flexDirection="column">
      {steps.map((step) => (
        <StepRow
          key={step.id}
          step={step}
          now={now}
          waiting={waiting}
          status={status}
        />
      ))}
    </Box>
  );
};
