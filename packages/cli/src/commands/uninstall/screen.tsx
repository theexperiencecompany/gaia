/**
 * Ink screen for `gaia uninstall`: the questions, one at a time, then each
 * step as it runs, then a card saying what is left and how to remove the CLI.
 * @module commands/uninstall/screen
 */

import { ConfirmInput } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { homeRelative } from "../../lib/paths.js";
import { ResultCard } from "../../ui/components/ResultCard.js";
import { RunScreen } from "../../ui/components/RunScreen.js";
import type { CLIStore } from "../../ui/store.js";
import type { InputId } from "../../ui/store.types.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import {
  UNINSTALL_BACKUP_DIR,
  UNINSTALL_INPUTS,
  UNINSTALL_OUTCOME_KEY,
  type UninstallInputId,
} from "./flow.js";
import { buildUninstallRows, UNINSTALL_HEADLINE } from "./summary.js";

const UNINSTALL_INPUT_IDS: readonly InputId[] = Object.values(UNINSTALL_INPUTS);

function isUninstallInput(id: InputId): id is UninstallInputId {
  return UNINSTALL_INPUT_IDS.includes(id);
}

/** What each question says, and whether Enter alone answers yes. */
function question(
  id: UninstallInputId,
  installDir: string | null,
): { text: string; detail: string; yesByDefault: boolean } {
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
  }
}

const Question: React.FC<{ store: CLIStore; id: UninstallInputId }> = ({
  store,
  id,
}) => {
  const asked = question(id, store.currentState.data.installDir ?? null);
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text dimColor>{asked.detail}</Text>
      <Box>
        <Text bold>{asked.text} </Text>
        <ConfirmInput
          // Remount per question, so each starts from its own default.
          key={id}
          defaultChoice={asked.yesByDefault ? "confirm" : "cancel"}
          onConfirm={() => store.submitInput(id, true)}
          onCancel={() => store.submitInput(id, false)}
        />
      </Box>
    </Box>
  );
};

export const UninstallScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const outcome = state.data[UNINSTALL_OUTCOME_KEY];

  return (
    <RunScreen
      store={store}
      result={
        outcome && (
          <Box marginTop={1}>
            <ResultCard
              headline={UNINSTALL_HEADLINE}
              rows={buildUninstallRows(outcome)}
              accent="green"
              success
            />
          </Box>
        )
      }
    >
      {state.inputRequest && isUninstallInput(state.inputRequest.id) && (
        <Question store={store} id={state.inputRequest.id} />
      )}
      {state.data.cancelled === true && (
        <Box marginTop={1}>
          <Text>{state.status}</Text>
        </Box>
      )}
    </RunScreen>
  );
};
