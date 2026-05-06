import { Button, Chip } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
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
    <Pressable onPress={onPress} hitSlop={12} className="p-2">
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

  const [isSending, setIsSending] = useState(false);
  const sendDisabled = !hasRecipients || isSending;

  const handleSend = async (): Promise<void> => {
    if (!onSend) return;
    setIsSending(true);
    try {
      await onSend();
    } finally {
      setIsSending(false);
    }
  };

  return (
    // Use inline styles for layout-critical parts so the card renders
    // identically regardless of NativeWind class processing. Header icon and
    // footer Send button were both invisible on device when expressed via
    // utility classes — they now use explicit gap/padding/min-height.
    <View
      style={{
        marginHorizontal: 16,
        marginVertical: 4,
        overflow: "hidden",
        borderRadius: 24,
        backgroundColor: "#27272a",
      }}
    >
      {/* Header */}
      <View
        style={{
          paddingHorizontal: 24,
          paddingTop: 14,
          paddingBottom: 8,
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
        }}
      >
        <GmailIcon width={18} height={18} />
        <Text style={{ color: "#f4f4f5", fontSize: 14, fontWeight: "500" }}>
          {isDraft ? "Email Draft" : "Compose Email"}
        </Text>
        {isReply && (
          <Chip size="sm" variant="soft" color="accent">
            <Chip.Label>Reply</Chip.Label>
          </Chip>
        )}
      </View>

      {/* Body rows */}
      <View style={{ paddingHorizontal: 24, gap: 4 }}>
        {/* To row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            minHeight: 40,
          }}
        >
          <Text style={{ fontSize: 14, color: "#a1a1aa" }}>To:</Text>
          {hasRecipients ? (
            <>
              <Text
                style={{
                  flex: 1,
                  fontSize: 14,
                  fontWeight: "500",
                  color: "#e4e4e7",
                }}
                numberOfLines={1}
              >
                {toDisplay}
              </Text>
              <EditIconButton onPress={onEditRecipients} />
            </>
          ) : (
            <View style={{ flex: 1, flexDirection: "row" }}>
              <Button variant="primary" size="sm" onPress={onEditRecipients}>
                <Button.Label>Add Recipients</Button.Label>
              </Button>
            </View>
          )}
        </View>

        <Separator />

        {/* Subject row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            minHeight: 40,
          }}
        >
          <Text style={{ fontSize: 14, color: "#a1a1aa" }}>Subject:</Text>
          <Text
            style={{
              flex: 1,
              fontSize: 14,
              fontWeight: "500",
              color: "#e4e4e7",
            }}
            numberOfLines={1}
          >
            {data.subject}
          </Text>
          <EditIconButton onPress={onEditSubject} />
        </View>

        <Separator />

        {/* Body — scrollable with edit button overlaid top-right */}
        <View style={{ position: "relative" }}>
          <View style={{ position: "absolute", top: 0, right: 0, zIndex: 10 }}>
            <EditIconButton onPress={onEditBody} />
          </View>
          <ScrollView
            style={{ maxHeight: 140 }}
            showsVerticalScrollIndicator={false}
            nestedScrollEnabled
            contentContainerStyle={{ paddingBottom: 20 }}
          >
            <View style={{ paddingRight: 32 }}>
              <MarkdownRenderer content={bodyText} />
            </View>
          </ScrollView>
        </View>
      </View>

      {/* Footer — explicit minHeight guarantees the Send button always has
          space to paint, even if a parent ScrollView/measurement hiccups. */}
      <View
        style={{
          flexDirection: "row",
          justifyContent: "flex-end",
          paddingHorizontal: 24,
          paddingTop: 12,
          paddingBottom: 20,
          minHeight: 64,
        }}
      >
        <Pressable
          onPress={handleSend}
          disabled={sendDisabled}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            // Disabled state uses zinc-600 + zinc-300 so the button stays
            // visibly present against the zinc-800 card bg even when no
            // recipients have been resolved yet.
            backgroundColor: sendDisabled ? "#52525b" : "#00bbff",
            borderRadius: 999,
            paddingHorizontal: 20,
            paddingVertical: 10,
            minHeight: 40,
          }}
        >
          {isSending && <ActivityIndicator size="small" color="#000" />}
          <Text
            style={{
              color: sendDisabled ? "#d4d4d8" : "#000",
              fontSize: 14,
              fontWeight: "600",
            }}
          >
            {isSending ? "Sending..." : isDraft ? "Send Draft" : "Send"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
