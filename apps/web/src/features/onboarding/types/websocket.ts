/**
 * WebSocket message types for onboarding feature
 */

import type { OnboardingPhase } from "@/stores/onboardingStore";

export type House = "frostpeak" | "greenvale" | "mistgrove" | "bluehaven";

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
    steps: Array<{ category: string }>;
  }>;
  // Stage data for reveal card reconstruction on page reload
  writing_style?: { style_summary: string; sample_snippets?: string[] } | null;
  social_profiles?: Array<{ platform: string; url: string }> | null;
  triage_summary?: {
    total_scanned: number;
    total_unread: number;
    summary?: string;
    patterns?: string[];
    important_emails: Array<{
      sender: string;
      subject: string;
      why_important: string;
    }>;
  } | null;
  onboarding_todos?: Array<{ id: string; title: string }> | null;
  first_message_conversation_id?: string;
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

export interface InboxScanResults {
  email_count: number;
}

export interface WritingStyleResults {
  style_summary: string;
  sample_snippets?: string[];
}

export interface SocialProfileResult {
  platform: string;
  url: string;
}

export interface SocialProfilesResults {
  profiles: SocialProfileResult[];
}

export interface TriageResults {
  total_scanned: number;
  total_unread: number;
  email_count?: number;
  summary?: string;
  patterns?: string[];
  important_emails: Array<{
    sender: string;
    subject: string;
    why_important: string;
  }>;
}

export interface TodoResults {
  todos: Array<{
    id: string;
    title: string;
    source_email?: { sender: string; subject: string };
  }>;
}

export interface WorkflowResults {
  workflows: Array<{ id?: string; title: string; description?: string }>;
}

export type ProgressResults =
  | InboxScanResults
  | WritingStyleResults
  | SocialProfilesResults
  | TriageResults
  | TodoResults
  | WorkflowResults;

export interface PersonalizationProgressMessage {
  type: "personalization_progress";
  data: {
    stage: string;
    message: string;
    progress: number; // 0-100
    results?: ProgressResults;
    details?: {
      current?: number;
      total?: number;
      platforms?: string[];
    };
  };
}

export interface IntelligenceCompleteMessage {
  type: "onboarding_intelligence_complete";
  data: {
    conversation_id: string;
  };
}

export type OnboardingWebSocketMessage =
  | PersonalizationCompleteMessage
  | BioStatusUpdateMessage
  | OnboardingPhaseUpdateMessage
  | PersonalizationProgressMessage
  | IntelligenceCompleteMessage;

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
