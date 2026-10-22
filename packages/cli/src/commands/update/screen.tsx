/**
 * Ink screen for `gaia update`: the shared run screen, with the offer and
 * its question while it waits (both gone once answered) and the one line a
 * run that changed nothing ends with.
 * @module commands/update/screen
 */

import { ConfirmInput } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { useState } from "react";
import { releaseSourceNotes } from "../../lib/selfhost-bundle.js";
import { CLI_VERSION } from "../../lib/version.js";
import { NoticeRow, RunScreen } from "../../ui/components/RunScreen.js";
import type { CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import {
  UPDATE_CONFIRM_INPUT,
  UPDATE_NOTICE_KEY,
  UPDATE_OFFER_KEY,
  type UpdateOffer,
} from "./offer.js";

const Offer: React.FC<{ store: CLIStore; offer: UpdateOffer }> = ({
  store,
  offer,
}) => (
  <Box flexDirection="column" marginTop={1}>
    {offer.lines.map((line) => (
      <Text key={line} dimColor>
        {line}
      </Text>
    ))}
    <Box marginTop={1}>
      <Text bold>{offer.question} </Text>
      <ConfirmInput
        defaultChoice="cancel"
        onConfirm={() => store.submitInput(UPDATE_CONFIRM_INPUT, true)}
        onCancel={() => store.submitInput(UPDATE_CONFIRM_INPUT, false)}
      />
    </Box>
  </Box>
);

export const UpdateScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const offer = state.data[UPDATE_OFFER_KEY];
  const notice = state.data[UPDATE_NOTICE_KEY];
  const [notes] = useState(() => releaseSourceNotes(process.env, CLI_VERSION));
  const asking = state.inputRequest?.id === UPDATE_CONFIRM_INPUT;

  return (
    <RunScreen store={store} notes={notes}>
      {asking && offer && <Offer store={store} offer={offer} />}
      {notice && (
        <Box marginTop={1}>
          <NoticeRow text={notice} />
        </Box>
      )}
    </RunScreen>
  );
};
