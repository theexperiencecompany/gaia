/**
 * `platformPick` stage. Telegram / WhatsApp / iMessage on GAIA Cloud (Slack
 * and Discord link from Settings); a self-hosted instance offers the bots it
 * runs and skips the stage when it runs none. Picking a platform opens its
 * app and waits there until the link actually lands (`platformConnected`);
 * skipping (`skipPlatforms`) advances at once. Either submits onboarding
 * (`onConfirmed`).
 */

"use client";

import { Button, Spinner } from "@heroui/react";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useEffect, useRef, useState } from "react";
import { PhoneLinkModal } from "@/components/shared/PhoneLinkModal";
import { BOT_PLATFORM_LABELS } from "@/config/botPlatforms";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { firstNameOf } from "@/features/auth/utils/firstName";
import { FIELD_NAMES } from "../../constants";
import {
  AWAITING_LINK_LINES,
  AWAITING_LINK_OTHER_APP_LABEL,
  AWAITING_LINK_SKIP_LABEL,
  PLATFORM_INTRO_LINES,
} from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { PlatformPreviewPlatform } from "../../constants/platformPreviewMessages";
import { useConnectPlatform } from "../../hooks/useConnectPlatform";
import { useOnboardingPlatforms } from "../../hooks/useOnboardingPlatforms";
import { usePaceDone } from "../../hooks/useTypedLines";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingBotBubble } from "../OnboardingBotBubble";
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
    awaitingPlatform,
    chooseAnother,
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
  const offersPlatforms =
    gaiaDone && platforms && !runsNoBot && awaitingPlatform === null;

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
      {awaitingPlatform && (
        <m.div className="flex flex-col items-start gap-3" {...MOTION_FADE_UP}>
          <OnboardingBotBubble text={AWAITING_LINK_LINES[awaitingPlatform]} />
          <div className="flex flex-wrap items-center gap-2 sm:ml-10.75">
            <Spinner
              size="sm"
              aria-label={`Waiting for ${BOT_PLATFORM_LABELS[awaitingPlatform]}`}
            />
            <Button
              variant="tertiary"
              size="md"
              onPress={() => connect(awaitingPlatform)}
            >
              Open {BOT_PLATFORM_LABELS[awaitingPlatform]} again
            </Button>
            <Button variant="ghost" size="md" onPress={chooseAnother}>
              {AWAITING_LINK_OTHER_APP_LABEL}
            </Button>
            <Button variant="ghost" size="md" onPress={skip}>
              {AWAITING_LINK_SKIP_LABEL}
            </Button>
          </div>
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
