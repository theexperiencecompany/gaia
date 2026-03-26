import { Card, Chip, Divider, PressableFeedback } from "heroui-native";
import { View } from "react-native";
import { AppIcon, Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface EmailFetchItem {
  from?: string;
  from_name?: string;
  subject?: string;
  snippet?: string;
  date?: string;
  is_unread?: boolean;
}

function formatRelativeDate(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return dateStr;
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function extractFromName(from?: string, fromName?: string): string {
  if (fromName) return fromName;
  if (!from) return "Unknown";
  const match = from.match(/^([^<]+)</);
  if (match) return match[1].trim();
  return from;
}

interface EmailRowProps {
  email: EmailFetchItem;
  onOpenThread?: () => void;
}

function EmailRow({ email, onOpenThread }: EmailRowProps) {
  const senderName = extractFromName(email.from, email.from_name);
  const relativeDate = formatRelativeDate(email.date);

  return (
    <PressableFeedback onPress={onOpenThread} className="px-4 py-3">
      <View className="flex-row items-start">
        <View className="mr-3 mt-1.5">
          {email.is_unread ? (
            <View className="w-2 h-2 rounded-full bg-primary" />
          ) : (
            <View className="w-2 h-2" />
          )}
        </View>
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center justify-between mb-0.5">
            <Text
              className={`text-sm flex-1 mr-2 ${email.is_unread ? "text-foreground font-semibold" : "text-foreground"}`}
              numberOfLines={1}
            >
              {senderName}
            </Text>
            <Text className="text-[#8e8e93] text-xs shrink-0">
              {relativeDate}
            </Text>
          </View>
          <Text
            className={`text-sm mb-0.5 ${email.is_unread ? "text-foreground font-medium" : "text-foreground/80"}`}
            numberOfLines={1}
          >
            {email.subject || "No Subject"}
          </Text>
          {email.snippet && (
            <Text className="text-[#8e8e93] text-xs" numberOfLines={2}>
              {email.snippet}
            </Text>
          )}
        </View>
      </View>
    </PressableFeedback>
  );
}

export function EmailFetchCard({ data }: { data: EmailFetchItem[] }) {
  const unreadCount = data.filter((e) => e.is_unread).length;

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] overflow-hidden"
    >
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={Mail01Icon} size={14} color="#8e8e93" />
          <Text className="text-xs text-[#8e8e93] flex-1">
            {data.length} Email{data.length !== 1 ? "s" : ""}
          </Text>
          {unreadCount > 0 && (
            <Chip size="sm" variant="soft" color="accent">
              <Chip.Label>{unreadCount} unread</Chip.Label>
            </Chip>
          )}
        </View>
        <View className="rounded-xl bg-white/5 border border-white/8 overflow-hidden">
          {data.slice(0, 5).map((email, index) => (
            <View key={`email-${email.subject || index}`}>
              {index > 0 && <Divider className="bg-white/8" />}
              <EmailRow email={email} />
            </View>
          ))}
          {data.length > 5 && (
            <>
              <Divider className="bg-white/8" />
              <View className="px-4 py-2">
                <Text className="text-[#8e8e93] text-xs text-center">
                  +{data.length - 5} more emails
                </Text>
              </View>
            </>
          )}
        </View>
      </Card.Body>
    </Card>
  );
}
