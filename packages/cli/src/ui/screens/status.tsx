import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { STATUS_FACTS_KEY } from "../../commands/status/flow.js";
import {
  buildStatusReport,
  type StatusFacts,
  type StatusRow,
} from "../../commands/status/report.js";
import { Header } from "../components/Header.js";
import { Mark } from "../components/Mark.js";
import { ErrorStep } from "../components/shared-steps.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";
import { useCLIState } from "../use-cli-state.js";

const ROW_LABEL_WIDTH = 8;

const NOTE_COLOR: Record<StatusRow["tone"], string | undefined> = {
  ok: undefined,
  warn: "yellow",
  fail: "red",
  dim: "gray",
};

const ReportRow: React.FC<{ row: StatusRow }> = ({ row }) => (
  <Box flexDirection="column">
    <Box flexWrap="wrap">
      <Box width={ROW_LABEL_WIDTH} flexShrink={0}>
        <Text bold>{row.label}</Text>
      </Box>
      {row.items.map((item) => (
        <Box key={item.name} marginRight={2}>
          <Mark kind={item.ok ? "ok" : "fail"} />
          <Text>{item.name}</Text>
        </Box>
      ))}
      {row.items.length === 0 && row.note && (
        <Box>
          {row.tone !== "dim" && (
            <Mark kind={row.tone === "warn" ? "warn" : "ok"} />
          )}
          <Text color={NOTE_COLOR[row.tone]}>{row.note}</Text>
        </Box>
      )}
    </Box>
    {row.items.length > 0 && row.note && (
      <Box marginLeft={ROW_LABEL_WIDTH}>
        <Text color={NOTE_COLOR[row.tone]}>{row.note}</Text>
      </Box>
    )}
  </Box>
);

/** `gaia status`: one headline, a row per group, where GAIA is installed. */
export const StatusScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const facts = state.data[STATUS_FACTS_KEY] as StatusFacts | undefined;
  const watch = state.data.watch === true;
  const showingResults = state.step === "Results" && facts !== undefined;

  useInput(
    (input, key) => {
      if (input === "q" || key.return || key.escape) store.submitInput("exit");
      else if (input === "r") store.submitInput("refresh");
    },
    { isActive: watch && state.inputRequest !== null },
  );

  const report = facts ? buildStatusReport(facts) : null;
  const kind = report?.headline.kind ?? "ok";

  return (
    <Box flexDirection="column" width="100%">
      <Header showStatus={false} />

      {state.step === "Checking" && (
        <Box marginTop={1} marginLeft={2}>
          <Spinner label={state.status} />
        </Box>
      )}

      {showingResults && report && (
        <Box flexDirection="column" marginTop={1} marginLeft={2}>
          <Box>
            <Mark kind={kind === "ok" ? "active" : kind} />
            <Text bold>{report.headline.text}</Text>
          </Box>
          {report.headline.url && (
            <Box marginLeft={2}>
              <Text color={THEME_COLOR}>{report.headline.url}</Text>
            </Box>
          )}
          {report.hint && (
            <Box marginLeft={2}>
              <Text>{report.hint}</Text>
            </Box>
          )}
          {report.rows.length > 0 && (
            <Box flexDirection="column" marginTop={1}>
              {report.rows.map((row) => (
                <ReportRow key={row.label} row={row} />
              ))}
            </Box>
          )}
          {facts.installed && (
            <Box marginTop={1}>
              <Text color="gray">Installed at {facts.install}</Text>
            </Box>
          )}
          {watch && (
            <Box marginTop={1}>
              <Text color="gray">
                checked {state.data.checkedAt} · <Text bold>r</Text> check again
                · <Text bold>q</Text> quit
              </Text>
            </Box>
          )}
        </Box>
      )}

      {state.error && <ErrorStep message={state.error.message} />}
    </Box>
  );
};
