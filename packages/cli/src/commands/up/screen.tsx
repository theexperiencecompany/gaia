/**
 * Ink screen for `gaia up`: the shared run screen under one header (the
 * installer's, when it ran this), the one prompt it may ask, and a single
 * card once GAIA is ready.
 * @module commands/up/screen
 */

import { Box, Text } from "ink";
import type React from "react";
import { useState } from "react";
import { MISSING_PREREQUISITES_KEY } from "../../lib/prerequisite-install.js";
import { releaseSourceNotes } from "../../lib/selfhost-bundle.js";
import { CLI_VERSION } from "../../lib/version.js";
import { ResultCard } from "../../ui/components/ResultCard.js";
import { NoticeRow, RunScreen } from "../../ui/components/RunScreen.js";
import { InstallConfirmStep } from "../../ui/components/shared-steps.js";
import { THEME_COLOR } from "../../ui/constants.js";
import type { CLIState, CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import { UP_NOTICE_KEY } from "./flow.js";
import { buildUpSummary, NEXT_COMMANDS } from "./summary.js";
import type { UpOutcome } from "./summary.types.js";

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
        width={COMMAND_COLUMN_WIDTH * 2}
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

export const UpScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const outcome = state.data.upOutcome as UpOutcome | undefined;
  const notice = state.data[UP_NOTICE_KEY] as string | undefined;
  const finished = state.data.finished === true && outcome !== undefined;
  const [notes] = useState(() => releaseSourceNotes(process.env, CLI_VERSION));

  return (
    <RunScreen
      store={store}
      notes={notes}
      result={finished ? <SummaryCard outcome={outcome} /> : undefined}
    >
      <UpPrompt state={state} store={store} />
      {notice && (
        <Box marginTop={1}>
          <NoticeRow text={notice} />
        </Box>
      )}
    </RunScreen>
  );
};
