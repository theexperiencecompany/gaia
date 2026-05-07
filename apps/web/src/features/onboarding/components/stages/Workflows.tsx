/**
 * `workflows` stage. Shows the suggested workflows, then once confirmed (or
 * if there are zero workflows) reveals the platform-connect picker. The
 * composer is an "Understood" CTA that dispatches `confirmWorkflows`.
 */

"use client";

import { m } from "motion/react";
import type { Dispatch } from "react";
import { useCallback, useEffect, useRef } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { apiService } from "@/lib/api/service";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import { MOTION_FADE_UP, MOTION_FADE_UP_LARGE } from "../../constants/motion";
import type { Action, OnboardingState } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingPlatformConnect } from "../OnboardingPlatformConnect";
import { OnboardingWorkflowCards } from "../OnboardingWorkflowCards";

interface WorkflowsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

/**
 * True iff the platform-connect picker should be visible: either the user
 * acknowledged workflows or the backend produced none. Kept here so both
 * `Workflows` content and `WorkflowsComposer` agree.
 */
function shouldShowPlatformConnect(state: OnboardingState): boolean {
  const workflows = state.server?.suggested_workflows ?? [];
  return state.workflowsConfirmed || workflows.length === 0;
}

export function Workflows({ state, dispatch }: WorkflowsProps) {
  const popupCleanupRef = useRef<(() => void) | null>(null);

  const workflows = state.server?.suggested_workflows ?? [];
  const workflowsConfirmed = state.workflowsConfirmed;
  const showPlatformConnect = shouldShowPlatformConnect(state);

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

  const skipPlatformConnect = useCallback(() => {
    dispatch({ type: "confirmWorkflows" });
  }, [dispatch]);

  useEffect(() => {
    return () => {
      popupCleanupRef.current?.();
      popupCleanupRef.current = null;
    };
  }, []);

  return (
    <m.div className="mt-4 space-y-4" {...MOTION_FADE_UP_LARGE}>
      {workflows.length > 0 && (
        <ChatBubbleBot
          {...BOT_BUBBLE_DEFAULTS}
          text="Here's what I set up to run on a recurring basis:"
        >
          <div className="mt-3">
            <OnboardingWorkflowCards workflows={workflows} />
          </div>
          {!workflowsConfirmed && (
            <p className="mt-2 ml-10.75 text-xs text-zinc-500">
              These run automatically. Customize them anytime in Workflows.
            </p>
          )}
        </ChatBubbleBot>
      )}

      {showPlatformConnect && (
        <m.div {...MOTION_FADE_UP}>
          <ChatBubbleBot
            {...BOT_BUBBLE_DEFAULTS}
            text="Get notifications and talk to me on the go:"
          >
            <div className="mt-3">
              <OnboardingPlatformConnect
                onConnect={connectPlatform}
                onSkip={skipPlatformConnect}
                connectedPlatform={state.connectedPlatform}
              />
            </div>
          </ChatBubbleBot>
        </m.div>
      )}
    </m.div>
  );
}

export function WorkflowsComposer({ state, dispatch }: WorkflowsProps) {
  if (shouldShowPlatformConnect(state)) return null;

  return (
    <ComposerCTA>
      <OnboardingCTAButton
        onClick={() => dispatch({ type: "confirmWorkflows" })}
      >
        Understood
      </OnboardingCTAButton>
    </ComposerCTA>
  );
}
