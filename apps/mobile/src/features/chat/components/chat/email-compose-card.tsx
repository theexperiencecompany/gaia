import { Button, Chip } from "heroui-native";
import { Pressable, ScrollView, View } from "react-native";
import Svg, { Path } from "react-native-svg";
import { AppIcon, PencilEdit01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

function GmailIcon({
  width = 18,
  height = 18,
}: {
  width?: number;
  height?: number;
}) {
  return (
    <Svg width={width} height={height} viewBox="0 0 256 193">
      <Path
        d="M58.182 192.05V93.14L27.507 65.077L0 49.504v125.091c0 9.658 7.825 17.455 17.455 17.455z"
        fill="#4285f4"
      />
      <Path
        d="M197.818 192.05h40.727c9.659 0 17.455-7.826 17.455-17.455V49.505l-31.156 17.837l-27.026 25.798z"
        fill="#34a853"
      />
      <Path
        d="m58.182 93.14l-4.174-38.647l4.174-36.989L128 69.868l69.818-52.364l4.669 34.992l-4.669 40.644L128 145.504z"
        fill="#ea4335"
      />
      <Path
        d="M197.818 17.504V93.14L256 49.504V26.231c0-21.585-24.64-33.89-41.89-20.945z"
        fill="#fbbc04"
      />
      <Path
        d="m0 49.504l26.759 20.07L58.182 93.14V17.504L41.89 5.286C24.61-7.66 0 4.646 0 26.23z"
        fill="#c5221f"
      />
    </Svg>
  );
}

export interface EmailComposeData {
  to: string[];
  subject: string;
  body: string;
  draft_id?: string;
  thread_id?: string;
  bcc?: string[];
  cc?: string[];
  is_html?: boolean;
}

interface EmailComposeCardProps {
  data?: EmailComposeData;
  onSend?: () => void;
  onEditRecipients?: () => void;
  onEditSubject?: () => void;
  onEditBody?: () => void;
}

export const SAMPLE_EMAIL_COMPOSE: EmailComposeData = {
  to: ["sudarshan@gmail.com"],
  subject: "Checking In",
  body: "Hi Sudarshan,\n\nI hope you are doing well! Just wanted to check in and see how you are doing.\n\nBest regards,\n\n[Your Name]",
  thread_id: "",
  bcc: [],
  cc: [],
  is_html: false,
};

const HTML_ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
  "&nbsp;": " ",
};

function stripHtml(input: string): string {
  if (!input) return "";
  return input
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(
      /&(amp|lt|gt|quot|apos|nbsp|#39);/g,
      (match) => HTML_ENTITIES[match] ?? match,
    )
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function Separator() {
  return <View className="h-px bg-zinc-700/50 my-1.5" />;
}

function EditButton({ onPress }: { onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} hitSlop={8} className="p-1">
      <AppIcon icon={PencilEdit01Icon} size={18} color="#71717a" />
    </Pressable>
  );
}

export function EmailComposeCard({
  data = SAMPLE_EMAIL_COMPOSE,
  onSend,
  onEditRecipients,
  onEditSubject,
  onEditBody,
}: EmailComposeCardProps) {
  const isDraft = !!data.draft_id;
  const isReply = !!data.thread_id;
  const hasRecipients = (data.to?.length ?? 0) > 0;
  const toDisplay = data.to?.join(", ") ?? "";
  const bodyText = data.is_html ? stripHtml(data.body) : data.body;

  return (
    <View className="mx-4 my-1 overflow-hidden rounded-2xl bg-zinc-800">
      {/* Header */}
      <View className="px-6 pt-4 pb-2 flex-row items-center gap-2">
        <GmailIcon width={18} height={18} />
        <Text className="text-zinc-100 text-sm font-medium">
          {isDraft ? "Email Draft" : "Compose Email"}
        </Text>
        {isReply && (
          <Chip size="sm" variant="soft" color="accent">
            <Chip.Label>Reply</Chip.Label>
          </Chip>
        )}
      </View>

      {/* Body rows */}
      <View className="px-6">
        {/* To row */}
        <View className="flex-row items-center gap-2 min-h-9">
          <Text className="text-zinc-400 text-sm">To:</Text>
          {hasRecipients ? (
            <>
              <Text
                className="flex-1 text-zinc-100 text-sm font-medium"
                numberOfLines={1}
              >
                {toDisplay}
              </Text>
              <EditButton onPress={onEditRecipients} />
            </>
          ) : (
            <View className="flex-1 flex-row">
              <Button variant="secondary" size="sm" onPress={onEditRecipients}>
                <Button.Label>Add Recipients</Button.Label>
              </Button>
            </View>
          )}
        </View>

        <Separator />

        {/* Subject row */}
        <View className="flex-row items-center gap-2 min-h-9">
          <Text className="text-zinc-400 text-sm">Subject:</Text>
          <Text
            className="flex-1 text-zinc-100 text-sm font-medium"
            numberOfLines={1}
          >
            {data.subject}
          </Text>
          <EditButton onPress={onEditSubject} />
        </View>

        <Separator />

        {/* Body */}
        <View className="relative">
          <View className="absolute top-0 right-0 z-10">
            <EditButton onPress={onEditBody} />
          </View>
          <ScrollView
            style={{ maxHeight: 184 }}
            showsVerticalScrollIndicator={false}
            nestedScrollEnabled
            contentContainerStyle={{ paddingTop: 4, paddingBottom: 8 }}
          >
            <Text className="text-zinc-200 text-sm leading-relaxed pr-8">
              {bodyText}
            </Text>
          </ScrollView>
        </View>
      </View>

      {/* Footer */}
      <View className="flex-row justify-end px-6 pb-5 pt-2">
        <Button
          variant="primary"
          size="sm"
          className="rounded-full px-5"
          onPress={onSend}
          isDisabled={!hasRecipients}
        >
          <Button.Label>{isDraft ? "Send Draft" : "Send"}</Button.Label>
        </Button>
      </View>
    </View>
  );
}
