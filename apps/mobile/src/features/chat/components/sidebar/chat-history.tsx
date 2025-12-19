import { useState } from "react";
import { ScrollView, TouchableOpacity, View } from "react-native";
import {
  ArrowDown01Icon,
  ArrowUp01Icon,
  BubbleChatIcon,
  FavouriteIcon,
  HugeiconsIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
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

interface CategorySectionProps {
  title: string;
  items: ChatHistoryItem[];
  isExpanded: boolean;
  onToggle: () => void;
  onSelectChat: (chatId: string) => void;
  activeChatId: string | null;
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

function CategorySection({
  title,
  items,
  isExpanded,
  onToggle,
  onSelectChat,
  activeChatId,
}: CategorySectionProps) {
  return (
    <View className="mb-2">
      <TouchableOpacity onPress={onToggle} activeOpacity={0.6}>
        <View className="px-6 py-3 flex-row items-center justify-between opacity-50">
          <Text className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">
            {title}
          </Text>
          <HugeiconsIcon
            icon={isExpanded ? ArrowDown01Icon : ArrowUp01Icon}
            size={12}
            color="#8e8e93"
          />
        </View>
      </TouchableOpacity>

      {isExpanded &&
        items.map((item) => {
          const isActive = activeChatId === item.id;
          return (
            <TouchableOpacity
              key={item.id}
              className={`flex-row items-center px-6 py-2 gap-3 relative ${
                isActive ? "bg-[#103543] rounded-xl" : "bg-transparent"
              }`}
              onPress={() => onSelectChat(item.id)}
              activeOpacity={0.7}
            >
              {isActive && (
                <View className="absolute left-0 top-3 bottom-3 w-1 bg-primary rounded-r-full" />
              )}
              <HugeiconsIcon
                icon={item.isStarred ? FavouriteIcon : BubbleChatIcon}
                size={16}
                color={isActive ? "#ffffff" : "#666666"}
              />
              <Text className={`flex-1`} numberOfLines={1}>
                {item.title}
              </Text>
            </TouchableOpacity>
          );
        })}
    </View>
  );
}

export function ChatHistory({ onSelectChat }: ChatHistoryProps) {
  const { activeChatId } = useChatContext();
  const [expandedSections, setExpandedSections] = useState({
    starred: true,
    today: true,
    yesterday: true,
    allTime: true,
  });

  const toggleSection = (section: keyof typeof expandedSections) => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  return (
    <ScrollView
      className="flex-1"
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{ paddingBottom: 16 }}
    >
      {/* Starred Chats */}
      {starredChats.length > 0 && (
        <CategorySection
          title="Starred Chats"
          items={starredChats}
          isExpanded={expandedSections.starred}
          onToggle={() => toggleSection("starred")}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}

      {/* Today */}
      {todayChats.length > 0 && (
        <CategorySection
          title="Today"
          items={todayChats}
          isExpanded={expandedSections.today}
          onToggle={() => toggleSection("today")}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}

      {/* Yesterday */}
      {yesterdayChats.length > 0 && (
        <CategorySection
          title="Yesterday"
          items={yesterdayChats}
          isExpanded={expandedSections.yesterday}
          onToggle={() => toggleSection("yesterday")}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}

      {/* All Time */}
      {allTimeChats.length > 0 && (
        <CategorySection
          title="All time"
          items={allTimeChats}
          isExpanded={expandedSections.allTime}
          onToggle={() => toggleSection("allTime")}
          onSelectChat={onSelectChat}
          activeChatId={activeChatId}
        />
      )}
    </ScrollView>
  );
}
