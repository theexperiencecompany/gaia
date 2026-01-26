/**
 * Main application component for the CLI.
 * Routes to different screens based on the command.
 * @module app
 */

import type React from "react";
import { InitScreen } from "./screens/init.js";
import type { CLIStore } from "./store.js";

/**
 * Props for the App component.
 */
interface AppProps {
  /** CLI store instance for state management */
  store: CLIStore;
  /** Command being executed (e.g., 'init') */
  command: string;
}

/**
 * Root application component that routes to command-specific screens.
 * Currently supports the 'init' command.
 * @param props - Application properties
 * @param props.store - CLI store instance
 * @param props.command - Command to execute
 */
export const App: React.FC<AppProps> = ({ store, command }) => {
  if (command === "init") {
    return <InitScreen store={store} />;
  }
  return null;
};
