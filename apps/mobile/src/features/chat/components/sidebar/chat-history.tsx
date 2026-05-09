import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { Button, PressableFeedback, SkeletonGroup } from "heroui-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import ReanimatedSwipeable, {
  type SwipeableMethods,
} from "react-native-gesture-handler/ReanimatedSwipeable";
import Reanimated, {
  type SharedValue,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowDown01Icon,
  BubbleChatAddIcon,
  Delete02Icon,
  FavouriteIcon,
  PencilEdit02Icon,
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
            backgroundColor: "#1a1a1a",
            // rounded-2xl = 16px on containers
            borderRadius: 16,
            padding: spacing.lg,
            width: "100%",
            maxWidth: 360,
          }}
          onPress={() => {}}
        >
          <Text
            style={{
              fontSize: fontSize.md,
              color: "#e4e4e7",
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
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              // 12px vertical padding for comfortable 44dp+ tap height
              paddingVertical: 12,
              color: "#e4e4e7",
              fontSize: fontSize.sm,
              marginBottom: spacing.md,
            }}
            placeholderTextColor="#71717a"
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
  const { iconSize, fontSize } = useResponsive();
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
          borderRadius: 12,
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
        <Text style={{ color: "#ffffff", fontSize: fontSize.xs, marginTop: 2 }}>
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

function StreamingDot() {
  const opacity = useSharedValue(1);
  const scale = useSharedValue(1);
  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.4, { duration: 700 }),
        withTiming(1, { duration: 700 }),
      ),
      -1,
      false,
    );
    scale.value = withRepeat(
      withSequence(
        withTiming(1.3, { duration: 700 }),
        withTiming(1, { duration: 700 }),
      ),
      -1,
      false,
    );
  }, [opacity, scale]);
  const style = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ scale: scale.value }],
  }));
  return (
    <Reanimated.View
      style={[
        style,
        {
          width: 8,
          height: 8,
          borderRadius: 4,
          backgroundColor: "#00bbff",
        },
      ]}
    />
  );
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
  const [showSheet, setShowSheet] = useState(false);

  const handleLongPress = useCallback(() => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setShowSheet(true);
  }, []);

  const handlePress = useCallback(() => {
    Haptics.selectionAsync();
    onPress();
  }, [onPress]);

  const handleSwipeDelete = () => {
    swipeableRef.current?.close();
    onDelete(item.id);
  };

  const renderRightActions = (
    _progress: SharedValue<number>,
    dragX: SharedValue<number>,
  ) => <DeleteSwipeAction dragX={dragX} onDelete={handleSwipeDelete} />;

  // RNGH-aware tap + long-press composition. Plain RN Pressable inside
  // ReanimatedSwipeable + DrawerLayout has its onPress swallowed when the
  // parent pan gesture is still resolving — gesture-handler's tap gesture
  // routes through the same arbitration system and fires reliably.
  const tapGesture = useMemo(
    () =>
      Gesture.Tap()
        .maxDuration(400)
        .onEnd((_e, success) => {
          if (success) {
            handlePress();
          }
        })
        .runOnJS(true),
    [handlePress],
  );

  const longPressGesture = useMemo(
    () =>
      Gesture.LongPress()
        .minDuration(450)
        .onStart(() => {
          handleLongPress();
        })
        .runOnJS(true),
    [handleLongPress],
  );

  const composedGesture = useMemo(
    () => Gesture.Exclusive(longPressGesture, tapGesture),
    [longPressGesture, tapGesture],
  );

  return (
    <ReanimatedSwipeable
      ref={swipeableRef}
      renderRightActions={renderRightActions}
      rightThreshold={40}
      overshootRight={false}
    >
      <GestureDetector gesture={composedGesture}>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: 12,
            paddingVertical: spacing.sm + 2,
            gap: spacing.sm,
            backgroundColor: isActive ? "rgba(0,187,255,0.10)" : "transparent",
            borderRadius: 10,
            marginHorizontal: 12,
            overflow: "hidden",
          }}
        >
          {isActive ? (
            <View
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                width: 3,
                backgroundColor: "#00bbff",
              }}
            />
          ) : null}
          {isStreaming && <StreamingDot />}
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
              fontSize: fontSize.md,
              color: isActive
                ? "#ffffff"
                : item.is_unread
                  ? "#ffffff"
                  : "#a1a1aa",
              fontWeight: isActive ? "600" : item.is_unread ? "400" : "300",
              flex: 1,
            }}
            numberOfLines={1}
          />
        </View>
      </GestureDetector>

      {/* Custom action sheet */}
      <Modal
        visible={showSheet}
        transparent
        animationType="slide"
        onRequestClose={() => setShowSheet(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)" }}
          onPress={() => setShowSheet(false)}
        />
        <View
          style={{
            backgroundColor: "#18181b",
            borderTopLeftRadius: 16,
            borderTopRightRadius: 16,
            paddingBottom: 32,
          }}
        >
          {/* Handle */}
          <View
            style={{
              width: 36,
              height: 5,
              borderRadius: 2.5,
              backgroundColor: "rgba(255,255,255,0.2)",
              alignSelf: "center",
              marginTop: 12,
              marginBottom: 12,
            }}
          />
          {/* Title */}
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#71717a",
              fontWeight: "500",
              paddingHorizontal: spacing.lg,
              paddingBottom: spacing.sm,
            }}
            numberOfLines={1}
          >
            {item.title}
          </Text>
          {/* Divider */}
          <View style={{ height: 1, backgroundColor: "#27272a" }} />

          {/* Star / Unstar */}
          <Pressable
            onPress={() => {
              setShowSheet(false);
              onToggleStar(item.id, !!item.is_starred);
            }}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.md,
              paddingHorizontal: spacing.lg,
              paddingVertical: spacing.md,
              backgroundColor: pressed
                ? "rgba(255,255,255,0.04)"
                : "transparent",
            })}
          >
            <AppIcon icon={FavouriteIcon} size={iconSize.sm} color="#a1a1aa" />
            <Text style={{ fontSize: fontSize.md, color: "#ffffff" }}>
              {item.is_starred ? "Unstar" : "Star"}
            </Text>
          </Pressable>

          {/* Rename */}
          <Pressable
            onPress={() => {
              setShowSheet(false);
              onRename(item.id, item.title);
            }}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.md,
              paddingHorizontal: spacing.lg,
              paddingVertical: spacing.md,
              backgroundColor: pressed
                ? "rgba(255,255,255,0.04)"
                : "transparent",
            })}
          >
            <AppIcon
              icon={PencilEdit02Icon}
              size={iconSize.sm}
              color="#a1a1aa"
            />
            <Text style={{ fontSize: fontSize.md, color: "#ffffff" }}>
              Rename
            </Text>
          </Pressable>

          {/* Divider before destructive action */}
          <View
            style={{ height: 1, backgroundColor: "#27272a", marginTop: 4 }}
          />

          {/* Delete */}
          <Pressable
            onPress={() => {
              setShowSheet(false);
              onDelete(item.id);
            }}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.md,
              paddingHorizontal: spacing.lg,
              paddingVertical: spacing.md,
              backgroundColor: pressed ? "rgba(239,68,68,0.08)" : "transparent",
            })}
          >
            <AppIcon icon={Delete02Icon} size={iconSize.sm} color="#ef4444" />
            <Text style={{ fontSize: fontSize.md, color: "#ef4444" }}>
              Delete
            </Text>
          </Pressable>
        </View>
      </Modal>
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
  const { spacing, fontSize, iconSize } = useResponsive();
  const rotation = useSharedValue(isExpanded ? 0 : -90);

  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value}deg` }],
  }));

  const handleToggle = () => {
    rotation.value = withTiming(isExpanded ? -90 : 0, { duration: 200 });
    onToggle();
  };

  if (items.length === 0) return null;

  return (
    <View style={{ marginBottom: 4 }}>
      <PressableFeedback
        onPress={handleToggle}
        hitSlop={4}
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.sm + 4,
          paddingTop: 8,
          paddingBottom: 4,
        }}
      >
        <Text
          style={{
            flex: 1,
            fontSize: fontSize.md,
            color: "#71717a",
            fontWeight: "400",
          }}
        >
          {title}
        </Text>
        <Reanimated.View style={chevronStyle}>
          <AppIcon icon={ArrowDown01Icon} size={iconSize.sm} color="#71717a" />
        </Reanimated.View>
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
    <View style={{ flex: 1 }}>
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
    </View>
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
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          padding: spacing.lg,
        }}
      >
        <Text
          style={{
            color: "#ef4444",
            fontSize: fontSize.sm,
            textAlign: "center",
          }}
        >
          {error}
        </Text>
      </View>
    );
  }

  if (filteredConversations.length === 0 && isSearching) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          padding: spacing.lg,
        }}
      >
        <Text
          style={{
            color: "#71717a",
            fontSize: fontSize.sm,
            textAlign: "center",
          }}
        >
          No results for "{searchQuery}"
        </Text>
      </View>
    );
  }

  if (conversations.length === 0) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          padding: spacing.lg,
        }}
      >
        <View
          style={{
            flexDirection: "column",
            alignItems: "center",
            gap: spacing.sm,
            paddingVertical: spacing.xl,
          }}
        >
          {/* #71717a (zinc-500) gives better contrast than zinc-600 on #1a1a1a */}
          <AppIcon icon={BubbleChatAddIcon} size={24} color="#71717a" />
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#a1a1aa",
              textAlign: "center",
            }}
          >
            No conversations yet
          </Text>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#71717a",
              textAlign: "center",
            }}
          >
            Start a new chat to begin
          </Text>
        </View>
      </View>
    );
  }

  // When searching: show flat list with highlighted matches
  if (isSearching) {
    return (
      <View style={{ flex: 1 }}>
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
              fontSize: fontSize.sm,
              color: "#52525b",
              fontWeight: "400",
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
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingBottom: spacing.md }}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        />
      </View>
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
          title="Previous 7 days"
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
          title="Previous 30 days"
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
