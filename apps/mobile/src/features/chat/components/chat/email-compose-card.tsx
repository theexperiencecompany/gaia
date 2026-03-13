import { Button, Card, Chip, Divider, TextField } from "heroui-native";
import { View } from "react-native";
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

function RecipientChips({ recipients }: { recipients: string[] }) {
  return (
    <View className="flex-row flex-wrap gap-1">
      {recipients.map((recipient) => (
        <Chip key={recipient} size="sm" variant="soft" color="default">
          <Chip.Label>{recipient}</Chip.Label>
        </Chip>
      ))}
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
      <Card.Body className="py-0 px-0">
        <View className="flex-row items-center justify-between px-4 pt-3 pb-2">
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Mail01Icon} size={18} color="#8e8e93" />
            <Text className="text-sm font-medium text-foreground">
              {isDraft ? "Email Draft" : "Compose Email"}
            </Text>
            {isReply && (
              <Chip size="sm" variant="soft" color="accent">
                <Chip.Label>Reply</Chip.Label>
              </Chip>
            )}
          </View>
          <AppIcon icon={PencilEdit01Icon} size={14} color="#8e8e93" />
        </View>

        <Divider className="bg-white/10" />

        {/* To field */}
        <View className="px-4 py-3">
          <TextField>
            <TextField.Label>To</TextField.Label>
            <RecipientChips recipients={data.to} />
          </TextField>
        </View>

        <Divider className="bg-white/10" />

        {/* CC field */}
        {data.cc && data.cc.length > 0 && (
          <>
            <View className="px-4 py-3">
              <TextField>
                <TextField.Label>Cc</TextField.Label>
                <RecipientChips recipients={data.cc} />
              </TextField>
            </View>
            <Divider className="bg-white/10" />
          </>
        )}

        {/* BCC field */}
        {data.bcc && data.bcc.length > 0 && (
          <>
            <View className="px-4 py-3">
              <TextField>
                <TextField.Label>Bcc</TextField.Label>
                <RecipientChips recipients={data.bcc} />
              </TextField>
            </View>
            <Divider className="bg-white/10" />
          </>
        )}

        {/* Subject field */}
        <View className="px-4 py-3">
          <TextField>
            <TextField.Label>Subject</TextField.Label>
            <TextField.Input
              value={data.subject}
              editable={false}
              className="text-sm font-medium"
            />
          </TextField>
        </View>

        <Divider className="bg-white/10" />

        {/* Body */}
        <View className="px-4 py-3">
          <TextField>
            <TextField.Input
              value={data.body}
              editable={false}
              multiline
              numberOfLines={6}
              style={{ maxHeight: 160 }}
              scrollEnabled
              showSoftInputOnFocus={false}
            />
          </TextField>
        </View>

        <Divider className="bg-white/10" />

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
      </Card.Body>
    </Card>
  );
}
