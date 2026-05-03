import { Button, Chip } from "heroui-native";
import { Pressable, ScrollView, View } from "react-native";
import { AppIcon, PencilEdit01Icon } from "@/components/icons";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import { Text } from "@/components/ui/text";
import { GmailIcon } from "@/features/chat/tool-data/cards/gmail-icon";

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

// ---------------------------------------------------------------------------
// HTML → plain text fallback. Web uses DOMPurify to render sanitized HTML
// inline; on mobile we render through MarkdownRenderer, which expects plain
// text/markdown — so we strip tags first when `is_html` is true.
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Inline pieces ported 1:1 from EmailComposeCard.tsx
// ---------------------------------------------------------------------------

function Separator() {
  return <View className="h-px bg-zinc-700 my-1.5" />;
}

function EditIconButton({ onPress }: { onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} hitSlop={8} className="p-1">
      <AppIcon icon={PencilEdit01Icon} size={20} color="#71717a" />
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Main card — mirrors apps/web EmailComposeCard layout:
// rounded-3xl bg-zinc-800 → header (Gmail icon + label + optional Reply chip)
// → To row → separator → Subject row → separator → Body (scrollable, max-h-46
// = 184px, edit button absolute top-right) → footer (rounded-full Send CTA).
// ---------------------------------------------------------------------------

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
    <View className="mx-4 my-1 overflow-hidden rounded-3xl bg-zinc-800">
      {/* Header */}
      <View className="px-6 py-1">
        <View className="flex-row items-center gap-2 pt-3 pb-2">
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
      </View>

      {/* Body rows */}
      <View className="px-6 gap-1">
        {/* To row */}
        <View className="flex-row items-center gap-2 min-h-9">
          <Text className="text-sm text-zinc-400">To:</Text>
          {hasRecipients ? (
            <>
              <Text
                className="flex-1 text-sm font-medium text-zinc-200"
                numberOfLines={1}
              >
                {toDisplay}
              </Text>
              <EditIconButton onPress={onEditRecipients} />
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
          <Text className="text-sm text-zinc-400">Subject:</Text>
          <Text
            className="flex-1 text-sm font-medium text-zinc-200"
            numberOfLines={1}
          >
            {data.subject}
          </Text>
          <EditIconButton onPress={onEditSubject} />
        </View>

        <Separator />

        {/* Body — scrollable with edit button overlaid top-right */}
        <View className="relative">
          <View className="absolute top-0 right-0 z-10">
            <EditIconButton onPress={onEditBody} />
          </View>
          <ScrollView
            style={{ maxHeight: 184 }}
            showsVerticalScrollIndicator={false}
            nestedScrollEnabled
            contentContainerStyle={{ paddingBottom: 20 }}
          >
            <View className="pr-8">
              <MarkdownRenderer content={bodyText} />
            </View>
          </ScrollView>
        </View>
      </View>

      {/* Footer */}
      <View className="flex-row justify-end px-6 pb-5">
        <Button
          variant="primary"
          className="rounded-full px-5"
          onPress={onSend}
          isDisabled={!hasRecipients}
        >
          <Button.Label className="font-medium">
            {isDraft ? "Send Draft" : "Send"}
          </Button.Label>
        </Button>
      </View>
    </View>
  );
}
