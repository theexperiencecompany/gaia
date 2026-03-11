import { Button, Card } from "heroui-native";
import { ScrollView, View } from "react-native";
import { AppIcon, Mail01Icon, PencilEdit01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

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

function Separator() {
  return <View className="h-px bg-white/10 mx-0" />;
}

function FieldRow({ label, value }: { label: string; value: string }) {
  return (
    <View className="flex-row items-center py-3 px-4">
      <Text className="text-sm text-[#8e8e93]" style={{ width: 64 }}>
        {label}
      </Text>
      <Text className="flex-1 text-sm text-[#e5e5e7]" numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

export function EmailComposeCard({
  data = SAMPLE_EMAIL_COMPOSE,
  onSend,
}: EmailComposeCardProps) {
  const isDraft = !!data.draft_id;
  const isReply = !!data.thread_id;

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl overflow-hidden bg-[#171920]"
    >
      {/* Header */}
      <View className="flex-row items-center justify-between px-4 pt-3 pb-2">
        <View className="flex-row items-center gap-2">
          <AppIcon icon={Mail01Icon} size={18} color="#8e8e93" />
          <Text className="text-sm font-medium text-foreground">
            {isDraft ? "Email Draft" : "Compose Email"}
          </Text>
          {isReply && (
            <View className="rounded-full bg-[#00bbff]/20 px-2 py-0.5">
              <Text className="text-[10px] text-[#00bbff] font-medium">
                Reply
              </Text>
            </View>
          )}
        </View>
        <AppIcon icon={PencilEdit01Icon} size={14} color="#8e8e93" />
      </View>

      <Separator />

      {/* To field */}
      <FieldRow label="To:" value={data.to.join(", ")} />

      <Separator />

      {/* CC field */}
      {data.cc && data.cc.length > 0 && (
        <>
          <FieldRow label="Cc:" value={data.cc.join(", ")} />
          <Separator />
        </>
      )}

      {/* BCC field */}
      {data.bcc && data.bcc.length > 0 && (
        <>
          <FieldRow label="Bcc:" value={data.bcc.join(", ")} />
          <Separator />
        </>
      )}

      {/* Subject field */}
      <View className="flex-row items-center py-3 px-4">
        <Text className="text-sm text-[#8e8e93]" style={{ width: 64 }}>
          Subject:
        </Text>
        <Text
          className="flex-1 text-sm font-medium text-[#e5e5e7]"
          numberOfLines={1}
        >
          {data.subject}
        </Text>
      </View>

      <Separator />

      {/* Body */}
      <ScrollView
        className="px-4 py-3"
        style={{ maxHeight: 160 }}
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
      >
        <Text className="text-sm text-[#e5e5e7] leading-5 whitespace-pre-line">
          {data.body}
        </Text>
      </ScrollView>

      <Separator />

      {/* Send button */}
      <View className="flex-row justify-end px-4 py-3">
        <Button
          variant="primary"
          size="sm"
          className="rounded-full px-5"
          onPress={onSend}
        >
          <Button.Label>{isDraft ? "Send Draft" : "Send"}</Button.Label>
        </Button>
      </View>
    </Card>
  );
}
