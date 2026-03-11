import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import {
  Button,
  Card,
  Divider,
  PressableFeedback,
  SkeletonGroup,
} from "heroui-native";
import { useCallback, useRef, useState } from "react";
import {
  Alert,
  FlatList,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import ReanimatedSwipeable, {
  type SwipeableMethods,
} from "react-native-gesture-handler/ReanimatedSwipeable";
import Reanimated, {
  type SharedValue,
  useAnimatedStyle,
} from "react-native-reanimated";
import {
  AppIcon,
  BubbleChatIcon,
  Delete02Icon,
  FavouriteIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useChatStore } from "@/stores/chat-store";
import {
  deleteConversation,
  renameConversation,
  toggleStarConversation,
} from "../../api/chat-api";
import { useChatQueryClient } from "../../api/queries";
import { useChatContext } from "../../hooks/use-chat-context";
import {
  type Conversation,
  groupConversationsByDate,
  useConversations,
} from "../../hooks/use-conversations";

interface ChatHistoryProps {
  onSelectChat: (chatId: string) => void;
  searchQuery: string;
}

interface RenameModalProps {
  visible: boolean;
  currentTitle: string;
  onConfirm: (newTitle: string) => void;
  onCancel: () => void;
}

function RenameModal({
  visible,
  currentTitle,
  onConfirm,
  onCancel,
}: RenameModalProps) {
  const [value, setValue] = useState(currentTitle);
  const { spacing, fontSize } = useResponsive();

  const handleConfirm = () => {
    const trimmed = value.trim();
    if (trimmed) {
      onConfirm(trimmed);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onCancel}
    >
      <Pressable
        style={{
          flex: 1,
          backgroundColor: "rgba(0,0,0,0.6)",
          justifyContent: "center",
          alignItems: "center",
          padding: spacing.lg,
        }}
        onPress={onCancel}
      >
        <Pressable
          style={{
            backgroundColor: "#18181b",
            borderRadius: 12,
            padding: spacing.lg,
            width: "100%",
            maxWidth: 360,
            borderWidth: 1,
            borderColor: "#27272a",
          }}
          onPress={() => {}}
        >
          <Text
            style={{
              fontSize: fontSize.md,
              color: "#ffffff",
              fontWeight: "600",
              marginBottom: spacing.xs,
            }}
          >
            Rename Conversation
          </Text>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#71717a",
              marginBottom: spacing.md,
            }}
          >
            Enter a new name for this conversation
          </Text>
          <TextInput
            value={value}
            onChangeText={setValue}
            autoFocus
            selectTextOnFocus
            style={{
              backgroundColor: "#09090b",
              borderWidth: 1,
              borderColor: "#27272a",
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm + 2,
              color: "#ffffff",
              fontSize: fontSize.sm,
              marginBottom: spacing.md,
            }}
            placeholderTextColor="#52525b"
            placeholder="Conversation name"
            onSubmitEditing={handleConfirm}
            returnKeyType="done"
          />
          <View
            style={{
              flexDirection: "row",
              justifyContent: "flex-end",
              gap: spacing.sm,
            }}
          >
            <Button variant="ghost" size="sm" onPress={onCancel}>
              <Button.Label>Cancel</Button.Label>
            </Button>
            <Button variant="primary" size="sm" onPress={handleConfirm}>
              <Button.Label>Save</Button.Label>
            </Button>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

interface DeleteSwipeActionProps {
  dragX: SharedValue<number>;
  onDelete: () => void;
}

function DeleteSwipeAction({ dragX, onDelete }: DeleteSwipeActionProps) {
  const { iconSize } = useResponsive();
  const animatedStyle = useAnimatedStyle(() => ({
    opacity: Math.min(1, Math.abs(dragX.value) / 60),
  }));

  return (
    <Reanimated.View
      style={[
        {
          justifyContent: "center",
          alignItems: "center",
          width: 72,
          borderRadius: 8,
          marginVertical: 1,
          marginRight: 4,
          overflow: "hidden",
        },
        animatedStyle,
      ]}
    >
      <Button
        variant="danger"
        onPress={onDelete}
        className="flex-1 w-full rounded-lg items-center justify-center"
      >
        <AppIcon icon={Delete02Icon} size={iconSize.sm} color="#ffffff" />
        <Text style={{ color: "#ffffff", fontSize: 10, marginTop: 2 }}>
          Delete
        </Text>
      </Button>
    </Reanimated.View>
  );
}

interface HighlightedTextProps {
  text: string;
  query: string;
  baseStyle: object;
  numberOfLines?: number;
}

function HighlightedText({
  text,
  query,
  baseStyle,
  numberOfLines,
}: HighlightedTextProps) {
  if (!query.trim()) {
    return (
      <Text numberOfLines={numberOfLines} style={baseStyle}>
        {text}
      </Text>
    );
  }

  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const parts: { text: string; highlighted: boolean }[] = [];
  let lastIndex = 0;

  let matchIndex = lowerText.indexOf(lowerQuery, lastIndex);
  while (matchIndex !== -1) {
    if (matchIndex > lastIndex) {
      parts.push({
        text: text.slice(lastIndex, matchIndex),
        highlighted: false,
      });
    }
    parts.push({
      text: text.slice(matchIndex, matchIndex + lowerQuery.length),
      highlighted: true,
    });
    lastIndex = matchIndex + lowerQuery.length;
    matchIndex = lowerText.indexOf(lowerQuery, lastIndex);
  }
  if (lastIndex < text.length) {
    parts.push({ text: text.slice(lastIndex), highlighted: false });
  }

  if (parts.length === 0) {
    return (
      <Text numberOfLines={numberOfLines} style={baseStyle}>
        {text}
      </Text>
    );
  }

  return (
    <Text numberOfLines={numberOfLines} style={baseStyle}>
      {parts.map((part, i) =>
        part.highlighted ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: stable index for highlight parts
          <Text key={i} style={{ color: "#00bbff", fontWeight: "600" }}>
            {part.text}
          </Text>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: stable index for plain parts
          <Text key={i}>{part.text}</Text>
        ),
      )}
    </Text>
  );
}

interface ChatItemProps {
  item: Conversation;
  isActive: boolean;
  isStreaming: boolean;
  onPress: () => void;
  onRename: (id: string, currentTitle: string) => void;
  onDelete: (id: string) => void;
  onToggleStar: (id: string, currentStarred: boolean) => void;
  searchQuery?: string;
}

function ChatItem({
  item,
  isActive,
  isStreaming,
  onPress,
  onRename,
  onDelete,
  onToggleStar,
  searchQuery = "",
}: ChatItemProps) {
  const { spacing, fontSize, iconSize } = useResponsive();
  const swipeableRef = useRef<SwipeableMethods>(null);

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);

    if (diffMins < 1) return "now";
    if (diffMins < 60) return `${diffMins}m`;
    if (diffHours < 24) return `${diffHours}h`;
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  };

  const handleLongPress = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    Alert.alert(item.title, undefined, [
      {
        text: item.is_starred ? "Unstar" : "Star",
        onPress: () => onToggleStar(item.id, !!item.is_starred),
      },
      {
        text: "Rename",
        onPress: () => onRename(item.id, item.title),
      },
      {
        text: "Delete",
        onPress: () => onDelete(item.id),
        style: "destructive",
      },
      { text: "Cancel", style: "cancel" },
    ]);
  };

  const handlePress = () => {
    Haptics.selectionAsync();
    onPress();
  };

  const handleSwipeDelete = () => {
    swipeableRef.current?.close();
    onDelete(item.id);
  };

  const renderRightActions = (
    _progress: SharedValue<number>,
    dragX: SharedValue<number>,
  ) => <DeleteSwipeAction dragX={dragX} onDelete={handleSwipeDelete} />;

  return (
    <ReanimatedSwipeable
      ref={swipeableRef}
      renderRightActions={renderRightActions}
      rightThreshold={40}
      overshootRight={false}
    >
      <PressableFeedback onPress={handlePress} onLongPress={handleLongPress}>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm + 2,
            gap: spacing.sm,
            backgroundColor: isActive
              ? "rgba(255,255,255,0.08)"
              : "transparent",
            borderRadius: 8,
            marginHorizontal: spacing.xs,
          }}
        >
          {isStreaming && (
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                backgroundColor: "#00bbff",
              }}
            />
          )}
          {!isStreaming && item.is_unread && (
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                backgroundColor: "#00bbff",
              }}
            />
          )}
          {item.is_starred && (
            <AppIcon
              icon={FavouriteIcon}
              size={iconSize.sm - 2}
              color="#f59e0b"
            />
          )}
          <HighlightedText
            text={item.title}
            query={searchQuery}
            baseStyle={{
              fontSize: fontSize.sm,
              color: isActive
                ? "#ffffff"
                : item.is_unread
                  ? "#ffffff"
                  : "#a1a1aa",
              fontWeight: item.is_unread ? "600" : "400",
              flex: 1,
            }}
            numberOfLines={1}
          />
          <Text
            style={{
              fontSize: fontSize.xs - 1,
              color: "#52525b",
            }}
          >
            {formatTime(item.updated_at || item.created_at)}
          </Text>
        </View>
      </PressableFeedback>
    </ReanimatedSwipeable>
  );
}

interface SectionProps {
  title: string;
  items: Conversation[];
  activeChatId: string | null;
  streamingConversationId: string | null;
  onSelectChat: (chatId: string) => void;
  onRename: (id: string, currentTitle: string) => void;
  onDelete: (id: string) => void;
  onToggleStar: (id: string, currentStarred: boolean) => void;
  isExpanded: boolean;
  onToggle: () => void;
}

function Section({
  title,
  items,
  activeChatId,
  streamingConversationId,
  onSelectChat,
  onRename,
  onDelete,
  onToggleStar,
  isExpanded,
  onToggle,
}: SectionProps) {
  const { spacing, fontSize } = useResponsive();

  if (items.length === 0) return null;

  return (
    <View style={{ marginBottom: 2 }}>
      <Divider className="mx-3 mb-1" />
      <PressableFeedback
        onPress={onToggle}
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#52525b",
            fontWeight: "500",
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          {title}
        </Text>
      </PressableFeedback>
      {isExpanded &&
        items.map((item) => (
          <ChatItem
            key={item.id}
            item={item}
            isActive={activeChatId === item.id}
            isStreaming={streamingConversationId === item.id}
            onPress={() => onSelectChat(item.id)}
            onRename={onRename}
            onDelete={onDelete}
            onToggleStar={onToggleStar}
          />
        ))}
    </View>
  );
}

function ChatHistorySkeleton() {
  const { spacing } = useResponsive();
  return (
    <SkeletonGroup isLoading className="gap-0">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <View
          key={i}
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm + 2,
            gap: spacing.sm,
            marginHorizontal: spacing.xs,
          }}
        >
          <SkeletonGroup.Item
            className="rounded-full"
            style={{ width: 8, height: 8 }}
          />
          <SkeletonGroup.Item
            className="rounded-md flex-1"
            style={{ height: 14 }}
          />
          <SkeletonGroup.Item
            className="rounded-md"
            style={{ width: 28, height: 10 }}
          />
        </View>
      ))}
    </SkeletonGroup>
  );
}

export function ChatHistory({ onSelectChat, searchQuery }: ChatHistoryProps) {
  const router = useRouter();
  const { activeChatId } = useChatContext();
  const { conversations, isLoading, error, refetch } = useConversations();
  const { spacing, fontSize } = useResponsive();
  const { invalidateConversations } = useChatQueryClient();
  const streamingConversationId = useChatStore(
    (state) => state.streamingState.conversationId,
  );
  const removeConversation = useChatStore((state) => state.removeConversation);
  const updateConversationTitle = useChatStore(
    (state) => state.updateConversationTitle,
  );
  const updateConversationStarred = useChatStore(
    (state) => state.updateConversationStarred,
  );

  const [expandedSections, setExpandedSections] = useState<
    Record<string, boolean>
  >({
    starred: true,
    today: true,
    yesterday: true,
    lastWeek: true,
    last30Days: true,
    older: true,
  });

  const [renameModal, setRenameModal] = useState<{
    visible: boolean;
    conversationId: string;
    currentTitle: string;
  }>({ visible: false, conversationId: "", currentTitle: "" });

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const handleSelectChat = useCallback(
    (chatId: string) => {
      onSelectChat(chatId);
      router.push(`/(app)/c/${chatId}`);
    },
    [onSelectChat, router],
  );

  const handleRename = useCallback(
    (conversationId: string, currentTitle: string) => {
      if (Platform.OS === "ios") {
        Alert.prompt(
          "Rename Conversation",
          "Enter a new name for this conversation",
          [
            { text: "Cancel", style: "cancel" },
            {
              text: "Save",
              onPress: async (newName?: string) => {
                if (!newName || newName.trim() === "") return;
                const trimmedName = newName.trim();
                updateConversationTitle(conversationId, trimmedName);
                try {
                  await renameConversation(conversationId, trimmedName);
                  invalidateConversations();
                } catch {
                  updateConversationTitle(conversationId, currentTitle);
                }
              },
            },
          ],
          "plain-text",
          currentTitle,
        );
      } else {
        setRenameModal({ visible: true, conversationId, currentTitle });
      }
    },
    [updateConversationTitle, invalidateConversations],
  );

  const handleRenameConfirm = useCallback(
    async (newTitle: string) => {
      const { conversationId, currentTitle } = renameModal;
      setRenameModal((prev) => ({ ...prev, visible: false }));
      updateConversationTitle(conversationId, newTitle);
      try {
        await renameConversation(conversationId, newTitle);
        invalidateConversations();
      } catch {
        updateConversationTitle(conversationId, currentTitle);
      }
    },
    [renameModal, updateConversationTitle, invalidateConversations],
  );

  const handleRenameCancel = useCallback(() => {
    setRenameModal((prev) => ({ ...prev, visible: false }));
  }, []);

  const handleDelete = useCallback(
    (conversationId: string) => {
      Alert.alert(
        "Delete Conversation",
        "Are you sure you want to delete this conversation? This action cannot be undone.",
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Delete",
            style: "destructive",
            onPress: async () => {
              removeConversation(conversationId);
              try {
                await deleteConversation(conversationId);
                invalidateConversations();
              } catch {
                refetch();
              }
            },
          },
        ],
      );
    },
    [removeConversation, invalidateConversations, refetch],
  );

  const handleToggleStar = useCallback(
    async (conversationId: string, currentStarred: boolean) => {
      const newStarred = !currentStarred;
      updateConversationStarred(conversationId, newStarred);
      try {
        await toggleStarConversation(conversationId, newStarred);
        invalidateConversations();
      } catch {
        updateConversationStarred(conversationId, currentStarred);
      }
    },
    [updateConversationStarred, invalidateConversations],
  );

  const isSearching = searchQuery.trim().length > 0;

  const filteredConversations = isSearching
    ? conversations.filter((c) =>
        c.title.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : conversations;

  const groupedChats = groupConversationsByDate(filteredConversations);

  const renderSearchItem = useCallback(
    ({ item }: { item: Conversation }) => (
      <ChatItem
        item={item}
        isActive={activeChatId === item.id}
        isStreaming={streamingConversationId === item.id}
        onPress={() => handleSelectChat(item.id)}
        onRename={handleRename}
        onDelete={handleDelete}
        onToggleStar={handleToggleStar}
        searchQuery={searchQuery}
      />
    ),
    [
      activeChatId,
      streamingConversationId,
      handleSelectChat,
      handleRename,
      handleDelete,
      handleToggleStar,
      searchQuery,
    ],
  );

  const keyExtractor = useCallback((item: Conversation) => item.id, []);

  if (isLoading) {
    return <ChatHistorySkeleton />;
  }

  if (error) {
    return (
      <Card
        variant="secondary"
        className="flex-1 items-center justify-center mx-3 rounded-2xl"
      >
        <Card.Body className="items-center justify-center p-4">
          <Card.Description className="text-center text-danger">
            {error}
          </Card.Description>
        </Card.Body>
      </Card>
    );
  }

  if (filteredConversations.length === 0 && isSearching) {
    return (
      <Card
        variant="secondary"
        className="flex-1 items-center justify-center mx-3 rounded-2xl"
      >
        <Card.Body className="items-center justify-center gap-1 p-4">
          <Card.Title className="text-center">No results found</Card.Title>
          <Card.Description className="text-center">
            Try a different search term
          </Card.Description>
        </Card.Body>
      </Card>
    );
  }

  if (conversations.length === 0) {
    return (
      <Card
        variant="secondary"
        className="flex-1 items-center justify-center mx-3 rounded-2xl"
      >
        <Card.Body className="items-center justify-center gap-3 py-10 px-5">
          <Card
            variant="secondary"
            className="w-14 h-14 rounded-full items-center justify-center"
          >
            <Card.Body className="items-center justify-center p-0">
              <AppIcon icon={BubbleChatIcon} size={28} color="#3f3f46" />
            </Card.Body>
          </Card>
          <Card.Title className="text-center">No conversations yet</Card.Title>
          <Card.Description className="text-center">
            Start a new chat to begin
          </Card.Description>
        </Card.Body>
      </Card>
    );
  }

  // When searching: show flat list with highlighted matches
  if (isSearching) {
    return (
      <>
        <RenameModal
          visible={renameModal.visible}
          currentTitle={renameModal.currentTitle}
          onConfirm={handleRenameConfirm}
          onCancel={handleRenameCancel}
        />
        <View
          style={{
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#52525b",
              fontWeight: "500",
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            {filteredConversations.length}{" "}
            {filteredConversations.length === 1 ? "result" : "results"}
          </Text>
        </View>
        <FlatList
          data={filteredConversations}
          keyExtractor={keyExtractor}
          renderItem={renderSearchItem}
          contentContainerStyle={{ paddingBottom: spacing.md }}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        />
      </>
    );
  }

  return (
    <>
      <RenameModal
        visible={renameModal.visible}
        currentTitle={renameModal.currentTitle}
        onConfirm={handleRenameConfirm}
        onCancel={handleRenameCancel}
      />
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingBottom: spacing.md }}
      >
        <Section
          title="Starred"
          items={groupedChats.starred}
          activeChatId={activeChatId}
          streamingConversationId={streamingConversationId}
          onSelectChat={handleSelectChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onToggleStar={handleToggleStar}
          isExpanded={expandedSections.starred}
          onToggle={() => toggleSection("starred")}
        />
        <Section
          title="Today"
          items={groupedChats.today}
          activeChatId={activeChatId}
          streamingConversationId={streamingConversationId}
          onSelectChat={handleSelectChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onToggleStar={handleToggleStar}
          isExpanded={expandedSections.today}
          onToggle={() => toggleSection("today")}
        />
        <Section
          title="Yesterday"
          items={groupedChats.yesterday}
          activeChatId={activeChatId}
          streamingConversationId={streamingConversationId}
          onSelectChat={handleSelectChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onToggleStar={handleToggleStar}
          isExpanded={expandedSections.yesterday}
          onToggle={() => toggleSection("yesterday")}
        />
        <Section
          title="Previous 7 Days"
          items={groupedChats.lastWeek}
          activeChatId={activeChatId}
          streamingConversationId={streamingConversationId}
          onSelectChat={handleSelectChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onToggleStar={handleToggleStar}
          isExpanded={expandedSections.lastWeek}
          onToggle={() => toggleSection("lastWeek")}
        />
        <Section
          title="Previous 30 Days"
          items={groupedChats.last30Days}
          activeChatId={activeChatId}
          streamingConversationId={streamingConversationId}
          onSelectChat={handleSelectChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onToggleStar={handleToggleStar}
          isExpanded={expandedSections.last30Days}
          onToggle={() => toggleSection("last30Days")}
        />
        <Section
          title="Older"
          items={groupedChats.older}
          activeChatId={activeChatId}
          streamingConversationId={streamingConversationId}
          onSelectChat={handleSelectChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onToggleStar={handleToggleStar}
          isExpanded={expandedSections.older}
          onToggle={() => toggleSection("older")}
        />
      </ScrollView>
    </>
  );
}
