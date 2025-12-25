import { useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  Text,
  View,
  Pressable,
} from "react-native";
import { useRouter } from "expo-router";
import { PressableFeedback } from "heroui-native";
import {
  BubbleChatIcon,
  FavouriteIcon,
  HugeiconsIcon,
} from "@/components/icons";
import { useChatContext } from "../../hooks/use-chat-context";
import {
  useConversations,
  groupConversationsByDate,
  type Conversation,
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
  return (
    <PressableFeedback onPress={onPress}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: 24,
          paddingVertical: 8,
          gap: 12,
          backgroundColor: isActive ? "#103543" : "transparent",
          borderRadius: isActive ? 12 : 0,
          position: "relative",
        }}
      >
        {isActive && (
          <View
            style={{
              position: "absolute",
              left: 0,
              top: 12,
              bottom: 12,
              width: 3,
              backgroundColor: "#16c1ff",
              borderTopRightRadius: 4,
              borderBottomRightRadius: 4,
            }}
          />
        )}
        <HugeiconsIcon
          icon={item.is_starred ? FavouriteIcon : BubbleChatIcon}
          size={16}
          color={isActive ? "#ffffff" : "#666666"}
        />
        <Text
          style={{
            flex: 1,
            color: isActive ? "#ffffff" : "#cccccc",
            fontSize: 14,
          }}
          numberOfLines={1}
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
  if (items.length === 0) return null;

  return (
    <View style={{ marginBottom: 8 }}>
      <Pressable
        onPress={onToggle}
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: 24,
          paddingVertical: 12,
          opacity: 0.6,
        }}
      >
        <Text
          style={{
            flex: 1,
            fontSize: 10,
            fontWeight: "700",
            color: "#888888",
            textTransform: "uppercase",
            letterSpacing: 2,
          }}
        >
          {title}
        </Text>
        <Text style={{ color: "#888888", fontSize: 12 }}>
          {isExpanded ? "▼" : "▶"}
        </Text>
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
  const { activeChatId } = useChatContext();
  const { conversations, isLoading, error } = useConversations();
  const router = useRouter();

  const [expandedSections, setExpandedSections] = useState<
    Record<string, boolean>
  >({
    starred: true,
    today: true,
    yesterday: true,
    lastWeek: true,
    older: true,
  });

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const handleSelectChat = (chatId: string) => {
    onSelectChat(chatId);
    router.push(`/(app)/(chat)/${chatId}`);
  };

  const groupedChats = groupConversationsByDate(conversations);

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="small" color="#16c1ff" />
        <Text style={{ color: "#888888", marginTop: 12, fontSize: 12 }}>
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
          padding: 24,
        }}
      >
        <Text style={{ color: "#ff6b6b", fontSize: 12, textAlign: "center" }}>
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
          padding: 24,
        }}
      >
        <Text style={{ color: "#888888", fontSize: 14, textAlign: "center" }}>
          No conversations yet
        </Text>
        <Text
          style={{
            color: "#666666",
            fontSize: 12,
            textAlign: "center",
            marginTop: 8,
          }}
        >
          Start a new chat to begin
        </Text>
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1 }}>
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
        title="Older"
        items={groupedChats.older}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        isExpanded={expandedSections.older}
        onToggle={() => toggleSection("older")}
      />
    </ScrollView>
  );
}
