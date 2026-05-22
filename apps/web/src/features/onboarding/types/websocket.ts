/**
 * WebSocket message types for onboarding feature
 */

export type OnboardingPhase =
  | "initial"
  | "personalization_pending"
  | "personalization_complete"
  | "getting_started"
  | "completed";

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
    trigger?: {
      type: string;
      cron_expression?: string;
      timezone?: string;
    };
  }>;
  writing_style?: {
    style_summary: string;
    example?: WritingStyleExampleBlocks | null;
  } | null;
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
  onboarding_todos?: Array<{
    id: string;
    title: string;
    description?: string | null;
    source_email?: { sender: string; subject: string } | null;
  }> | null;
  first_message_conversation_id?: string;
  first_message?: string | null;
}

export interface WritingStyleExampleBlocks {
  greeting: string;
  body: string[];
  signoff: string;
  name: string;
}

export interface WritingStyleResults {
  style_summary: string;
  example?: WritingStyleExampleBlocks | null;
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
    trigger?: {
      type: string;
      cron_expression?: string;
      timezone?: string;
    };
  }>;
}

export type OnboardingStage =
  | "inbox_scanning"
  | "writing_style_progress"
  | "writing_style_ready"
  | "social_profiles_ready"
  | "triage_analyzing"
  | "triage_ready"
  | "todos_creating"
  | "todos_ready"
  | "workflows_creating"
  | "workflows_ready"
  | "holo_ready"
  | "complete";

export interface StagePayloads {
  inbox_scanning: { status_text: string };
  writing_style_progress: { status_text: string };
  writing_style_ready: {
    style_summary: string | null;
    example?: WritingStyleExampleBlocks | null;
  };
  social_profiles_ready: SocialProfilesResults;
  triage_analyzing: { status_text: string };
  triage_ready: TriageResults;
  todos_creating: { status_text: string };
  todos_ready: TodoResults & { status_text?: string };
  workflows_creating: { status_text: string };
  workflows_ready: WorkflowResults & { status_text?: string };
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
