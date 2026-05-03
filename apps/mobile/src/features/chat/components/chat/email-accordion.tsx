import { Accordion, Card } from "heroui-native";
import { View } from "react-native";
import { AppIcon, ArrowDown01Icon, Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { Divider } from "@/shared/components/ui/divider";

export interface EmailAccordionItem {
  id: string;
  sender: string;
  subject: string;
  time: string;
  snippet?: string;
}

interface EmailAccordionProps {
  emails: EmailAccordionItem[];
  title?: string;
}

export const SAMPLE_EMAILS: EmailAccordionItem[] = [
  {
    id: "1",
    sender: "Reddit",
    subject: '"Microsoft | L60 | Hyderabad | Offer | 1.5 YOE"',
    time: "Yesterday",
  },
  {
    id: "2",
    sender: "Reddit",
    subject: '"Universal React Monorepo Template with Ne..."',
    time: "Dec 28",
  },
  {
    id: "3",
    sender: "Mail Delivery Subsyst...",
    subject: "Delivery Status Notification (Failure)",
    time: "Dec 28",
  },
  {
    id: "4",
    sender: "ngrok team",
    subject: "Welcome to ngrok!",
    time: "Dec 28",
  },
  {
    id: "5",
    sender: "Reddit",
    subject: '"Why???????"',
    time: "Dec 27",
  },
  {
    id: "6",
    sender: "Reddit",
    subject: '"Steam looks wierd"',
    time: "Dec 26",
  },
];

function EmailItem({ email }: { email: EmailAccordionItem }) {
  return (
    <View className="flex-row items-center py-3">
      <View className="w-28 flex-shrink-0">
        <Text className="text-sm font-medium text-foreground" numberOfLines={1}>
          {email.sender}
        </Text>
      </View>
      <Text className="flex-1 text-sm text-[#71717a] mx-3" numberOfLines={1}>
        {email.subject}
      </Text>
      <Text className="text-xs text-[#71717a]">{email.time}</Text>
    </View>
  );
}

export function EmailAccordion({
  emails = SAMPLE_EMAILS,
  title,
}: EmailAccordionProps) {
  const emailCount = emails.length;
  const displayTitle =
    title || `${emailCount} Email${emailCount !== 1 ? "s" : ""}`;

  return (
    <Accordion selectionMode="single">
      <Accordion.Item value="emails">
        <Accordion.Trigger className="flex-row items-center px-4 py-2.5">
          <View className="flex-row items-center flex-1 gap-2">
            <AppIcon icon={Mail01Icon} size={16} color="#71717a" />
            <Text className="text-sm text-[#71717a]">{displayTitle}</Text>
          </View>
          <AppIcon icon={ArrowDown01Icon} size={14} color="#71717a" />
        </Accordion.Trigger>
        <Accordion.Content>
          <Card
            variant="secondary"
            className="rounded-2xl mx-4 mt-1 mb-2 bg-zinc-900 overflow-hidden"
          >
            <Card.Body className="py-0 px-4">
              {emails.map((email, index) => (
                <View key={email.id}>
                  <EmailItem email={email} />
                  {index < emails.length - 1 ? (
                    <Divider className="bg-zinc-700/50" />
                  ) : null}
                </View>
              ))}
            </Card.Body>
          </Card>
        </Accordion.Content>
      </Accordion.Item>
    </Accordion>
  );
}
