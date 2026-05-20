import { render } from "ink";
import React from "react";
import { attachPlainReporter, isInteractive } from "../../lib/non-tty.js";
import type { StartServicesOptions } from "../../lib/service-starter.js";
import { App } from "../../ui/app.js";
import { createStore } from "../../ui/store.js";
import { runStartFlow } from "./flow.js";

export async function runStart(options?: StartServicesOptions): Promise<void> {
  const store = createStore();

  if (!isInteractive()) {
    // Non-TTY: skip Ink (it can't render without raw mode) and stream the
    // store's state changes as plain text. Auto-resolve the trailing
    // "press Enter to exit" prompt so the process terminates cleanly.
    attachPlainReporter(store);
    store.setAutoResolve("exit");
    try {
      await runStartFlow(store, options);
    } catch (error) {
      store.setError(error as Error);
    }
    process.exit(store.currentState.error ? 1 : 0);
  }

  const { unmount } = render(
    React.createElement(App, { store, command: "start" }),
  );

  const handleExit = () => {
    unmount();
    process.exit(130);
  };
  process.once("SIGINT", handleExit);
  process.once("SIGTERM", handleExit);

  await new Promise((resolve) => setTimeout(resolve, 50));

  try {
    await runStartFlow(store, options);
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
