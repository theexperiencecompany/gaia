/**
 * Ink screen for `gaia up`: one column under one header (the installer's,
 * when it ran this), each finished step one line, the one step running now
 * with the lines of what it works through, the one prompt it may ask, and a
 * single card once GAIA is ready. Steps still to come stay hidden.
 * @module commands/up/screen
 */

import { Box, Static, Text } from "ink";
import type React from "react";
import { useState } from "react";
import { resumedStep } from "../../lib/docker-group.js";
import { MISSING_PREREQUISITES_KEY } from "../../lib/prerequisite-install.js";
import type { RunStep } from "../../lib/run-steps.js";
import { releaseSourceNotes } from "../../lib/selfhost-bundle.js";
import { CLI_VERSION } from "../../lib/version.js";
import { Header } from "../../ui/components/Header.js";
import { Mark } from "../../ui/components/Mark.js";
import { ResultCard } from "../../ui/components/ResultCard.js";
import {
  ActiveStep,
  FinishedStep,
  splitFinished,
} from "../../ui/components/StepList.js";
import {
  ErrorStep,
  InstallConfirmStep,
} from "../../ui/components/shared-steps.js";
import { THEME_COLOR } from "../../ui/constants.js";
import type { CLIState, CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import { UP_NOTICE_KEY } from "./flow.js";
import { buildUpSummary, NEXT_COMMANDS } from "./summary.js";
import type { UpOutcome } from "./summary.types.js";

/** What the screen writes once, above the live frame: the header and notes, then each finished step. */
type WrittenItem =
  | { kind: "header" }
  | { kind: "note"; text: string }
  | { kind: "step"; step: RunStep };
const HEADER_ITEM: WrittenItem = { kind: "header" };

/** Set by install.sh when it hands its screen to `gaia up`: its header is already on it. */
const CONTINUES_INSTALLER_ENV = "GAIA_CONTINUES_INSTALLER";

/** The run's lines sit two columns in, under the installer's own. */
const INDENT = 2;

const COMMAND_WIDTH = 14;
const COMMAND_COLUMN_WIDTH = 30;

const SummaryCard: React.FC<{ outcome: UpOutcome }> = ({ outcome }) => {
  const summary = buildUpSummary(outcome);
  const accent = summary.tone === "success" ? "green" : THEME_COLOR;
  return (
    <Box flexDirection="column" marginTop={1}>
      <ResultCard
        headline={summary.headline}
        rows={summary.rows}
        accent={accent}
        success={summary.tone === "success"}
      />
      <Box
        flexDirection="row"
        flexWrap="wrap"
        marginTop={1}
        paddingX={2}
        width={COMMAND_COLUMN_WIDTH * 2 + 4}
      >
        {NEXT_COMMANDS.map(([command, purpose]) => (
          <Box key={command} width={COMMAND_COLUMN_WIDTH}>
            <Box width={COMMAND_WIDTH}>
              <Text color={THEME_COLOR}>{command}</Text>
            </Box>
            <Text color="gray">{purpose}</Text>
          </Box>
        ))}
      </Box>
    </Box>
  );
};

/** The install prompt, the only input gaia up asks for: a taken port is moved, never asked about. */
const UpPrompt: React.FC<{ state: CLIState; store: CLIStore }> = ({
  state,
  store,
}) => {
  return (
    <InstallConfirmStep
      inputId={state.inputRequest?.id}
      missing={state.data[MISSING_PREREQUISITES_KEY]}
      onConfirm={() => store.submitInput("install")}
      onDecline={() => store.submitInput("decline")}
    />
  );
};

/** A line in the step list that is not a step: a release from somewhere else, a declined install. */
const NoticeRow: React.FC<{ text: string }> = ({ text }) => (
  <Box>
    <Mark kind="warn" />
    <Text>{text}</Text>
  </Box>
);

/** The lines written once at the top: the header, unless an earlier process already drew one, and the release notes. */
function openingItems(): WrittenItem[] {
  // A docker-group relaunch continues its parent's screen, header and notes included.
  if (resumedStep()) return [];
  const notes = releaseSourceNotes(process.env, CLI_VERSION).map(
    (text): WrittenItem => ({ kind: "note", text }),
  );
  return process.env[CONTINUES_INSTALLER_ENV] === "1"
    ? notes
    : [HEADER_ITEM, ...notes];
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

export const UpScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const steps = (state.data.steps ?? []) as RunStep[];
  const outcome = state.data.upOutcome as UpOutcome | undefined;
  const notice = state.data[UP_NOTICE_KEY] as string | undefined;
  const finished = state.data.finished === true && outcome !== undefined;
  const { finished: finishedSteps, live } = splitFinished(steps);
  const current = live.find((step) => step.state !== "pending");
  const [opening] = useState(openingItems);
  const written: WrittenItem[] = [
    ...opening,
    ...finishedSteps.map((step) => ({ kind: "step" as const, step })),
  ];

  return (
    <Box flexDirection="column" width="100%">
      <Static items={written}>
        {(item) => (
          <Box key={writtenKey(item)} paddingLeft={INDENT}>
            <WrittenRow item={item} />
          </Box>
        )}
      </Static>
      <Box flexDirection="column" paddingLeft={INDENT}>
        {current && (
          <ActiveStep
            step={current}
            waiting={state.inputRequest !== null}
            status={state.status}
          />
        )}
        <UpPrompt state={state} store={store} />
        {notice && (
          <Box marginTop={1}>
            <NoticeRow text={notice} />
          </Box>
        )}
      </Box>
      {finished && <SummaryCard outcome={outcome} />}
      {state.error && <ErrorStep message={state.error.message} />}
    </Box>
  );
};
