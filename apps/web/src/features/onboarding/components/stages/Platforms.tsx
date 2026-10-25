/**
 * `platformPick` stage. Telegram / WhatsApp / iMessage on GAIA Cloud (Slack
 * and Discord link from Settings); a self-hosted instance offers the bots it
 * runs and skips the stage when it runs none. The stage advances when the
 * user either connects a platform (`platformConnected`) or skips
 * (`skipPlatforms`); either also submits onboarding (`onConfirmed`).
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useEffect, useRef, useState } from "react";
import { PhoneLinkModal } from "@/components/shared/PhoneLinkModal";
import { BOT_PLATFORM_LABELS } from "@/config/botPlatforms";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { firstNameOf } from "@/features/auth/utils/firstName";
import { FIELD_NAMES } from "../../constants";
import { PLATFORM_INTRO_LINES } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { PlatformPreviewPlatform } from "../../constants/platformPreviewMessages";
import { useConnectPlatform } from "../../hooks/useConnectPlatform";
import { useOnboardingPlatforms } from "../../hooks/useOnboardingPlatforms";
import { usePaceDone } from "../../hooks/useTypedLines";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingBotBubbles } from "../OnboardingBotBubbles";
import { OnboardingPlatformConnect } from "../OnboardingPlatformConnect";
import { OnboardingPlatformPreview } from "../OnboardingPlatformPreview";

interface PlatformsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  onConfirmed: () => void;
}

const PLATFORM_REVEAL_KEY = "platform";

export function Platforms({ state, dispatch, onConfirmed }: PlatformsProps) {
  const gaiaDone = usePaceDone(PLATFORM_REVEAL_KEY);
  const [hoveredPlatform, setHoveredPlatform] =
    useState<PlatformPreviewPlatform | null>(null);

  const profession = state.responses[FIELD_NAMES.PROFESSION];
  const { name, email } = useCurrentUser();
  const userFirstName = firstNameOf(name, email);

  const {
    connect,
    skip,
    phoneModalOpen,
    phoneTarget,
    isSubmittingPhone,
    submitPhone,
    closePhoneModal,
  } = useConnectPlatform(dispatch, state.preferencesPersisted, onConfirmed);

  const platforms = useOnboardingPlatforms();
  const runsNoBot = platforms?.length === 0;
  // A ref, not state: StrictMode re-runs the effect and onboarding must submit once.
  const autoSkipped = useRef(false);
  useEffect(() => {
    if (!runsNoBot || autoSkipped.current) return;
    autoSkipped.current = true;
    skip();
  }, [runsNoBot, skip]);
  const offersPlatforms = gaiaDone && platforms && !runsNoBot;

  return (
    <m.div className="mt-4 flex flex-col gap-3" {...MOTION_FADE_UP}>
      {offersPlatforms && !state.connectedPlatform && (
        <m.div {...MOTION_FADE_UP}>
          <OnboardingPlatformPreview
            profession={profession}
            hoveredPlatform={hoveredPlatform}
            userFirstName={userFirstName}
          />
        </m.div>
      )}
      <OnboardingBotBubbles
        lines={PLATFORM_INTRO_LINES}
        revealKey={PLATFORM_REVEAL_KEY}
      />
      {offersPlatforms && (
        <m.div {...MOTION_FADE_UP}>
          <OnboardingPlatformConnect
            platforms={platforms}
            onConnect={connect}
            onSkip={skip}
            onHoverPlatform={setHoveredPlatform}
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
