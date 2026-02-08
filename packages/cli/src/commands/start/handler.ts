import { render } from "ink";
import React from "react";
import { createStore } from "../../ui/store.js";
import { App } from "../../ui/app.js";
import { runStartFlow } from "./flow.js";

export async function runStart(): Promise<void> {
  const store = createStore();

  const { unmount } = render(
    React.createElement(App, { store, command: "start" }),
  );

  try {
    await runStartFlow(store);
  } catch (error) {
    store.setError(error as Error);
  }

  await new Promise<void>((resolve) => {
    const check = () => {
      if (store.currentState.data.exitRequested) {
        resolve();
      } else {
        setTimeout(check, 100);
      }
    };
    check();
  });

  unmount();
  process.exit(0);
}
