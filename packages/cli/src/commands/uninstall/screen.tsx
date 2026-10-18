/**
 * Ink screen for `gaia uninstall`: the questions, one at a time, then each
 * step as it runs, then a card saying what is left and how to remove the CLI.
 * @module commands/uninstall/screen
 */

import { ConfirmInput } from "@inkjs/ui";
import { Box, Static, Text } from "ink";
import type React from "react";
import { homeRelative } from "../../lib/paths.js";
import type { RunStep } from "../../lib/run-steps.js";
import { ResultCard } from "../../ui/components/ResultCard.js";
import {
  ActiveStep,
  FinishedStep,
  splitFinished,
} from "../../ui/components/StepList.js";
import { ErrorStep } from "../../ui/components/shared-steps.js";
import type { CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import {
  UNINSTALL_BACKUP_DIR,
  UNINSTALL_INPUTS,
  UNINSTALL_OUTCOME_KEY,
  type UninstallOutcome,
} from "./flow.js";
import { buildUninstallRows, UNINSTALL_HEADLINE } from "./summary.js";

const INDENT = 2;

/** What each question says, and whether Enter alone answers yes. */
function question(
  id: string,
  installDir: string | null,
): { text: string; detail: string; yesByDefault: boolean } | null {
  switch (id) {
    case UNINSTALL_INPUTS.confirm:
      return {
        text: "Remove GAIA from this computer?",
        detail: `Its containers, networks and images go${installDir ? `, and so does ${homeRelative(installDir)}` : ""}. You choose about your data next.`,
        yesByDefault: true,
      };
    case UNINSTALL_INPUTS.deleteData:
      return {
        text: "Delete your data too?",
        detail:
          "Accounts, chats, memories and files. This can't be undone. No keeps it, and 'gaia up' picks it back up.",
        yesByDefault: false,
      };
    case UNINSTALL_INPUTS.backup:
      return {
        text: `Back it up to ${homeRelative(UNINSTALL_BACKUP_DIR)} first?`,
        detail: "Runs 'gaia backup' while GAIA is still running.",
        yesByDefault: true,
      };
    default:
      return null;
  }
}

const Question: React.FC<{ store: CLIStore; id: string }> = ({ store, id }) => {
  const asked = question(id, store.currentState.data.installDir ?? null);
  if (!asked) return null;
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text dimColor>{asked.detail}</Text>
      <Box>
        <Text bold>{asked.text} </Text>
        <ConfirmInput
          // Remount per question, so each starts from its own default.
          key={id}
          defaultChoice={asked.yesByDefault ? "confirm" : "cancel"}
          onConfirm={() => store.submitInput(true)}
          onCancel={() => store.submitInput(false)}
        />
      </Box>
    </Box>
  );
};

export const UninstallScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const steps = (state.data.steps ?? []) as RunStep[];
  const outcome = state.data[UNINSTALL_OUTCOME_KEY] as
    | UninstallOutcome
    | undefined;
  const { finished, live } = splitFinished(steps);
  const current = live.find((step) => step.state !== "pending");

  return (
    <Box flexDirection="column" width="100%">
      <Static items={finished}>
        {(step) => (
          <Box key={step.id} paddingLeft={INDENT}>
            <FinishedStep step={step} />
          </Box>
        )}
      </Static>
      <Box flexDirection="column" paddingLeft={INDENT}>
        {state.inputRequest && (
          <Question store={store} id={state.inputRequest.id} />
        )}
        {current && (
          <ActiveStep step={current} waiting={false} status={state.status} />
        )}
        {state.data.cancelled === true && (
          <Box marginTop={1}>
            <Text>{state.status}</Text>
          </Box>
        )}
      </Box>
      {outcome && (
        <Box marginTop={1}>
          <ResultCard
            headline={UNINSTALL_HEADLINE}
            rows={buildUninstallRows(outcome)}
            accent="green"
            success
          />
        </Box>
      )}
      {state.error && <ErrorStep message={state.error.message} />}
    </Box>
  );
};
