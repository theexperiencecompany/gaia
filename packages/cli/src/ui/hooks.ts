import { useInput } from "ink";
import { useEffect, useState } from "react";
import type { CLIState, CLIStore } from "./store.js";

/**
 * Subscribes to a CLIStore and returns the current state, kept in sync
 * via the store's "change" event. Also registers a global input handler
 * that exits on Enter/Escape when the state has an error.
 */
export const useStoreSync = (store: CLIStore): CLIState => {
  const [state, setState] = useState(store.currentState);

  useEffect(() => {
    const update = () => setState({ ...store.currentState });
    store.on("change", update);
    return () => {
      store.off("change", update);
    };
  }, [store]);

  useInput((_input, key) => {
    if ((key.return || key.escape) && state.error) {
      store.submitInput("exit");
    }
  });

  return state;
};
