import { useState } from "react";
import { ScrollView, Text, View, Pressable } from "react-native";
import { PressableFeedback } from "heroui-native";
import {
  BubbleChatIcon,
  FavouriteIcon,
  HugeiconsIcon,
} from "@/components/icons";
import { useChatContext } from "../../hooks/use-chat-context";

interface ChatHistoryItem {
  id: string;
  title: string;
  timestamp: Date;
  isStarred?: boolean;
}

interface ChatHistoryProps {
  onSelectChat: (chatId: string) => void;
}

// Mock data - replace with actual chat history
const starredChats: ChatHistoryItem[] = [
  {
    id: "s1",
    title: "this is random chat",
    timestamp: new Date(),
    isStarred: true,
  },
];

const todayChats: ChatHistoryItem[] = [
  { id: "t1", title: "Greeting message", timestamp: new Date() },
];

const yesterdayChats: ChatHistoryItem[] = [
  { id: "y1", title: "Greeting message", timestamp: new Date() },
];

const allTimeChats: ChatHistoryItem[] = [
  { id: "a1", title: "Casual greeting", timestamp: new Date() },
  { id: "a2", title: "hello message text", timestamp: new Date() },
  { id: "a3", title: "hello message example", timestamp: new Date() },
  { id: "a4", title: "General greeting", timestamp: new Date() },
  { id: "a5", title: "General greeting message re", timestamp: new Date() },
  { id: "a6", title: "this is random chat", timestamp: new Date() },
];

interface ChatItemProps {
  item: ChatHistoryItem;
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
          icon={item.isStarred ? FavouriteIcon : BubbleChatIcon}
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
  items: ChatHistoryItem[];
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
  const [expandedSections, setExpandedSections] = useState<
    Record<string, boolean>
  >({
    starred: true,
    today: true,
    yesterday: true,
    allTime: true,
  });

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  return (
    <ScrollView style={{ flex: 1 }}>
      <Section
        title="Starred Chats"
        items={starredChats}
        activeChatId={activeChatId}
        onSelectChat={onSelectChat}
        isExpanded={expandedSections.starred}
        onToggle={() => toggleSection("starred")}
      />
      <Section
        title="Today"
        items={todayChats}
        activeChatId={activeChatId}
        onSelectChat={onSelectChat}
        isExpanded={expandedSections.today}
        onToggle={() => toggleSection("today")}
      />
      <Section
        title="Yesterday"
        items={yesterdayChats}
        activeChatId={activeChatId}
        onSelectChat={onSelectChat}
        isExpanded={expandedSections.yesterday}
        onToggle={() => toggleSection("yesterday")}
      />
      <Section
        title="All Time"
        items={allTimeChats}
        activeChatId={activeChatId}
        onSelectChat={onSelectChat}
        isExpanded={expandedSections.allTime}
        onToggle={() => toggleSection("allTime")}
      />
    </ScrollView>
  );
}
