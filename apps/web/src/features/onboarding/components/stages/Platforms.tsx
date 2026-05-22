/**
 * `platforms` stage. Shows the Telegram / WhatsApp / Discord picker so the
 * user can pick a messaging platform to receive briefings on. The stage
 * advances when the user either connects a platform (dispatch
 * `platformConnected`) or clicks Skip (dispatch `skipPlatforms`).
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useState } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { useUserStore } from "@/stores/userStore";
import { FIELD_NAMES } from "../../constants";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { PlatformPreviewPlatform } from "../../constants/platformPreviewMessages";
import { useConnectPlatform } from "../../hooks/useConnectPlatform";
import type { Action, OnboardingState } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingPlatformConnect } from "../OnboardingPlatformConnect";
import { OnboardingPlatformPreview } from "../OnboardingPlatformPreview";

interface PlatformsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function Platforms({ state, dispatch }: PlatformsProps) {
  const [hoveredPlatform, setHoveredPlatform] =
    useState<PlatformPreviewPlatform | null>(null);

  const profession = state.responses[FIELD_NAMES.PROFESSION];
  const onboardingName = state.responses[FIELD_NAMES.NAME];
  const storeName = useUserStore((s) => s.name);
  const storeAvatar = useUserStore((s) => s.profilePicture);
  const userName = onboardingName || storeName;
  const userAvatar = storeAvatar;

  const { connect, skip } = useConnectPlatform(dispatch);

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
          "Tell me where you already hang out and I’ll text you when it matters, morning briefings, urgent emails, calendar nudges, deadline reminders, anything that can’t wait."
        }
      />
      <OnboardingPlatformConnect
        onConnect={connect}
        onSkip={skip}
        onHoverPlatform={setHoveredPlatform}
        hideSkip
      />
    </m.div>
  );
}

export function PlatformsComposer({ state, dispatch }: PlatformsProps) {
  const { skip } = useConnectPlatform(dispatch);
  if (state.connectedPlatform) return null;

  return (
    <ComposerCTA>
      <OnboardingCTAButton onClick={skip}>I'll do it later</OnboardingCTAButton>
    </ComposerCTA>
  );
}
