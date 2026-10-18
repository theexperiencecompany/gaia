import { ThemeProvider } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import React from "react";
import { UninstallScreen } from "../commands/uninstall/screen.js";
import { UpScreen } from "../commands/up/screen.js";
import { HANDED_OVER_KEY } from "./constants.js";
import { InitScreen } from "./screens/init.js";
import { ServiceScreen } from "./screens/service.js";
import { SetupScreen } from "./screens/setup.js";
import { StatusScreen } from "./screens/status.js";
import type { CLIStore } from "./store.js";
import { cliTheme } from "./theme.js";
import { useCLIState } from "./use-cli-state.js";

export type CLICommand =
  | "init"
  | "setup"
  | "status"
  | "start"
  | "stop"
  | "up"
  | "uninstall";

const AVAILABLE_COMMANDS: readonly CLICommand[] = [
  "init",
  "setup",
  "status",
  "start",
  "stop",
  "up",
  "uninstall",
];

interface AppProps {
  store: CLIStore;
  command: CLICommand;
}

interface ErrorBoundaryState {
  error: Error | null;
}

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override render(): React.ReactNode {
    if (this.state.error) {
      return (
        <Box flexDirection="column" padding={1}>
          <Text color="red" bold>
            An unexpected error occurred:
          </Text>
          <Text color="red">{this.state.error.message}</Text>
          {this.state.error.stack && (
            <Box marginTop={1}>
              <Text color="gray" dimColor>
                {this.state.error.stack}
              </Text>
            </Box>
          )}
        </Box>
      );
    }
    return this.props.children;
  }
}

const CommandRouter: React.FC<AppProps> = ({ store, command }) => {
  switch (command) {
    case "init":
      return <InitScreen store={store} />;
    case "setup":
      return <SetupScreen store={store} />;
    case "status":
      return <StatusScreen store={store} />;
    case "start":
    case "stop":
      return <ServiceScreen store={store} command={command} />;
    case "up":
      return <UpScreen store={store} />;
    case "uninstall":
      return <UninstallScreen store={store} />;
    default:
      return (
        <Box flexDirection="column" padding={1}>
          <Text color="red">Unknown command: {command}</Text>
          <Box marginTop={1} flexDirection="column">
            <Text bold>Available commands:</Text>
            {AVAILABLE_COMMANDS.map((cmd) => (
              <Text key={cmd}>
                {"  "}
                <Text color="cyan">{cmd}</Text>
              </Text>
            ))}
          </Box>
        </Box>
      );
  }
};

/** Ctrl-C in raw mode arrives as input, not SIGINT: hand it to the runner. */
const CancelOnCtrlC: React.FC<{ onCancel: () => void }> = ({ onCancel }) => {
  useInput((input, key) => {
    if (key.ctrl && input === "c") onCancel();
  });
  return null;
};

export const App: React.FC<AppProps & { onCancel: () => void }> = ({
  store,
  command,
  onCancel,
}) => {
  const state = useCLIState(store);
  return (
    <ErrorBoundary>
      <ThemeProvider theme={cliTheme}>
        <CancelOnCtrlC onCancel={onCancel} />
        {/* A process handing its screen to a relaunch takes its live lines down; what it wrote stays. */}
        {state.data[HANDED_OVER_KEY] !== true && (
          <CommandRouter store={store} command={command} />
        )}
      </ThemeProvider>
    </ErrorBoundary>
  );
};
