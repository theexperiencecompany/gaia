import { Image } from "expo-image";
import { Button, Card } from "heroui-native";
import { ScrollView, View } from "react-native";
import { HugeiconsIcon, PencilEdit01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

interface EmailComposeData {
  to: string[];
  subject: string;
  body: string;
  thread_id?: string;
  bcc?: string[];
  cc?: string[];
  is_html?: boolean;
}

interface EmailComposeCardProps {
  data?: EmailComposeData;
  onEdit?: (field: "to" | "subject" | "body") => void;
  onSend?: () => void;
}

const GMAIL_ICON =
  "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/512px-Gmail_icon_%282020%29.svg.png";

export const SAMPLE_EMAIL_COMPOSE: EmailComposeData = {
  to: ["sudarshan@gmail.com"],
  subject: "Checking In",
  body: "Hi Sudarshan,\n\nI hope you are doing well! Just wanted to check in and see how you are doing.\n\nBest regards,\n\n[Your Name]",
  thread_id: "",
  bcc: [],
  cc: [],
  is_html: false,
};

function EditButton({ onPress }: { onPress?: () => void }) {
  return (
    <Button variant="ghost" isIconOnly size="sm" onPress={onPress}>
      <HugeiconsIcon icon={PencilEdit01Icon} size={16} color="#6b6b6b" />
    </Button>
  );
}

function FieldRow({
  label,
  value,
  onEdit,
}: {
  label: string;
  value: string;
  onEdit?: () => void;
}) {
  return (
    <View className="flex-row items-center py-3 px-4 border-b border-muted/20">
      <Text className="text-muted text-sm" style={{ width: 60 }}>
        {label}
      </Text>
      <Text className="flex-1 text-foreground text-sm" numberOfLines={1}>
        {value}
      </Text>
      <EditButton onPress={onEdit} />
    </View>
  );
}

export function EmailComposeCard({
  data = SAMPLE_EMAIL_COMPOSE,
  onEdit,
  onSend,
}: EmailComposeCardProps) {
  return (
    <Card variant="secondary" className="rounded-xl mx-4 my-2 overflow-hidden">
      <View className="flex-row items-center gap-2 px-4 py-3 border-b border-muted/20">
        <Image
          source={{ uri: GMAIL_ICON }}
          style={{ width: 18, height: 18 }}
          contentFit="contain"
        />
        <Text className="text-foreground text-sm font-medium">
          Compose Email
        </Text>
      </View>

      <FieldRow
        label="To:"
        value={data.to.join(", ")}
        onEdit={() => onEdit?.("to")}
      />

      <FieldRow
        label="Subject:"
        value={data.subject}
        onEdit={() => onEdit?.("subject")}
      />

      <View
        className="flex-row items-start py-3 px-4"
        style={{ maxHeight: 120 }}
      >
        <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false}>
          <Text className="text-foreground text-sm leading-relaxed">
            {data.body}
          </Text>
        </ScrollView>
        <EditButton onPress={() => onEdit?.("body")} />
      </View>

      <View className="flex-row justify-end px-4 py-3">
        <Button
          variant="primary"
          size="sm"
          className="rounded-full"
          onPress={onSend}
        >
          <Button.Label>Send</Button.Label>
        </Button>
      </View>
    </Card>
  );
}
