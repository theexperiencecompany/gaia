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
  writing_style?: { style_summary: string; example?: string } | null;
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

// ── Per-reveal-card payload types (consumed by reveal components) ──────────

export interface WritingStyleResults {
  style_summary: string;
  example?: string;
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
  workflows: Array<{
    id?: string;
    title: string;
    description?: string;
    categories?: string[];
  }>;
}

// ── DAG stage events (new event model) ─────────────────────────────────────

export type OnboardingStage =
  | "inbox_scanning"
  | "writing_style_ready"
  | "social_profiles_ready"
  | "triage_analyzing"
  | "triage_analyzed"
  | "triage_ready"
  | "todos_creating"
  | "todos_ready"
  | "workflows_ready"
  | "holo_ready"
  | "complete";

export interface StagePayloads {
  inbox_scanning: { current: number };
  writing_style_ready: {
    style_summary: string | null;
    example?: string | null;
  };
  social_profiles_ready: SocialProfilesResults;
  triage_analyzing: { total_emails: number; status: string };
  triage_analyzed: { important_count: number; status: string };
  triage_ready: TriageResults;
  todos_creating: { status: string };
  todos_ready: TodoResults;
  workflows_ready: WorkflowResults;
  holo_ready: Record<string, never>;
  complete: { conversation_id: string | null };
}

export type OnboardingStageEvent = {
  type: "onboarding_stage";
  data: {
    [K in OnboardingStage]: {
      stage: K;
      payload: StagePayloads[K];
    };
  }[OnboardingStage];
};

export type StageBuffer = {
  [K in OnboardingStage]?: StagePayloads[K];
};

// ── Phase update event (used by root layout for global phase tracking) ────

export interface OnboardingPhaseUpdateMessage {
  type: "onboarding_phase_update";
  data: {
    phase: OnboardingPhase;
  };
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
 * Type guard for OnboardingStageEvent
 */
export function isOnboardingStageEvent(
  message: unknown,
): message is OnboardingStageEvent {
  return (
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: string }).type === "onboarding_stage" &&
    "data" in message &&
    typeof (message as { data?: { stage?: string } }).data?.stage === "string"
  );
}
