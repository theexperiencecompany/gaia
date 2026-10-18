/**
 * Ink screen for `gaia up`: a one-line header, each finished step collapsed
 * to one dim line, the one step running now with its bar and a plain line
 * under it, the one prompt it may ask, and a single card once GAIA is ready.
 * Steps still to come stay hidden behind the running step's "step n of N".
 * @module commands/up/screen
 */

import { StatusMessage } from "@inkjs/ui";
import { Box, Static, Text } from "ink";
import type React from "react";
import { resumedStep } from "../../lib/docker-group.js";
import { homeRelative } from "../../lib/paths.js";
import { MISSING_PREREQUISITES_KEY } from "../../lib/prerequisite-install.js";
import type { RunStep } from "../../lib/run-steps.js";
import { releaseSourceNotes } from "../../lib/selfhost-bundle.js";
import { wrapToWidth } from "../../lib/terminal-text.js";
import { CLI_VERSION } from "../../lib/version.js";
import {
  ActiveStep,
  FinishedStep,
  splitFinished,
  stepCounter,
} from "../../ui/components/StepList.js";
import {
  ErrorStep,
  InstallConfirmStep,
  PortConflictStep,
} from "../../ui/components/shared-steps.js";
import { useCardWidth } from "../../ui/components/use-card-width.js";
import { BOX_BORDER, MARK, THEME_COLOR } from "../../ui/constants.js";
import type { CLIState, CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import { UP_NOTICE_KEY } from "./flow.js";
import {
  buildUpSummary,
  NEXT_COMMANDS,
  type SummaryRow,
  type UpOutcome,
} from "./summary.js";

/** What the screen writes once, above the live frame: the header, then each finished step. */
type WrittenItem = { kind: "header" } | { kind: "step"; step: RunStep };
const HEADER_ITEM: WrittenItem = { kind: "header" };

/** The run's lines sit two columns in, under the installer's own. */
const INDENT = 2;

const ROW_LABEL_WIDTH = 16;
/** Columns the card's border (1 each side) and paddingX (2 each side) take. */
const CARD_FRAME_WIDTH = 6;
const COMMAND_WIDTH = 14;
const COMMAND_COLUMN_WIDTH = 30;

const ROW_COLOR: Record<NonNullable<SummaryRow["tone"]>, string | undefined> = {
  primary: undefined,
  warn: "yellow",
  dim: "gray",
};

/** A row's text wrapped to its column, with its URL bold, underlined and cyan. */
const RowText: React.FC<{ row: SummaryRow; width: number }> = ({
  row,
  width,
}) => {
  const color = row.tone ? ROW_COLOR[row.tone] : undefined;
  const text = wrapToWidth(row.text, width);
  if (!row.url) return <Text color={color}>{text}</Text>;
  const [before, after] = text.split(row.url);
  return (
    <Text color={color}>
      {before}
      <Text color="cyan" bold underline>
        {row.url}
      </Text>
      {after}
    </Text>
  );
};

const SummaryCard: React.FC<{ outcome: UpOutcome }> = ({ outcome }) => {
  const summary = buildUpSummary(outcome);
  const accent = summary.tone === "success" ? "green" : THEME_COLOR;
  const width = useCardWidth();
  return (
    <Box flexDirection="column" marginTop={1}>
      <Box
        flexDirection="column"
        borderStyle={BOX_BORDER}
        borderColor={accent}
        paddingX={2}
        paddingY={1}
        width={width}
      >
        <Text bold color={accent}>
          {summary.tone === "success" ? `${MARK.ok} ` : ""}
          {summary.headline}
        </Text>
        <Box flexDirection="column" marginTop={1}>
          {summary.rows.map((row) => (
            <Box key={row.label} marginBottom={row.tone === "primary" ? 1 : 0}>
              <Box width={ROW_LABEL_WIDTH} flexShrink={0}>
                <Text bold={row.tone === "primary"}>{row.label}</Text>
              </Box>
              <RowText
                row={row}
                width={width - CARD_FRAME_WIDTH - ROW_LABEL_WIDTH}
              />
            </Box>
          ))}
        </Box>
      </Box>
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

/** The install and port-conflict prompts, the only input gaia up asks for. */
const UpPrompt: React.FC<{ state: CLIState; store: CLIStore }> = ({
  state,
  store,
}) => {
  if (state.inputRequest?.id === "port_conflicts") {
    return state.data.portConflicts ? (
      <PortConflictStep
        portResults={state.data.portConflicts}
        onAccept={() => store.submitInput("accept")}
        onAbort={() => store.submitInput("abort")}
      />
    ) : null;
  }
  return (
    <InstallConfirmStep
      inputId={state.inputRequest?.id}
      missing={state.data[MISSING_PREREQUISITES_KEY]}
      onConfirm={() => store.submitInput("install")}
      onDecline={() => store.submitInput("decline")}
    />
  );
};

/**
 * "GAIA v0.7.0 · setting up": the logo is for --version and status, not a
 * run. A run whose release comes from somewhere else says so under it.
 */
const UpHeader: React.FC = () => (
  <Box flexDirection="column" marginTop={1} marginBottom={1}>
    <Text>
      <Text bold>GAIA</Text>
      <Text dimColor>{` v${CLI_VERSION} · setting up`}</Text>
    </Text>
    {releaseSourceNotes(process.env, CLI_VERSION).map((note) => (
      <StatusMessage key={note} variant="warning">
        {note}
      </StatusMessage>
    ))}
  </Box>
);

export const UpScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const steps = (state.data.steps ?? []) as RunStep[];
  const outcome = state.data.upOutcome as UpOutcome | undefined;
  const logPath = state.data.logPath as string | undefined;
  const notice = state.data[UP_NOTICE_KEY] as string | undefined;
  const finished = state.data.finished === true && outcome !== undefined;
  const { finished: finishedSteps, live } = splitFinished(steps);
  const current = live.find((step) => step.state !== "pending");
  const written: WrittenItem[] = [
    // A docker-group relaunch continues its parent's screen, header included.
    ...(resumedStep() ? [] : [HEADER_ITEM]),
    ...finishedSteps.map((step) => ({ kind: "step" as const, step })),
  ];

  return (
    <Box flexDirection="column" width="100%">
      <Static items={written}>
        {(item) => (
          <Box
            key={item.kind === "header" ? "header" : item.step.id}
            paddingLeft={INDENT}
          >
            {item.kind === "header" ? (
              <UpHeader />
            ) : (
              <FinishedStep step={item.step} />
            )}
          </Box>
        )}
      </Static>
      <Box flexDirection="column" paddingLeft={INDENT}>
        {current && (
          <Box marginTop={finishedSteps.length > 0 ? 1 : 0}>
            <ActiveStep
              step={current}
              counter={stepCounter(steps, current)}
              waiting={state.inputRequest !== null}
              status={state.status}
            />
          </Box>
        )}
        <UpPrompt state={state} store={store} />
        {notice && (
          <Box marginTop={1}>
            <StatusMessage variant="warning">{notice}</StatusMessage>
          </Box>
        )}
        {logPath && !finished && !state.error && (
          <Box marginTop={1} marginLeft={2}>
            <Text dimColor>Full log: {homeRelative(logPath)}</Text>
          </Box>
        )}
      </Box>
      {finished && <SummaryCard outcome={outcome} />}
      {state.error && <ErrorStep message={state.error.message} />}
    </Box>
  );
};
