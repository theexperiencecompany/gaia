import { Pressable, View } from "react-native";
import { AppIcon, BubbleChatIcon, Search01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface SearchResultItemProps {
  conversationId: string;
  title: string;
  snippet: string;
  query: string;
  type: "conversation" | "message";
  timestamp?: string;
  onPress: (conversationId: string) => void;
}

function highlightText(
  text: string,
  query: string,
): Array<{ text: string; highlighted: boolean }> {
  if (!query.trim()) {
    return [{ text, highlighted: false }];
  }

  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`(${escapedQuery})`, "gi");
  const parts = text.split(regex);

  return parts.map((part) => ({
    text: part,
    highlighted: regex.test(part),
  }));
}

export function SearchResultItem({
  conversationId,
  title,
  snippet,
  query,
  type,
  timestamp,
  onPress,
}: SearchResultItemProps) {
  const { spacing, fontSize, iconSize } = useResponsive();

  const titleParts = highlightText(title, query);
  const snippetParts = highlightText(snippet, query);

  const formattedDate = timestamp
    ? new Date(timestamp).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    : null;

  return (
    <Pressable
      onPress={() => onPress(conversationId)}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.sm,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm + 2,
        backgroundColor: pressed ? "rgba(255,255,255,0.04)" : "transparent",
        borderBottomWidth: 1,
        borderBottomColor: "rgba(255,255,255,0.05)",
      })}
    >
      {/* Icon */}
      <View
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          backgroundColor:
            type === "conversation"
              ? "rgba(0,187,255,0.12)"
              : "rgba(255,255,255,0.06)",
          alignItems: "center",
          justifyContent: "center",
          marginTop: 2,
          flexShrink: 0,
        }}
      >
        <AppIcon
          icon={type === "conversation" ? BubbleChatIcon : Search01Icon}
          size={iconSize.sm}
          color={type === "conversation" ? "#00bbff" : "#8e8e93"}
        />
      </View>

      {/* Content */}
      <View style={{ flex: 1, gap: 3 }}>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            gap: spacing.xs,
          }}
        >
          {/* Title with highlight */}
          <Text
            numberOfLines={1}
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#f4f4f5",
              flex: 1,
            }}
          >
            {titleParts.map((part, index) => (
              <Text
                key={index}
                style={{
                  color: part.highlighted ? "#00bbff" : "#f4f4f5",
                  fontWeight: part.highlighted ? "700" : "600",
                }}
              >
                {part.text}
              </Text>
            ))}
          </Text>

          {/* Date */}
          {formattedDate && (
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#52525b",
                flexShrink: 0,
              }}
            >
              {formattedDate}
            </Text>
          )}
        </View>

        {/* Snippet with highlight */}
        {snippet ? (
          <Text
            numberOfLines={2}
            style={{
              fontSize: fontSize.xs + 1,
              color: "#71717a",
              lineHeight: 18,
            }}
          >
            {snippetParts.map((part, index) => (
              <Text
                key={index}
                style={{
                  color: part.highlighted ? "#a1c4fd" : "#71717a",
                  fontWeight: part.highlighted ? "600" : "400",
                }}
              >
                {part.text}
              </Text>
            ))}
          </Text>
        ) : null}

        {/* Type badge */}
        <View
          style={{
            alignSelf: "flex-start",
            paddingHorizontal: 6,
            paddingVertical: 1,
            borderRadius: 4,
            backgroundColor:
              type === "conversation"
                ? "rgba(0,187,255,0.08)"
                : "rgba(255,255,255,0.05)",
          }}
        >
          <Text
            style={{
              fontSize: fontSize.xs - 1,
              color: type === "conversation" ? "#00bbff" : "#52525b",
              fontWeight: "500",
              textTransform: "capitalize",
            }}
          >
            {type}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}
