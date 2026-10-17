import { Spinner } from "@inkjs/ui";
import { Box, Text } from "ink";
import type React from "react";
import { Header } from "../components/Header.js";
import { LogWindow } from "../components/LogWindow.js";
import { Mark } from "../components/Mark.js";
import { ErrorStep } from "../components/shared-steps.js";
import type { CLIStore } from "../store.js";
import { useCLIState } from "../use-cli-state.js";

interface ServiceScreenProps {
  store: CLIStore;
  command: "start" | "stop";
}

/** `gaia start` / `gaia stop`: a spinner while Docker works, then one result line. */
export const ServiceScreen: React.FC<ServiceScreenProps> = ({ store }) => {
  const state = useCLIState(store);
  const working = state.step === "Starting" || state.step === "Stopping";
  const done = state.step === "Running" || state.step === "Stopped";
  const logs = (state.data.dockerLogs ?? []) as string[];

  return (
    <Box flexDirection="column" width="100%">
      <Header showStatus={done} />

      {working && !state.error && (
        <Box flexDirection="column" marginTop={1}>
          <Spinner label={state.status || "Working…"} />
          {logs.length > 0 && <LogWindow logs={logs} />}
        </Box>
      )}

      {state.step === "Running" && state.data.started && (
        <Box flexDirection="column" marginTop={1}>
          <Box>
            <Mark kind="ok" />
            <Text>
              GAIA is running at{" "}
              <Text color="cyan" bold>
                {state.data.webUrl}
              </Text>
            </Text>
          </Box>
          <Text color="gray">
            {"  "}gaia status shows its health · gaia stop shuts it down
          </Text>
        </Box>
      )}

      {state.step === "Stopped" && state.data.stopped && (
        <Box flexDirection="column" marginTop={1}>
          <Box>
            <Mark kind="ok" />
            <Text>{state.status}</Text>
          </Box>
          {state.data.stopMode === "force-ports" && (
            <Text color="yellow">
              {"  "}--force-ports also stopped whatever else listened on GAIA's
              ports.
            </Text>
          )}
        </Box>
      )}

      {state.error && <ErrorStep message={state.error.message} />}
    </Box>
  );
};
