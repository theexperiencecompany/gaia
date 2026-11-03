"use client";

import { useSyncExternalStore } from "react";

import {
  readPendingCheckout,
  subscribePendingCheckout,
} from "../lib/pendingCheckout";

const serverSnapshot = (): null => null;

/**
 * The pending plan id, re-rendering when it is written or cleared: a resume
 * that fails clears it, and the routing it was holding back must run then.
 */
export const usePendingCheckout = (): string | null =>
  useSyncExternalStore(
    subscribePendingCheckout,
    readPendingCheckout,
    serverSnapshot,
  );
