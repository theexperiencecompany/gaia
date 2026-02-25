import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { Header } from "../components/Header.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";

const LOG_HEIGHT = 8;

const DockerLogWindow: React.FC<{ logs: string[] }> = ({ logs }) => {
  const [scrollOffset, setScrollOffset] = useState(0);
  const prevLenRef = useRef(logs.length);

  useEffect(() => {
    if (logs.length !== prevLenRef.current) {
      prevLenRef.current = logs.length;
      setScrollOffset(0);
    }
  }, [logs.length]);

  useInput((_input, key) => {
    if (key.upArrow) {
      setScrollOffset((o) =>
        Math.min(o + 1, Math.max(0, logs.length - LOG_HEIGHT)),
      );
    } else if (key.downArrow) {
      setScrollOffset((o) => Math.max(0, o - 1));
    }
  });

  const total = logs.length;
  const start = Math.max(0, total - LOG_HEIGHT - scrollOffset);
  const end = Math.max(0, total - scrollOffset);
  const visible = logs.slice(start, end);
  const linesAbove = start;
  const linesBelow = scrollOffset;

  return (
    <Box flexDirection="column" marginTop={1} marginLeft={1}>
      {linesAbove > 0 && (
        <Text color="gray" dimColor>
          ↑ {linesAbove} more line{linesAbove !== 1 ? "s" : ""}
        </Text>
      )}
      <Box flexDirection="column" height={LOG_HEIGHT} overflow="hidden">
        {visible.map((line, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: logs are append-only
          <Text key={start + i} color="gray" wrap="truncate">
            {line}
          </Text>
        ))}
      </Box>
      {linesBelow > 0 ? (
        <Text color="gray" dimColor>
          ↓ {linesBelow} more line{linesBelow !== 1 ? "s" : ""}
        </Text>
      ) : (
        <Text color="gray" dimColor>
          ↑↓ scroll
        </Text>
      )}
    </Box>
  );
};

interface ServiceScreenProps {
  store: CLIStore;
  command: "start" | "stop";
}

export const ServiceScreen: React.FC<ServiceScreenProps> = ({ store }) => {
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
      store.submitInput("exit");
    }
  });

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
          {state.data.dockerLogs && state.data.dockerLogs.length > 0 && (
            <DockerLogWindow logs={state.data.dockerLogs as string[]} />
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
          {state.data.setupMode !== "developer" && (
            <Box marginTop={1} flexDirection="column">
              <Text>
                Web:{" "}
                <Text color="cyan" bold>
                  http://localhost:{state.data.webPort || 3000}
                </Text>
              </Text>
              <Text>
                API:{" "}
                <Text color="cyan" bold>
                  http://localhost:{state.data.apiPort || 8000}
                </Text>
              </Text>
            </Box>
          )}
          {state.data.setupMode === "developer" && (
            <Box marginTop={1} flexDirection="column">
              <Box flexDirection="column">
                <Text>
                  Web:{" "}
                  <Text color="cyan" bold>
                    http://localhost:{state.data.webPort || 3000}
                  </Text>
                </Text>
                <Text>
                  API:{" "}
                  <Text color="cyan" bold>
                    http://localhost:{state.data.apiPort || 8000}
                  </Text>
                </Text>
              </Box>
              <Box marginTop={1} flexDirection="column">
                <Text color="gray">
                  Use gaia dev / gaia dev full for foreground Nx TUI.
                </Text>
                <Text color="gray">
                  Run <Text color={THEME_COLOR}>gaia logs</Text> to stream logs.
                </Text>
                <Text color="gray">
                  Run <Text color={THEME_COLOR}>gaia stop</Text> to shut down.
                </Text>
              </Box>
            </Box>
          )}
          <Box marginTop={1}>
            <Text dimColor>
              <Text bold>Enter</Text> to exit
            </Text>
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
            {"\u2713"} {state.status || "All GAIA services stopped."}
          </Text>
          {state.data.stopMode === "force-ports" && (
            <Box marginTop={1}>
              <Text color="yellow">
                Force-port cleanup was enabled and may have stopped non-GAIA
                listeners on app ports.
              </Text>
            </Box>
          )}
          <Box marginTop={1}>
            <Text dimColor>
              <Text bold>Enter</Text> to exit
            </Text>
          </Box>
        </Box>
      )}

      {state.error && (
        <Box borderStyle="single" borderColor="red" padding={1} marginTop={2}>
          <Text color="red">Error: {state.error.message}</Text>
          <Box marginTop={1}>
            <Text dimColor>
              <Text bold>Enter</Text> to exit
            </Text>
          </Box>
        </Box>
      )}
    </Box>
  );
};
