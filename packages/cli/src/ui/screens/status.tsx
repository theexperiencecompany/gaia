import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import type { ServiceStatus } from "../../lib/healthcheck.js";
import type { ContainerStatus } from "../../lib/docker.js";
import { Header } from "../components/Header.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";

export const StatusScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const [state, setState] = useState(store.currentState);

  useEffect(() => {
    const update = () => setState({ ...store.currentState });
    store.on("change", update);
    return () => {
      store.off("change", update);
    };
  }, [store]);

  useInput((_input, key) => {
    if (key.return || key.escape) {
      store.updateData("exitRequested", true);
    }
  });

  return (
    <Box flexDirection="column" width="100%">
      <Header />

      {state.step === "Checking" && (
        <Box marginTop={1}>
          <Spinner label="Checking service health..." />
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
            <Text bold color={THEME_COLOR}>
              GAIA Service Status
            </Text>
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
              <Text color="gray">
                {"─".repeat(42)}
              </Text>
              {state.data.services.map((service: ServiceStatus) => (
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
                      {service.status === "up"
                        ? "\u2713 UP"
                        : "\u2717 DOWN"}
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
                            container.status === "running"
                              ? "green"
                              : "red"
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
            <Text dimColor>Press Enter or Escape to exit</Text>
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
