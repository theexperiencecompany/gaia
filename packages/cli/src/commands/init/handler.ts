/**
 * Handler for the 'init' command.
 * Sets up the React/Ink rendering and orchestrates the init flow.
 * @module commands/init/handler
 */

import { render } from "ink";
import React from "react";
import { App } from "../../ui/app.js";
import { createStore } from "../../ui/store.js";
import { runInitFlow } from "./flow.js";

/**
 * Executes the init command.
 * Creates the store, renders the UI, and runs the initialization flow.
 * Handles errors by displaying them in the UI before exiting.
 */
export async function runInit(
  options: { branch?: string } = {},
): Promise<void> {
  const store = createStore();

  const { unmount } = render(
    React.createElement(App, { store, command: "init" }),
  );

  const handleExit = () => {
    unmount();
    process.exit(130);
  };
  process.once("SIGINT", handleExit);
  process.once("SIGTERM", handleExit);

  try {
    await runInitFlow(store, options.branch);
  } catch (error) {
    store.setError(error as Error);
  } finally {
    process.off("SIGINT", handleExit);
    process.off("SIGTERM", handleExit);
  }

  if (store.currentState.error) {
    await store.waitForInput("exit");
  }

  unmount();
  process.exit(store.currentState.error ? 1 : 0);
}
