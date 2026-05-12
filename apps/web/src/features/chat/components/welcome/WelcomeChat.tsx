/**
 * Post-onboarding welcome experience rendered the first time a freshly
 * onboarded user lands on `/c`. Re-uses the onboarding bubbles, platform
 * preview demo, and workflow cards so the visual language matches the
 * onboarding flow — but lives entirely inside the chat feature.
 *
 * The onboarding flow itself is not modified; this component only imports
 * read-only pieces of it.
 */

"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { ArrowRight02Icon, ConnectIcon } from "@icons";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { OnboardingPlatformConnect } from "@/features/onboarding/components/OnboardingPlatformConnect";
import { OnboardingPlatformPreview } from "@/features/onboarding/components/OnboardingPlatformPreview";
import { OnboardingWorkflowCards } from "@/features/onboarding/components/OnboardingWorkflowCards";
import { BOT_BUBBLE_DEFAULTS } from "@/features/onboarding/constants/bubbleDefaults";
import {
  WORKFLOWS_INTRO_PRIMARY,
  WORKFLOWS_INTRO_SECONDARY,
} from "@/features/onboarding/constants/messages";
import type { PlatformPreviewPlatform } from "@/features/onboarding/constants/platformPreviewMessages";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";
import { apiService } from "@/lib/api/service";
import { useUserStore } from "@/stores/userStore";

const WELCOME_INTRO =
  "Hey, welcome to GAIA. Here's your personalised setup ready to go.";

const CAPABILITIES_INTRO =
  "I can read your inbox, draft replies, manage your calendar, keep your todos in shape, and run jobs across your tools. Connect more apps anytime — the more I see, the more I can help.";

const WORKFLOWS_TIP =
  "Tap any card to peek inside the workflow. Edits live on the Workflows page.";

interface WelcomeChatProps {
  onDismiss: () => void;
}

export function WelcomeChat({ onDismiss }: WelcomeChatProps) {
  const router = useRouter();
  const popupCleanupRef = useRef<(() => void) | null>(null);
  const [hoveredPlatform, setHoveredPlatform] =
    useState<PlatformPreviewPlatform | null>(null);
  const [connectedPlatform, setConnectedPlatform] = useState<string | null>(
    null,
  );

  const userName = useUserStore((s) => s.name);
  const userAvatar = useUserStore((s) => s.profilePicture);
  const profession = useUserStore((s) => s.onboarding?.preferences?.profession);

  const { workflows, isLoading: workflowsLoading } = useWorkflows(true);

  const connectPlatform = useCallback(async (platform: string) => {
    popupCleanupRef.current?.();
    popupCleanupRef.current = null;

    const finish = () => setConnectedPlatform(platform);

    try {
      const response = await apiService.get<{
        auth_url: string | null;
        auth_type: string;
        instructions: string | null;
        action_link: string | null;
      }>(`/platform-links/${platform.toLowerCase()}/connect`, { silent: true });

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
  }, []);

  useEffect(() => {
    return () => {
      popupCleanupRef.current?.();
      popupCleanupRef.current = null;
    };
  }, []);

  const handleSkipPlatforms = useCallback(() => {
    setConnectedPlatform("__skipped__");
  }, []);

  const openIntegrations = useCallback(() => {
    router.push("/integrations");
  }, [router]);

  return (
    <m.div
      className="mx-auto flex w-full max-w-3xl flex-col gap-4 pt-6 pb-32"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={WELCOME_INTRO} />

      <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={CAPABILITIES_INTRO}>
        <div className="ml-10.75 mt-3">
          <Button
            variant="flat"
            color="primary"
            radius="full"
            startContent={<ConnectIcon className="size-4" />}
            onPress={openIntegrations}
          >
            Browse integrations
          </Button>
        </div>
      </ChatBubbleBot>

      {!connectedPlatform && (
        <OnboardingPlatformPreview
          profession={profession}
          hoveredPlatform={hoveredPlatform}
          userName={userName}
          userAvatar={userAvatar}
        />
      )}

      <ChatBubbleBot
        {...BOT_BUBBLE_DEFAULTS}
        text="You shouldn't have to come check on me. Pick where you already hang out and I'll text you — briefings, urgent emails, anything that can't wait."
      />

      <OnboardingPlatformConnect
        onConnect={connectPlatform}
        onSkip={handleSkipPlatforms}
        onHoverPlatform={setHoveredPlatform}
        connectedPlatform={
          connectedPlatform === "__skipped__" ? null : connectedPlatform
        }
      />

      <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={WORKFLOWS_INTRO_PRIMARY} />
      <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={WORKFLOWS_INTRO_SECONDARY}>
        <div className="mt-3">
          {workflowsLoading && workflows.length === 0 ? (
            <div className="ml-10.75 flex items-center gap-2 text-sm text-zinc-500">
              <Spinner size="sm" />
              <span>Loading your workflows…</span>
            </div>
          ) : workflows.length > 0 ? (
            <>
              <OnboardingWorkflowCards
                workflows={workflows.map((w) => ({
                  id: w.id,
                  title: w.title,
                  description: w.description,
                  steps: w.steps?.map((step) => ({
                    category: step.category,
                    title: step.title,
                    description: step.description,
                  })),
                }))}
              />
              <p className="mt-2 ml-10.75 text-xs text-zinc-500">
                {WORKFLOWS_TIP}
              </p>
            </>
          ) : (
            <p className="ml-10.75 text-sm text-zinc-500">
              No workflows yet — connect an integration to get started.
            </p>
          )}
        </div>
      </ChatBubbleBot>

      <div className="mt-2 flex justify-center">
        <Button
          color="primary"
          radius="full"
          endContent={<ArrowRight02Icon className="size-4" />}
          onPress={onDismiss}
        >
          Start chatting with GAIA
        </Button>
      </div>
    </m.div>
  );
}
