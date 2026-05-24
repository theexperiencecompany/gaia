import type {
  ChatMessageItem,
  ChatPlatform,
} from "@/features/landing/components/iphone/ChatDemo";

export type PlatformPreviewPlatform = Extract<
  ChatPlatform,
  "telegram" | "whatsapp" | "slack" | "discord"
>;

export type ProfessionArchetype =
  | "builder"
  | "operator"
  | "founder"
  | "scholar"
  | "default";

export interface PlatformScript {
  title: string;
  subtitle?: string;
  messages: ChatMessageItem[];
}

export interface UserIdentity {
  name: string | undefined;
  avatar: string | undefined;
}
