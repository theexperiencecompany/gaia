import { Card, Chip, PressableFeedback } from "heroui-native";
import { ScrollView, View } from "react-native";
import { AppIcon, Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------
// Matches web `EmailFetchData` (apps/web/src/types/features/mailTypes.ts).

export interface EmailFetchItem {
  from?: string;
  subject?: string;
  time?: string;
  thread_id?: string;
  id?: string;
}

interface EmailFetchCardProps {
  data: EmailFetchItem[];
  onEmailPress?: (email: EmailFetchItem, index: number) => void;
}

// -- Helpers — ported 1:1 from EmailListCard.tsx ------------------------------

function extractSenderName(from: string): string {
  // Quoted name before email: "John Doe" <john@example.com>
  const match = from.match(/^"?([^"<]+)"?\s*</);
  if (match) {
    return match[1].trim();
  }

  // Bare name before angle brackets
  const spaceMatch = from.match(/^([^<]+)\s+</);
  if (spaceMatch) {
    return spaceMatch[1].trim();
  }

  // No name — extract local-part of the email
  const emailMatch = from.match(/<([^>]+)>/);
  if (emailMatch) {
    return emailMatch[1].split("@")[0];
  }

  return from.split("@")[0] || from;
}

function formatTime(time: string | null): string {
  if (!time) return "Yesterday";

  const date = new Date(time);
  if (Number.isNaN(date.getTime())) return time;

  const now = new Date();
  const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) {
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }
  if (diffInHours < 48) {
    return "Yesterday";
  }
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

// -- Email row ----------------------------------------------------------------

interface EmailRowProps {
  email: EmailFetchItem;
  onPress?: () => void;
}

function EmailRow({ email, onPress }: EmailRowProps) {
  const senderName = extractSenderName(email.from || "Unknown Sender");
  const time = formatTime(email.time || null);

  const content = (
    <View className="flex-row items-center gap-3 px-3 py-3">
      {/* Sender — fixed-width column to match web's w-40 */}
      <View style={{ width: 120, flexShrink: 0 }}>
        <Text className="text-sm font-medium text-zinc-300" numberOfLines={1}>
          {senderName}
        </Text>
      </View>

      {/* Subject */}
      <View className="flex-1 min-w-0">
        <Text className="text-sm text-foreground" numberOfLines={1}>
          {email.subject || "Unknown Subject"}
        </Text>
      </View>

      {/* Time */}
      <View style={{ flexShrink: 0 }}>
        <Text className="text-xs text-[#8e8e93]">{time}</Text>
      </View>
    </View>
  );

  if (onPress) {
    return <PressableFeedback onPress={onPress}>{content}</PressableFeedback>;
  }

  return content;
}

// -- Email fetch card ---------------------------------------------------------

const MAX_VISIBLE = 8;

export function EmailFetchCard({ data, onEmailPress }: EmailFetchCardProps) {
  const visibleEmails = data.slice(0, MAX_VISIBLE);
  const overflow = data.length - MAX_VISIBLE;

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] overflow-hidden"
      animation="disable-all"
    >
      {/* Header — matches CollapsibleListWrapper's "N Emails" label */}
      <Card.Header className="px-4 py-3 pb-0">
        <View className="flex-row items-center gap-2">
          <View className="w-7 h-7 rounded-xl bg-primary/15 items-center justify-center">
            <AppIcon icon={Mail01Icon} size={14} color="#00bbff" />
          </View>
          <View className="flex-1 min-w-0">
            <Card.Title>
              {data.length} Email{data.length !== 1 ? "s" : ""}
            </Card.Title>
          </View>
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>Inbox</Chip.Label>
          </Chip>
        </View>
      </Card.Header>

      <Card.Body className="p-0">
        <View
          style={{
            height: 1,
            backgroundColor: "rgba(255,255,255,0.07)",
            marginTop: 12,
          }}
        />

        {data.length === 0 ? (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No emails found</Text>
          </View>
        ) : (
          <ScrollView
            style={{ maxHeight: 380 }}
            nestedScrollEnabled
            showsVerticalScrollIndicator={false}
          >
            {visibleEmails.map((email, index) => {
              const key = `${email.id ?? email.thread_id ?? email.subject ?? "email"}-${index}`;
              return (
                <View key={key}>
                  {index > 0 && (
                    <View
                      style={{
                        height: 1,
                        backgroundColor: "rgba(255,255,255,0.07)",
                        marginHorizontal: 12,
                      }}
                    />
                  )}
                  <EmailRow
                    email={email}
                    onPress={
                      onEmailPress
                        ? () => onEmailPress(email, index)
                        : undefined
                    }
                  />
                </View>
              );
            })}

            {overflow > 0 ? (
              <>
                <View
                  style={{
                    height: 1,
                    backgroundColor: "rgba(255,255,255,0.07)",
                  }}
                />
                <View className="px-4 py-2.5 items-center">
                  <Text className="text-muted text-xs">
                    +{overflow} more email{overflow !== 1 ? "s" : ""}
                  </Text>
                </View>
              </>
            ) : null}
          </ScrollView>
        )}
      </Card.Body>
    </Card>
  );
}
