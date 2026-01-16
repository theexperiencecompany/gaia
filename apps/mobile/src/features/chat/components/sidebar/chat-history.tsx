import { PressableFeedback } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import {
  BubbleChatIcon,
  FavouriteIcon,
  HugeiconsIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";
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
  return (
    <PressableFeedback onPress={onPress}>
      <View
        className={`flex-row items-center px-6 py-2 gap-3 relative ${
          isActive ? "bg-muted/10 rounded-xl" : ""
        }`}
      >
        <HugeiconsIcon
          icon={item.is_starred ? FavouriteIcon : BubbleChatIcon}
          size={16}
          color={isActive ? "#ffffff" : "#666666"}
        />
        <Text
          numberOfLines={1}
          className={cn("text-sm", {
            "text-foreground": isActive,
            "text-muted": !isActive,
          })}
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
    <View className="mb-2">
      <Pressable
        onPress={onToggle}
        className="flex-row items-center px-6 py-3 opacity-60"
      >
        <Text className="text-xs text-muted">{title}</Text>
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
      <View className="flex-1 justify-center items-center">
        <ActivityIndicator size="small" color="#16c1ff" />
        <Text className="text-muted-foreground mt-3 text-xs">
          Loading conversations...
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View className="flex-1 justify-center items-center p-6">
        <Text className="text-destructive text-xs text-center">{error}</Text>
      </View>
    );
  }

  if (conversations.length === 0) {
    return (
      <View className="flex-1 justify-center items-center p-6">
        <Text className="text-muted-foreground text-sm text-center">
          No conversations yet
        </Text>
        <Text className="text-muted-foreground text-xs text-center mt-2">
          Start a new chat to begin
        </Text>
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1 }} className="px-3">
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
