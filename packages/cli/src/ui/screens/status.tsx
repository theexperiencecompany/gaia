import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import type { ContainerStatus } from "../../lib/docker.js";
import type { ServiceStatus } from "../../lib/healthcheck.js";
import { Header } from "../components/Header.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";

export const StatusScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const [state, setState] = useState(store.currentState);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  useEffect(() => {
    const update = () => setState({ ...store.currentState });
    store.on("change", update);
    return () => {
      store.off("change", update);
    };
  }, [store]);

  useEffect(() => {
    setIsRefreshing(false);
    setLastChecked(new Date().toLocaleTimeString());
  }, [state.data.services]);

  useInput((_input, key) => {
    if ((key.return || key.escape) && state.step === "Results") {
      store.submitInput("exit");
    }
    if (
      _input === "r" &&
      state.step === "Results" &&
      state.data.refreshable &&
      !isRefreshing
    ) {
      setIsRefreshing(true);
      store.submitInput("refresh");
    }
  });

  return (
    <Box flexDirection="column" width="100%">
      <Header />

      {state.step === "Checking" && (
        <Box marginTop={1}>
          <Spinner
            label={
              state.data.services
                ? "Refreshing service health..."
                : "Checking service health..."
            }
          />
        </Box>
      )}

      {state.step === "Results" && state.data.services && (
        <Box flexDirection="column">
          <Box
            flexDirection="column"
            borderStyle="round"
            borderColor={THEME_COLOR}
            paddingX={2}
            paddingY={1}
          >
            <Box justifyContent="space-between">
              <Text bold color={THEME_COLOR}>
                GAIA Service Status
              </Text>
              {lastChecked && (
                <Text color="gray" dimColor>
                  checked {lastChecked} · <Text bold>r</Text> refresh
                </Text>
              )}
            </Box>
            <Box marginTop={1} flexDirection="column">
              <Box>
                <Box width={22}>
                  <Text bold>Service</Text>
                </Box>
                <Box width={10}>
                  <Text bold>Status</Text>
                </Box>
                <Box width={10}>
                  <Text bold>Latency</Text>
                </Box>
              </Box>
              <Text color="gray">{"─".repeat(42)}</Text>
              {[...state.data.services]
                .sort((a: ServiceStatus, b: ServiceStatus) => {
                  if (a.status === "down" && b.status !== "down") return -1;
                  if (a.status !== "down" && b.status === "down") return 1;
                  return a.name.localeCompare(b.name);
                })
                .map((service: ServiceStatus) => (
                  <Box key={service.name}>
                    <Box width={22}>
                      <Text>
                        {service.name} (:{service.port})
                      </Text>
                    </Box>
                    <Box width={10}>
                      <Text
                        color={service.status === "up" ? "green" : "red"}
                        bold
                      >
                        {service.status === "up" ? "\u2713 UP" : "\u2717 DOWN"}
                      </Text>
                    </Box>
                    <Box width={10}>
                      <Text color="gray">
                        {service.latency ? `${service.latency}ms` : "--"}
                      </Text>
                    </Box>
                  </Box>
                ))}
            </Box>
          </Box>

          {state.data.docker && (
            <Box
              flexDirection="column"
              borderStyle="round"
              borderColor="gray"
              paddingX={2}
              paddingY={1}
              marginTop={1}
            >
              <Text bold>Docker Containers</Text>
              <Text color="gray">
                Docker:{" "}
                {state.data.docker.running ? (
                  <Text color="green">Running</Text>
                ) : (
                  <Text color="red">Not running</Text>
                )}
              </Text>
              {state.data.docker.containers?.length > 0 && (
                <Box marginTop={1} flexDirection="column">
                  {state.data.docker.containers.map(
                    (container: ContainerStatus) => (
                      <Box key={container.name}>
                        <Text
                          color={
                            container.status === "running" ? "green" : "red"
                          }
                        >
                          {container.status === "running"
                            ? "\u2713"
                            : "\u2717"}{" "}
                        </Text>
                        <Text>{container.name}</Text>
                        {container.health && (
                          <Text color="gray"> ({container.health})</Text>
                        )}
                      </Box>
                    ),
                  )}
                </Box>
              )}
            </Box>
          )}

          <Box marginTop={1}>
            <Text dimColor>
              <Text bold>Enter</Text> exit · <Text bold>r</Text> refresh
            </Text>
          </Box>
        </Box>
      )}

      {state.error && (
        <Box borderStyle="single" borderColor="red" padding={1} marginTop={2}>
          <Text color="red">Error: {state.error.message}</Text>
        </Box>
      )}
    </Box>
  );
};
