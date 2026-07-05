import type { HilPreferences } from "@gaia/shared/chat";
import { useCallback, useEffect, useState } from "react";
import { settingsApi } from "@/features/settings/api/settings-api";

const EMPTY: HilPreferences = { enabled: false, tool_overrides: {} };

/**
 * HIL preferences with optimistic per-tool overrides. Mirrors the web hook but
 * uses local state (mobile has no shared react-query cache for this).
 */
export function useHilPreferences() {
  const [prefs, setPrefs] = useState<HilPreferences>(EMPTY);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .getHilPreferences()
      .then((p) => {
        if (!cancelled) setPrefs(p);
      })
      .catch(() => {
        // silently ignore — defaults keep the list usable
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setEnabled = useCallback(
    async (enabled: boolean): Promise<boolean> => {
      const previous = prefs;
      setPrefs((p) => ({ ...p, enabled }));
      try {
        setPrefs(await settingsApi.updateHilPreferences({ enabled }));
        return true;
      } catch {
        // Roll back and report failure without rejecting, matching
        // setToolApproval — callers decide whether to surface an error.
        setPrefs(previous);
        return false;
      }
    },
    [prefs],
  );

  const setToolApproval = useCallback(
    async (name: string, ask: boolean, destructive: boolean) => {
      // Store only diffs from the default: matching the default clears the override.
      const value = ask === destructive ? null : ask;
      const previous = prefs;
      setPrefs((p) => {
        const overrides = { ...p.tool_overrides };
        if (value === null) delete overrides[name];
        else overrides[name] = value;
        return { ...p, tool_overrides: overrides };
      });
      try {
        setPrefs(await settingsApi.setToolOverride(name, value));
      } catch {
        setPrefs(previous);
      }
    },
    [prefs],
  );

  return { prefs, isLoading, setEnabled, setToolApproval };
}

/** Effective "ask before running" state for a tool. */
export function toolAsks(
  prefs: HilPreferences,
  name: string,
  destructive: boolean,
): boolean {
  return prefs.tool_overrides[name] ?? destructive;
}
