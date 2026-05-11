/**
 * `platforms` stage. Shows the Telegram / WhatsApp / Discord picker so the
 * user can pick a messaging platform to receive briefings on. The stage
 * advances when the user either connects a platform (dispatch
 * `platformConnected`) or clicks Skip (dispatch `skipPlatforms`).
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useCallback, useEffect, useRef } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { apiService } from "@/lib/api/service";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingPlatformConnect } from "../OnboardingPlatformConnect";

interface PlatformsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function Platforms({ state, dispatch }: PlatformsProps) {
  const popupCleanupRef = useRef<(() => void) | null>(null);

  const connectPlatform = useCallback(
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

  return (
    <m.div className="mt-4" {...MOTION_FADE_UP}>
      <ChatBubbleBot
        {...BOT_BUBBLE_DEFAULTS}
        text="Get notifications and talk to me on the go:"
      >
        <div className="mt-3">
          <OnboardingPlatformConnect
            onConnect={connectPlatform}
            onSkip={skip}
            connectedPlatform={state.connectedPlatform}
          />
        </div>
      </ChatBubbleBot>
    </m.div>
  );
}
