/**
 * Ink screen for `gaia up`: the step list (each row with its own timer), the
 * one prompt it may ask, and a single card once GAIA is ready.
 * @module commands/up/screen
 */

import { Box, Text } from "ink";
import type React from "react";
import { MISSING_PREREQUISITES_KEY } from "../../lib/prerequisite-install.js";
import type { RunStep } from "../../lib/run-steps.js";
import { Header } from "../../ui/components/Header.js";
import { StepList } from "../../ui/components/StepList.js";
import {
  ErrorStep,
  InstallConfirmStep,
  PortConflictStep,
} from "../../ui/components/shared-steps.js";
import { BOX_BORDER, MARK, THEME_COLOR } from "../../ui/constants.js";
import type { CLIState, CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import {
  buildUpSummary,
  NEXT_COMMANDS,
  type SummaryRow,
  type UpOutcome,
} from "./summary.js";

const ROW_LABEL_WIDTH = 16;
const COMMAND_WIDTH = 14;
const COMMAND_COLUMN_WIDTH = 30;

const ROW_COLOR: Record<NonNullable<SummaryRow["tone"]>, string | undefined> = {
  primary: undefined,
  warn: "yellow",
  dim: "gray",
};

/** A row's text, with its URL bold, underlined and cyan. */
const RowText: React.FC<{ row: SummaryRow }> = ({ row }) => {
  const color = row.tone ? ROW_COLOR[row.tone] : undefined;
  if (!row.url) return <Text color={color}>{row.text}</Text>;
  const [before, after] = row.text.split(row.url);
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
  return (
    <Box flexDirection="column" marginTop={1}>
      <Box
        flexDirection="column"
        borderStyle={BOX_BORDER}
        borderColor={accent}
        paddingX={2}
        paddingY={1}
      >
        <Text bold color={accent}>
          {summary.tone === "success" ? `${MARK.ok} ` : ""}
          {summary.headline}
        </Text>
        <Box flexDirection="column" marginTop={1}>
          {summary.rows.map((row) => (
            <Box key={row.label}>
              <Box width={ROW_LABEL_WIDTH} flexShrink={0}>
                <Text bold={row.tone === "primary"}>{row.label}</Text>
              </Box>
              <RowText row={row} />
            </Box>
          ))}
        </Box>
      </Box>
      <Box flexDirection="row" flexWrap="wrap" marginTop={1} paddingX={2}>
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

export const UpScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const steps = (state.data.steps ?? []) as RunStep[];
  const outcome = state.data.upOutcome as UpOutcome | undefined;
  const logPath = state.data.logPath as string | undefined;
  const finished = state.data.finished === true && outcome !== undefined;

  return (
    <Box flexDirection="column" width="100%">
      <Header
        size="large"
        showStatus={finished && !outcome.noStart && !outcome.stillStarting}
      />
      <StepList
        steps={steps}
        waiting={state.inputRequest !== null}
        status={state.status}
      />
      <UpPrompt state={state} store={store} />
      {logPath && !finished && (
        <Box marginTop={1} marginLeft={2}>
          <Text color="gray">Full log: {logPath}</Text>
        </Box>
      )}
      {finished && <SummaryCard outcome={outcome} />}
      {state.error && <ErrorStep message={state.error.message} />}
    </Box>
  );
};
