import React from "react";

/**
 * Recharts is heavy (~100 kB min) and only needed when a chart actually
 * renders, so it loads on demand instead of shipping in the initial bundle.
 * The shared promise self-clears on rejection so a failed import is retried on
 * the next call instead of replaying forever.
 */
export type RechartsModule = typeof import("recharts");

let rechartsPromise: Promise<RechartsModule> | null = null;

export const loadRecharts = (): Promise<RechartsModule> => {
  rechartsPromise ??= import("recharts").catch((error: unknown) => {
    rechartsPromise = null;
    throw error;
  });
  return rechartsPromise;
};

/** Resolves the lazily loaded recharts module; null until the chunk arrives. */
export function useRecharts(): RechartsModule | null {
  const [recharts, setRecharts] = React.useState<RechartsModule | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    loadRecharts()
      .then((loaded) => {
        if (!cancelled) setRecharts(loaded);
      })
      .catch((error: unknown) => {
        console.error("Failed to load chart library:", error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return recharts;
}
