import { Spinner, StatusMessage } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import { progressCaption, progressPercent } from "../../lib/progress.js";
import { formatElapsed, type RunStep } from "../../lib/run-steps.js";
import { Mark } from "./Mark.js";
import { PercentBar } from "./PercentBar.js";

/** Label column width: room for the usual label and the gap before the timer. */
const LABEL_WIDTH = 32;
/** Spaces a label longer than the column still keeps before the timer. */
const LABEL_GAP = 2;
const TICK_MS = 1000;
/** A housekeeping step done faster than this is not worth a line of its own. */
const FOLD_MS = 2000;

/** Re-render every second while something runs, so its timer moves. */
export function useNow(running: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [running]);
  return now;
}

/** The label padded to the column, never closer to the timer than LABEL_GAP. */
function labelCell(label: string): string {
  return label.padEnd(Math.max(LABEL_WIDTH, label.length + LABEL_GAP));
}

function elapsed(step: RunStep, now: number): string {
  if (step.startedAt === undefined) return "";
  return formatElapsed((step.endedAt ?? now) - step.startedAt);
}

/** Whether a finished step gets its own line: not when skipped, nor a quick housekeeping one. */
function isListed(step: RunStep): boolean {
  if (step.state === "skipped") return false;
  if (!step.minor) return true;
  return elapsedMs(step) >= FOLD_MS;
}

function elapsedMs(step: RunStep): number {
  if (step.startedAt === undefined || step.endedAt === undefined) return 0;
  return step.endedAt - step.startedAt;
}

/**
 * The leading run of finished steps, which never change again, and the rest.
 * Finished rows belong in Ink's Static output: a live frame as tall as the
 * terminal makes Ink clear the whole screen, scrollback included, on every redraw.
 * Only the finished steps worth a line are returned.
 */
export function splitFinished(steps: RunStep[]): {
  finished: RunStep[];
  live: RunStep[];
} {
  const firstLive = steps.findIndex(
    (step) => step.state !== "done" && step.state !== "skipped",
  );
  const at = firstLive === -1 ? steps.length : firstLive;
  return {
    finished: steps.slice(0, at).filter(isListed),
    live: steps.slice(at),
  };
}

/** "step 2 of 4" for a real step; nothing for housekeeping between them. */
export function stepCounter(steps: RunStep[], step: RunStep): string | null {
  if (step.minor) return null;
  const counted = steps.filter((s) => !s.minor && s.state !== "skipped");
  const at = counted.findIndex((s) => s.id === step.id);
  return at === -1 ? null : `step ${at + 1} of ${counted.length}`;
}

/** A finished step, collapsed to one dim line: "✓ Docker installed   2m 10s". */
export const FinishedStep: React.FC<{ step: RunStep }> = ({ step }) => (
  <StatusMessage variant="success">
    <Text dimColor>
      {labelCell(step.doneLabel)}
      {elapsed(step, Date.now())}
    </Text>
  </StatusMessage>
);

/** A step that ended badly: failed in red, or cancelled with Ctrl-C. */
const EndedStep: React.FC<{ step: RunStep }> = ({ step }) => {
  const line = (
    <Text>
      {labelCell(step.label)}
      <Text dimColor>{elapsed(step, Date.now())}</Text>
    </Text>
  );
  if (step.state === "failed") {
    return <StatusMessage variant="error">{line}</StatusMessage>;
  }
  return (
    <Box>
      <Mark kind="cancelled" />
      {line}
    </Box>
  );
};

/**
 * The one step running now: its name in bold with a spinner, where it is in
 * the run, and underneath its bar (with the amount and time left) and one
 * plain line. While a question is on screen it stops spinning and its clock
 * stops.
 */
export const ActiveStep: React.FC<{
  step: RunStep;
  counter: string | null;
  /** True while the run waits on the user. */
  waiting: boolean;
  /** Shown under the step when it has no detail of its own. */
  status: string;
}> = ({ step, counter, waiting, status }) => {
  const now = useNow(!waiting);
  if (step.state === "failed" || step.state === "cancelled") {
    return <EndedStep step={step} />;
  }
  const detail = step.detail ?? (status || undefined);
  const meta = [counter, waiting ? null : elapsed(step, now)]
    .filter(Boolean)
    .join(" · ");
  return (
    <Box flexDirection="column">
      <Box>
        {waiting ? (
          <Mark kind="pending" />
        ) : (
          <Box marginRight={1}>
            <Spinner />
          </Box>
        )}
        <Text bold>{labelCell(step.label)}</Text>
        <Text dimColor>{meta}</Text>
      </Box>
      {step.amount && (
        <Box marginLeft={2} marginTop={1}>
          <PercentBar
            percent={progressPercent(step.amount, step.percent)}
            caption={progressCaption(step.amount, {
              percent: step.percent,
              etaMs: step.etaMs,
            })}
          />
        </Box>
      )}
      {detail && (
        <Box marginLeft={2} marginTop={step.amount ? 0 : 1}>
          <Text dimColor wrap="truncate">
            {detail}
          </Text>
        </Box>
      )}
      {step.hint && (
        <Box marginLeft={2}>
          <Text dimColor>{step.hint}</Text>
        </Box>
      )}
    </Box>
  );
};
