import { Image } from "expo-image";
import { Accordion, Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

interface Email {
  id: string;
  sender: string;
  subject: string;
  time: string;
}

interface EmailAccordionProps {
  emails: Email[];
  title?: string;
  icon?: string;
}

const GMAIL_ICON =
  "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/512px-Gmail_icon_%282020%29.svg.png";

export const SAMPLE_EMAILS: Email[] = [
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

function EmailItem({ email }: { email: Email }) {
  return (
    <View className="flex-row items-center py-3 px-4">
      <Text className="text-foreground text-sm w-28" numberOfLines={1}>
        {email.sender}
      </Text>
      <Text className="flex-1 text-muted text-sm mx-3" numberOfLines={1}>
        {email.subject}
      </Text>
      <Text className="text-muted text-xs">{email.time}</Text>
    </View>
  );
}

export function EmailAccordion({
  emails = SAMPLE_EMAILS,
  title,
  icon = GMAIL_ICON,
}: EmailAccordionProps) {
  const emailCount = emails.length;
  const displayTitle = title || `Hide ${emailCount} Emails`;

  return (
    <Accordion selectionMode="single">
      <Accordion.Item value="emails">
        <Accordion.Trigger className="flex-row items-center px-4 py-2">
          <View className="flex-row items-center flex-1 gap-2">
            <Image
              source={{ uri: icon }}
              style={{ width: 18, height: 18 }}
              contentFit="contain"
            />
            <Text className="text-muted text-sm">{displayTitle}</Text>
          </View>
          <Accordion.Indicator />
        </Accordion.Trigger>
        <Accordion.Content>
          <Card
            variant="secondary"
            className="rounded-xl mx-4 mt-2 overflow-hidden"
          >
            <Card.Body className="p-0">
              {emails.map((email) => (
                <EmailItem key={email.id} email={email} />
              ))}
            </Card.Body>
          </Card>
        </Accordion.Content>
      </Accordion.Item>
    </Accordion>
  );
}
