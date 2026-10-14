/**
 * Subscribes a screen to the CLI store, re-rendering on every change.
 * @module ui/use-cli-state
 */

import { useEffect, useState } from "react";
import type { CLIState, CLIStore } from "./store.js";

/** Returns a fresh copy of the store's state each time it changes. */
export function useCLIState(store: CLIStore): CLIState {
  const [state, setState] = useState(store.currentState);

  useEffect(() => {
    const update = () => setState({ ...store.currentState });
    store.on("change", update);
    return () => {
      store.off("change", update);
    };
  }, [store]);

  return state;
}
