/**
 * The screen every command that does work draws: one column under one
 * header, each finished step one line, the one step running now with the
 * lines of what it works through, the command's own prompt or card, then the
 * ending. Steps still to come stay hidden.
 * @module ui/components/RunScreen
 */

import { Box, Static, Text } from "ink";
import type React from "react";
import type { ReactNode } from "react";
import { useState } from "react";
import { readEnding } from "../../lib/command-ending.js";
import { resumedStep } from "../../lib/docker-group.js";
import type { RunStep } from "../../lib/run-steps.js";
import { SCREEN_INDENT } from "../constants.js";
import type { CLIStore } from "../store.js";
import { useCLIState } from "../use-cli-state.js";
import { Ending } from "./Ending.js";
import { Header } from "./Header.js";
import { Mark } from "./Mark.js";
import { ActiveStep, FinishedStep, splitFinished } from "./StepList.js";
import { ErrorStep } from "./shared-steps.js";

/** What the screen writes once, above the live frame: the header and notes, then each finished step. */
type WrittenItem =
  | { kind: "header" }
  | { kind: "note"; text: string }
  | { kind: "step"; step: RunStep };

/** Set by install.sh when it hands its screen to `gaia up`: its header is already on it. */
const CONTINUES_INSTALLER_ENV = "GAIA_CONTINUES_INSTALLER";

/** A line in the step list that is not a step: a release from somewhere else, a declined install. */
export const NoticeRow: React.FC<{ text: string }> = ({ text }) => (
  <Box>
    <Mark kind="warn" />
    <Text>{text}</Text>
  </Box>
);

/** The header, unless an earlier process (the installer, a docker-group relaunch) already drew it, then the notes. */
function openingItems(notes: readonly string[]): WrittenItem[] {
  if (resumedStep()) return [];
  const written = notes.map((text): WrittenItem => ({ kind: "note", text }));
  return process.env[CONTINUES_INSTALLER_ENV] === "1"
    ? written
    : [{ kind: "header" }, ...written];
}

function writtenKey(item: WrittenItem): string {
  if (item.kind === "step") return item.step.id;
  return item.kind === "note" ? item.text : "header";
}

const WrittenRow: React.FC<{ item: WrittenItem }> = ({ item }) => {
  if (item.kind === "step") return <FinishedStep step={item.step} />;
  if (item.kind === "note") return <NoticeRow text={item.text} />;
  return (
    <Box marginBottom={1}>
      <Header showStatus={false} showUpdate={false} />
    </Box>
  );
};

export const RunScreen: React.FC<{
  store: CLIStore;
  /** Warning lines written once under the header. */
  notes?: readonly string[];
  /** The command's prompt, under the running step. */
  children?: ReactNode;
  /** The command's result card, before the ending. */
  result?: ReactNode;
}> = ({ store, notes = [], children, result }) => {
  const state = useCLIState(store);
  const steps = state.data.steps ?? [];
  const { finished, live } = splitFinished(steps);
  const current = live.find((step) => step.state !== "pending");
  const [opening] = useState(() => openingItems(notes));
  const ending = readEnding(store);
  const written: WrittenItem[] = [
    ...opening,
    ...finished.map((step) => ({ kind: "step" as const, step })),
  ];

  return (
    <Box flexDirection="column" width="100%">
      <Static items={written}>
        {(item) => (
          <Box key={writtenKey(item)} paddingLeft={SCREEN_INDENT}>
            <WrittenRow item={item} />
          </Box>
        )}
      </Static>
      <Box flexDirection="column" paddingLeft={SCREEN_INDENT}>
        {current && (
          <ActiveStep
            step={current}
            waiting={state.inputRequest !== null}
            status={state.status}
          />
        )}
        {children}
      </Box>
      <Box flexDirection="column" paddingLeft={SCREEN_INDENT}>
        {result}
        {ending && !state.error && <Ending ending={ending} />}
        {state.error && <ErrorStep message={state.error.message} />}
      </Box>
    </Box>
  );
};
