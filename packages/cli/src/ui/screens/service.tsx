import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import { Header } from "../components/Header.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";
import { CommandsSummary } from "./init.js";

interface ServiceScreenProps {
  store: CLIStore;
  command: "start" | "stop";
}

export const ServiceScreen: React.FC<ServiceScreenProps> = ({
  store,
  command,
}) => {
  const [state, setState] = useState(store.currentState);

  useEffect(() => {
    const update = () => setState({ ...store.currentState });
    store.on("change", update);
    return () => {
      store.off("change", update);
    };
  }, [store]);

  useInput((_input, key) => {
    if (
      (key.return || key.escape) &&
      (state.data.started || state.data.stopped || state.error)
    ) {
      store.updateData("exitRequested", true);
    }
  });

  const isStart = command === "start";

  return (
    <Box flexDirection="column" width="100%">
      <Header />

      {(state.step === "Starting" || state.step === "Stopping") && (
        <Box
          flexDirection="column"
          marginTop={1}
          paddingX={2}
          borderStyle="round"
          borderColor={THEME_COLOR}
        >
          <Spinner label={state.status || "Working..."} />
          {state.data.repoPath && (
            <Box marginTop={1}>
              <Text color="gray">Repository: {state.data.repoPath}</Text>
            </Box>
          )}
          {state.data.setupMode && (
            <Box>
              <Text color="gray">Mode: {state.data.setupMode}</Text>
            </Box>
          )}
        </Box>
      )}

      {state.step === "Running" && state.data.started && (
        <Box
          flexDirection="column"
          marginTop={1}
          paddingX={2}
          paddingY={1}
          borderStyle="round"
          borderColor="green"
        >
          <Text color="green" bold>
            {"\u2713"} GAIA is running!
          </Text>
          <Box marginTop={1} flexDirection="column">
            <Text>
              Web:{" "}
              <Text color="cyan" bold>
                http://localhost:3000
              </Text>
            </Text>
            <Text>
              API:{" "}
              <Text color="cyan" bold>
                http://localhost:8000
              </Text>
            </Text>
          </Box>
          <Box marginTop={1}>
            <Text dimColor>Press Enter to exit</Text>
          </Box>
        </Box>
      )}

      {state.step === "Stopped" && state.data.stopped && (
        <Box
          flexDirection="column"
          marginTop={1}
          paddingX={2}
          paddingY={1}
          borderStyle="round"
          borderColor={THEME_COLOR}
        >
          <Text color={THEME_COLOR} bold>
            {"\u2713"} All GAIA services stopped.
          </Text>
          <Box marginTop={1}>
            <Text dimColor>Press Enter to exit</Text>
          </Box>
        </Box>
      )}

      {state.error && (
        <Box borderStyle="single" borderColor="red" padding={1} marginTop={2}>
          <Text color="red">Error: {state.error.message}</Text>
          <Box marginTop={1}>
            <Text dimColor>Press Enter to exit</Text>
          </Box>
        </Box>
      )}
    </Box>
  );
};
