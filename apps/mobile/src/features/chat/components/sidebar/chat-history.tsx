import { useRouter } from "expo-router";
import { PressableFeedback } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import {
  BubbleChatIcon,
  FavouriteIcon,
  HugeiconsIcon,
  TestTube01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useChatContext } from "../../hooks/use-chat-context";
import {
  type Conversation,
  groupConversationsByDate,
  useConversations,
} from "../../hooks/use-conversations";

interface ChatHistoryProps {
  onSelectChat: (chatId: string) => void;
}

interface ChatItemProps {
  item: Conversation;
  isActive: boolean;
  onPress: () => void;
}

function ChatItem({ item, isActive, onPress }: ChatItemProps) {
  const { spacing, fontSize, iconSize } = useResponsive();

  return (
    <PressableFeedback onPress={onPress}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.lg,
          paddingVertical: spacing.sm,
          gap: spacing.md,
          backgroundColor: isActive ? "rgba(255,255,255,0.05)" : "transparent",
          borderRadius: isActive ? 12 : 0,
        }}
      >
        <HugeiconsIcon
          icon={item.is_starred ? FavouriteIcon : BubbleChatIcon}
          size={iconSize.sm}
          color={isActive ? "#ffffff" : "#666666"}
        />
        <Text
          numberOfLines={1}
          style={{
            fontSize: fontSize.sm,
            color: isActive ? "#ffffff" : "#8e8e93",
            flex: 1,
          }}
        >
          {item.title}
        </Text>
      </View>
    </PressableFeedback>
  );
}

interface SectionProps {
  title: string;
  items: Conversation[];
  activeChatId: string | null;
  onSelectChat: (chatId: string) => void;
  isExpanded: boolean;
  onToggle: () => void;
}

function Section({
  title,
  items,
  activeChatId,
  onSelectChat,
  isExpanded,
  onToggle,
}: SectionProps) {
  const { spacing, fontSize } = useResponsive();

  if (items.length === 0) return null;

  return (
    <View style={{ marginBottom: spacing.sm }}>
      <Pressable
        onPress={onToggle}
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.lg,
          paddingVertical: spacing.md,
          opacity: 0.6,
        }}
      >
        <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>{title}</Text>
      </Pressable>
      {isExpanded &&
        items.map((item) => (
          <ChatItem
            key={item.id}
            item={item}
            isActive={activeChatId === item.id}
            onPress={() => onSelectChat(item.id)}
          />
        ))}
    </View>
  );
}

export function ChatHistory({ onSelectChat }: ChatHistoryProps) {
  const router = useRouter();
  const { activeChatId } = useChatContext();
  const { conversations, isLoading, error } = useConversations();
  const { spacing, fontSize, iconSize } = useResponsive();

  const [expandedSections, setExpandedSections] = useState<
    Record<string, boolean>
  >({
    starred: true,
    today: true,
    yesterday: true,
    lastWeek: true,
    previousChats: true,
  });

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const handleSelectChat = (chatId: string) => {
    onSelectChat(chatId);
  };

  const groupedChats = groupConversationsByDate(conversations);

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="small" color="#16c1ff" />
        <Text
          style={{
            color: "#8e8e93",
            marginTop: spacing.md,
            fontSize: fontSize.xs,
          }}
        >
          Loading conversations...
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View
        style={{
          flex: 1,
          justifyContent: "center",
          alignItems: "center",
          padding: spacing.lg,
        }}
      >
        <Text
          style={{
            color: "#ef4444",
            fontSize: fontSize.xs,
            textAlign: "center",
          }}
        >
          {error}
        </Text>
      </View>
    );
  }

  if (conversations.length === 0) {
    return (
      <View
        style={{
          flex: 1,
          justifyContent: "center",
          alignItems: "center",
          padding: spacing.lg,
        }}
      >
        <Text
          style={{
            color: "#8e8e93",
            fontSize: fontSize.sm,
            textAlign: "center",
          }}
        >
          No conversations yet
        </Text>
        <Text
          style={{
            color: "#8e8e93",
            fontSize: fontSize.xs,
            textAlign: "center",
            marginTop: spacing.sm,
          }}
        >
          Start a new chat to begin
        </Text>
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1, paddingHorizontal: spacing.md }}>
      <PressableFeedback onPress={() => router.push("/test")}>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.lg,
            paddingVertical: spacing.sm,
            gap: spacing.md,
            marginBottom: spacing.sm,
          }}
        >
          <HugeiconsIcon
            icon={TestTube01Icon}
            size={iconSize.sm}
            color="#8e8e93"
          />
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#8e8e93",
            }}
          >
            Test
          </Text>
        </View>
      </PressableFeedback>
      <Section
        title="Starred"
        items={groupedChats.starred}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        isExpanded={expandedSections.starred}
        onToggle={() => toggleSection("starred")}
      />
      <Section
        title="Today"
        items={groupedChats.today}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        isExpanded={expandedSections.today}
        onToggle={() => toggleSection("today")}
      />
      <Section
        title="Yesterday"
        items={groupedChats.yesterday}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        isExpanded={expandedSections.yesterday}
        onToggle={() => toggleSection("yesterday")}
      />
      <Section
        title="Last 7 Days"
        items={groupedChats.lastWeek}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        isExpanded={expandedSections.lastWeek}
        onToggle={() => toggleSection("lastWeek")}
      />
      <Section
        title="Previous Chats"
        items={groupedChats.previousChats}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        isExpanded={expandedSections.previousChats}
        onToggle={() => toggleSection("previousChats")}
      />
    </ScrollView>
  );
}
