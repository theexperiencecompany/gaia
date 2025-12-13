/**
 * WebSocket message types for onboarding feature
 */

import type { OnboardingPhase } from "@/stores/onboardingStore";

export type BioStatus = "pending" | "processing" | "completed" | "no_gmail";

export interface PersonalizationData {
  phase?: OnboardingPhase;
  bio_status?: BioStatus;
  has_personalization?: boolean;
  house?: string;
  personality_phrase?: string;
  user_bio?: string;
  account_number?: number;
  member_since?: string;
  name?: string;
  holo_card_id?: string;
  overlay_color?: string;
  overlay_opacity?: number;
  suggested_workflows?: Array<{
    id: string;
    title: string;
    description: string;
    steps: Array<{ tool_category: string }>;
  }>;
}

export interface PersonalizationCompleteMessage {
  type: "onboarding_personalization_complete";
  data: PersonalizationData;
}

export interface BioStatusUpdateMessage {
  type: "bio_status_update";
  data: {
    bio_status: BioStatus;
  };
}

export interface OnboardingPhaseUpdateMessage {
  type: "onboarding_phase_update";
  data: {
    phase: OnboardingPhase;
  };
}

export interface PersonalizationProgressMessage {
  type: "personalization_progress";
  data: {
    stage: string;
    message: string;
    progress: number; // 0-100
    details?: {
      current?: number;
      total?: number;
      platforms?: string[];
    };
  };
}

export type OnboardingWebSocketMessage =
  | PersonalizationCompleteMessage
  | BioStatusUpdateMessage
  | OnboardingPhaseUpdateMessage
  | PersonalizationProgressMessage;

/**
 * Type guard for PersonalizationCompleteMessage
 */
export function isPersonalizationCompleteMessage(
  message: unknown,
): message is PersonalizationCompleteMessage {
  return (
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: string }).type ===
      "onboarding_personalization_complete" &&
    "data" in message
  );
}

/**
 * Type guard for BioStatusUpdateMessage
 */
export function isBioStatusUpdateMessage(
  message: unknown,
): message is BioStatusUpdateMessage {
  return (
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: string }).type === "bio_status_update" &&
    "data" in message &&
    typeof (message as { data?: { bio_status?: string } }).data?.bio_status ===
      "string"
  );
}

/**
 * Type guard for OnboardingPhaseUpdateMessage
 */
export function isOnboardingPhaseUpdateMessage(
  message: unknown,
): message is OnboardingPhaseUpdateMessage {
  return (
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: string }).type === "onboarding_phase_update" &&
    "data" in message &&
    typeof (message as { data?: { phase?: string } }).data?.phase === "string"
  );
}

/**
 * Type guard for PersonalizationProgressMessage
 */
export function isPersonalizationProgressMessage(
  message: unknown,
): message is PersonalizationProgressMessage {
  return (
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: string }).type === "personalization_progress" &&
    "data" in message
  );
}
