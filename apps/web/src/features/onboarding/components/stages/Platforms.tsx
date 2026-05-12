/**
 * `platforms` stage. Shows the Telegram / WhatsApp / Discord picker so the
 * user can pick a messaging platform to receive briefings on. The stage
 * advances when the user either connects a platform (dispatch
 * `platformConnected`) or clicks Skip (dispatch `skipPlatforms`).
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { apiService } from "@/lib/api/service";
import { useUserStore } from "@/stores/userStore";
import { FIELD_NAMES } from "../../constants";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { PlatformPreviewPlatform } from "../../constants/platformPreviewMessages";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingPlatformConnect } from "../OnboardingPlatformConnect";
import { OnboardingPlatformPreview } from "../OnboardingPlatformPreview";

interface PlatformsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function Platforms({ state, dispatch }: PlatformsProps) {
  const popupCleanupRef = useRef<(() => void) | null>(null);
  const [hoveredPlatform, setHoveredPlatform] =
    useState<PlatformPreviewPlatform | null>(null);

  const profession = state.responses[FIELD_NAMES.PROFESSION];
  const onboardingName = state.responses[FIELD_NAMES.NAME];
  const storeName = useUserStore((s) => s.name);
  const storeAvatar = useUserStore((s) => s.profilePicture);
  const userName = onboardingName || storeName;
  const userAvatar = storeAvatar;

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
    <m.div className="mt-4 flex flex-col gap-3" {...MOTION_FADE_UP}>
      {!state.connectedPlatform && (
        <OnboardingPlatformPreview
          profession={profession}
          hoveredPlatform={hoveredPlatform}
          userName={userName}
          userAvatar={userAvatar}
        />
      )}
      <ChatBubbleBot
        {...BOT_BUBBLE_DEFAULTS}
        text={
          "You shouldn’t have to come check on me. Tell me where you already hang out and I’ll text you — briefings, urgent emails, anything that can’t wait."
        }
      />
      <OnboardingPlatformConnect
        onConnect={connectPlatform}
        onSkip={skip}
        onHoverPlatform={setHoveredPlatform}
        connectedPlatform={state.connectedPlatform}
      />
    </m.div>
  );
}
