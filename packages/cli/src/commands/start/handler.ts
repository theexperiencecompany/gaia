import { render } from "ink";
import React from "react";
import type { StartServicesOptions } from "../../lib/service-starter.js";
import { App } from "../../ui/app.js";
import { createStore } from "../../ui/store.js";
import { runStartFlow } from "./flow.js";

export async function runStart(options?: StartServicesOptions): Promise<void> {
  const store = createStore();

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
