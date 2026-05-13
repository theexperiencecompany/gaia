/**
 * Shared platform-connect logic. Hits the platform-link endpoint, opens an
 * OAuth popup, watches for a postMessage from it (or for the popup to close),
 * and dispatches `platformConnected` when the flow finishes. Returns a stable
 * `connect` callback plus a `skip` shortcut so both the active platforms
 * stage and the post-ack accordion can share one wiring.
 */

"use client";

import { type Dispatch, useCallback, useEffect, useRef } from "react";
import { apiService } from "@/lib/api/service";
import type { Action } from "../state/types";

interface UseConnectPlatformReturn {
  connect: (platform: string) => Promise<void>;
  skip: () => void;
}

export function useConnectPlatform(
  dispatch: Dispatch<Action>,
): UseConnectPlatformReturn {
  const popupCleanupRef = useRef<(() => void) | null>(null);

  const connect = useCallback(
    async (platform: string) => {
      popupCleanupRef.current?.();
      popupCleanupRef.current = null;

      const finish = () => {
        dispatch({ type: "platformConnected", platform });
      };

      try {
        const response = await apiService.get<{
          auth_url: string | null;
          auth_type: string;
          instructions: string | null;
          action_link: string | null;
        }>(`/platform-links/${platform.toLowerCase()}/connect`, {
          silent: true,
        });

        if (response.auth_url) {
          const width = 600;
          const height = 700;
          const left = window.screenX + (window.innerWidth - width) / 2;
          const top = window.screenY + (window.innerHeight - height) / 2;

          const popup = window.open(
            response.auth_url,
            `Connect ${platform}`,
            `width=${width},height=${height},left=${left},top=${top}`,
          );

          if (!popup) {
            finish();
            return;
          }

          let cancelled = false;
          let rafId = 0;
          const onMessage = (event: MessageEvent) => {
            if (event.source === popup) {
              cleanup();
              finish();
            }
          };
          const cleanup = () => {
            cancelled = true;
            if (rafId) cancelAnimationFrame(rafId);
            window.removeEventListener("message", onMessage);
            popupCleanupRef.current = null;
          };
          const tick = () => {
            if (cancelled) return;
            if (popup.closed) {
              cleanup();
              finish();
              return;
            }
            rafId = requestAnimationFrame(tick);
          };
          window.addEventListener("message", onMessage);
          rafId = requestAnimationFrame(tick);
          popupCleanupRef.current = cleanup;
        } else if (response.action_link) {
          window.open(response.action_link, "_blank");
          finish();
        }
      } catch {
        finish();
      }
    },
    [dispatch],
  );

  const skip = useCallback(() => {
    dispatch({ type: "skipPlatforms" });
  }, [dispatch]);

  useEffect(() => {
    return () => {
      popupCleanupRef.current?.();
      popupCleanupRef.current = null;
    };
  }, []);

  return { connect, skip };
}
