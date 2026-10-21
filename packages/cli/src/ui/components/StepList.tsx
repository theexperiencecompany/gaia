import { Spinner } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import {
  progressCaption,
  progressPercent,
  stallNote,
} from "../../lib/progress.js";
import { formatElapsed, type RunStep } from "../../lib/run-steps.js";
import type { RunSubstep } from "../../lib/run-steps.types.js";
import {
  LABEL_GAP,
  LABEL_WIDTH,
  labelCell,
  TIME_WIDTH,
} from "../../lib/step-row.js";
import { Mark } from "./Mark.js";
import { PercentBar } from "./PercentBar.js";

/** A line under a step starts under its label, two columns in. */
const SUBSTEP_INDENT = 2;
/** A line under a step, after its mark: its label and a note ending where the row's time does. */
const SUBSTEP_WIDTH = LABEL_WIDTH + TIME_WIDTH - SUBSTEP_INDENT;
const TICK_MS = 1000;
/** A housekeeping step done faster than this is not worth a line of its own. */
const FOLD_MS = 2000;

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

/** Whether a finished step gets its own line: not when skipped, nor a quick housekeeping one. */
function isListed(step: RunStep): boolean {
  if (step.state === "skipped") return false;
  if (!step.minor || step.warnings?.length) return true;
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

/** One row: its mark, its label, and its time right-aligned in the time column. */
const StepRow: React.FC<{
  mark: React.ReactNode;
  label: string;
  bold?: boolean;
  time: string;
}> = ({ mark, label, bold = false, time }) => (
  <Box>
    {mark}
    <Text bold={bold}>{labelCell(label)}</Text>
    <Text dimColor>{time.padStart(TIME_WIDTH)}</Text>
  </Box>
);

/** A finished step, one line: "✓ Docker installed          2m 10s". */
export const FinishedStep: React.FC<{ step: RunStep }> = ({ step }) => (
  <Box flexDirection="column">
    <StepRow
      mark={<Mark kind="ok" />}
      label={step.doneLabel}
      time={elapsed(step, Date.now())}
    />
    {step.warnings?.map((warning) => (
      <Box key={warning} paddingLeft={SUBSTEP_INDENT}>
        <Mark kind="warn" />
        <Text>{warning}</Text>
      </Box>
    ))}
  </Box>
);

/** A step that ended badly: failed in red, or cancelled with Ctrl-C. */
const EndedStep: React.FC<{ step: RunStep }> = ({ step }) => (
  <StepRow
    mark={<Mark kind={step.state === "failed" ? "fail" : "cancelled"} />}
    label={step.label}
    time={elapsed(step, Date.now())}
  />
);

const SpinnerMark: React.FC = () => (
  <Box marginRight={1}>
    <Spinner />
  </Box>
);

/** Where a line under a step stands: running, done, failed, or (blank) still to come. */
const SubstepMark: React.FC<{ state: RunSubstep["state"] }> = ({ state }) => {
  if (state === "active") return <SpinnerMark />;
  if (state === "done") return <Mark kind="ok" />;
  if (state === "failed") return <Mark kind="fail" />;
  return <Box width={2} />;
};

/** The running line's own clock: how long it has been on this stage. */
function substepClock(substep: RunSubstep, now: number): string | undefined {
  if (substep.state !== "active" || substep.startedAt === undefined) {
    return undefined;
  }
  return formatElapsed(now - substep.startedAt);
}

/**
 * One line under a running step: its mark, its label, then its note and its
 * clock ending at the row's right edge. A long note is cut, never the clock.
 */
const SubstepRow: React.FC<{ substep: RunSubstep; now: number }> = ({
  substep,
  now,
}) => {
  const quiet = substep.state !== "active";
  const clock = substepClock(substep, now);
  return (
    <Box>
      <SubstepMark state={substep.state} />
      <Box width={SUBSTEP_WIDTH}>
        <Box flexGrow={1} flexShrink={0}>
          <Text dimColor={quiet}>{substep.label}</Text>
        </Box>
        {substep.note && (
          <Box flexShrink={1} marginLeft={LABEL_GAP}>
            <Text dimColor wrap="truncate">
              {substep.note}
            </Text>
          </Box>
        )}
        {clock && (
          <Box flexShrink={0} marginLeft={substep.note ? 0 : LABEL_GAP}>
            <Text dimColor>{substep.note ? ` · ${clock}` : clock}</Text>
          </Box>
        )}
      </Box>
    </Box>
  );
};

/**
 * The one step running now: its name in bold with a spinner and its timer,
 * and underneath its bar (with the amount and time left), its lines (the
 * stages, images or services it works through), or one plain line. While a
 * question is on screen it stops spinning and its clock stops.
 */
export const ActiveStep: React.FC<{
  step: RunStep;
  /** True while the run waits on the user. */
  waiting: boolean;
  /** Shown under the step when it has no detail of its own. */
  status: string;
}> = ({ step, waiting, status }) => {
  const now = useNow(!waiting);
  if (step.state === "failed" || step.state === "cancelled") {
    return <EndedStep step={step} />;
  }
  const substeps = step.substeps ?? [];
  const stall = step.amount ? stallNote(step.amountMovedAt, now) : null;
  const detail =
    substeps.length > 0 ? undefined : (step.detail ?? (status || undefined));
  return (
    <Box flexDirection="column">
      <StepRow
        mark={waiting ? <Mark kind="pending" /> : <SpinnerMark />}
        label={step.label}
        bold
        time={waiting ? "" : elapsed(step, now)}
      />
      <Box flexDirection="column" marginLeft={SUBSTEP_INDENT}>
        {step.amount && (
          <Box marginLeft={2}>
            <PercentBar
              percent={progressPercent(step.amount, step.percent)}
              caption={progressCaption(step.amount, {
                percent: step.percent,
                // A stalled transfer's last estimate is stale.
                etaMs: stall ? null : step.etaMs,
              })}
            />
          </Box>
        )}
        {stall && (
          <Box marginLeft={2}>
            <Text dimColor>{stall}</Text>
          </Box>
        )}
        {substeps.map((substep) => (
          <SubstepRow key={substep.id} substep={substep} now={now} />
        ))}
        {detail && (
          <Box marginLeft={2}>
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
    </Box>
  );
};
