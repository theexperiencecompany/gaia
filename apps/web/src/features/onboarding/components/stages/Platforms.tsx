/**
 * `platformPick` stage. Telegram / WhatsApp / iMessage — Slack and Discord
 * moved to Settings → Linked accounts. The stage advances when the user
 * either connects a platform (`platformConnected`) or skips
 * (`skipPlatforms`).
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useState } from "react";
import { PhoneLinkModal } from "@/components/shared/PhoneLinkModal";
import { BOT_PLATFORM_LABELS } from "@/config/botPlatforms";
import { useUserStore } from "@/stores/userStore";
import { FIELD_NAMES } from "../../constants";
import { PLATFORM_INTRO_LINES } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { PlatformPreviewPlatform } from "../../constants/platformPreviewMessages";
import { useConnectPlatform } from "../../hooks/useConnectPlatform";
import { usePaceDone } from "../../hooks/useTypedLines";
import type { Action, OnboardingState } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingBotBubbles } from "../OnboardingBotBubbles";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingPlatformConnect } from "../OnboardingPlatformConnect";
import { OnboardingPlatformPreview } from "../OnboardingPlatformPreview";

interface PlatformsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

const PLATFORM_REVEAL_KEY = "platform";

export function Platforms({ state, dispatch }: PlatformsProps) {
  const gaiaDone = usePaceDone(PLATFORM_REVEAL_KEY);
  const [hoveredPlatform, setHoveredPlatform] =
    useState<PlatformPreviewPlatform | null>(null);

  const profession = state.responses[FIELD_NAMES.PROFESSION];
  const userName = useUserStore((s) => s.name);
  const userAvatar = useUserStore((s) => s.profilePicture);

  const {
    connect,
    skip,
    phoneModalOpen,
    phoneTarget,
    isSubmittingPhone,
    submitPhone,
    closePhoneModal,
  } = useConnectPlatform(dispatch, state.preferencesPersisted);

  return (
    <m.div className="mt-4 flex flex-col gap-3" {...MOTION_FADE_UP}>
      {gaiaDone && !state.connectedPlatform && (
        <m.div {...MOTION_FADE_UP}>
          <OnboardingPlatformPreview
            profession={profession}
            hoveredPlatform={hoveredPlatform}
            userName={userName}
            userAvatar={userAvatar}
          />
        </m.div>
      )}
      <OnboardingBotBubbles
        lines={PLATFORM_INTRO_LINES}
        revealKey={PLATFORM_REVEAL_KEY}
      />
      {gaiaDone && (
        <m.div {...MOTION_FADE_UP}>
          <OnboardingPlatformConnect
            onConnect={connect}
            onSkip={skip}
            onHoverPlatform={setHoveredPlatform}
            hideSkip
          />
        </m.div>
      )}
      <PhoneLinkModal
        isOpen={phoneModalOpen}
        platformName={BOT_PLATFORM_LABELS.imessage}
        isSubmitting={isSubmittingPhone}
        target={phoneTarget}
        onSubmit={submitPhone}
        onClose={closePhoneModal}
      />
    </m.div>
  );
}

export function PlatformsComposer({ state, dispatch }: PlatformsProps) {
  const { skip } = useConnectPlatform(dispatch, state.preferencesPersisted);
  if (state.connectedPlatform) return null;

  return (
    <ComposerCTA>
      <OnboardingCTAButton onClick={skip}>I'll do it later</OnboardingCTAButton>
    </ComposerCTA>
  );
}
