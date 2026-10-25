/**
 * Ink screen for `gaia bots add|remove`: the shared run screen with the one
 * credential prompt `add` may ask, gone once answered.
 * @module commands/bots/screen
 */

import { PasswordInput } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { wrapToWidth } from "../../lib/terminal-text.js";
import { Mark } from "../../ui/components/Mark.js";
import { RunScreen } from "../../ui/components/RunScreen.js";
import { useCardWidth } from "../../ui/components/use-card-width.js";
import type { CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import { BOT_CREDENTIAL_INPUT, type CredentialRequest } from "./prompt.js";

const CredentialPrompt: React.FC<{
  store: CLIStore;
  request: CredentialRequest;
}> = ({ store, request }) => {
  const width = useCardWidth();
  return (
    <Box flexDirection="column" marginTop={1}>
      {request.retry && (
        <Box>
          <Mark kind="fail" />
          <Text>{wrapToWidth(request.retry, width - 4)}</Text>
        </Box>
      )}
      {request.hint && <Text dimColor>{wrapToWidth(request.hint, width)}</Text>}
      <Box>
        <Text bold>{request.label}: </Text>
        <PasswordInput
          onSubmit={(value) =>
            store.submitInput(BOT_CREDENTIAL_INPUT, value.trim())
          }
        />
      </Box>
    </Box>
  );
};

export const BotsScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const request =
    state.inputRequest?.id === BOT_CREDENTIAL_INPUT
      ? state.inputRequest.meta
      : undefined;
  return (
    <RunScreen store={store}>
      {request && (
        // Remount per credential, so each starts empty.
        <CredentialPrompt
          key={`${request.label}:${request.retry ?? ""}`}
          store={store}
          request={request}
        />
      )}
    </RunScreen>
  );
};
