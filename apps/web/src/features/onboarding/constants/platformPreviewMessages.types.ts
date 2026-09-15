import type {
  ChatMessageItem,
  ChatPlatform,
} from "@/features/landing/components/iphone/ChatDemo";

export type PlatformPreviewPlatform = Extract<
  ChatPlatform,
  "telegram" | "whatsapp" | "imessage"
>;

export interface PlatformScript {
  title: string;
  subtitle?: string;
  messages: ChatMessageItem[];
}

export interface UserIdentity {
  /** Given name for GAIA's lines; absent for an email-only account. */
  firstName: string | undefined;
}
