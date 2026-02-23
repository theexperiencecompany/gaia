import { render } from "ink";
import React from "react";
import type { StopServicesOptions } from "../../lib/service-starter.js";
import { App } from "../../ui/app.js";
import { createStore } from "../../ui/store.js";
import { runStopFlow } from "./flow.js";

export async function runStop(options?: StopServicesOptions): Promise<void> {
  const store = createStore();

  const { unmount } = render(
    React.createElement(App, { store, command: "stop" }),
  );

  const handleExit = () => {
    unmount();
    process.exit(130);
  };
  process.once("SIGINT", handleExit);
  process.once("SIGTERM", handleExit);

  await new Promise((resolve) => setTimeout(resolve, 50));

  try {
    await runStopFlow(store, options);
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
