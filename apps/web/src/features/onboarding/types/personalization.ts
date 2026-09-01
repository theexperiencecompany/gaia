/**
 * The `/onboarding/personalization` payload — everything the Gmail
 * intelligence pipeline writes onto the user document, and the shape the
 * holo card (both the settings view and the public `/profile/{id}` page)
 * renders from.
 *
 * Nothing in the onboarding *flow* reads this any more: the pipeline moved
 * to Gmail connect, so these are the holo card's types, not the flow's.
 */

import type { IntegrationRef } from "@/types/features/workflowTypes";

export type OnboardingPhase =
  | "initial"
  | "personalization_pending"
  | "personalization_complete"
  | "getting_started"
  | "completed";

export type House = "frostpeak" | "greenvale" | "mistgrove" | "bluehaven";

export type BioStatus = "pending" | "processing" | "completed" | "no_gmail";

export interface WritingStyleExampleBlocks {
  greeting: string;
  body: string[];
  signoff: string;
  name: string;
}

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
    missing_integrations?: IntegrationRef[];
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
