import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { Pressable, Share, View } from "react-native";
import {
  AppIcon,
  Copy01Icon,
  LinkBackwardIcon,
  Pin02Icon,
  Share01Icon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { chatApi } from "../../api/chat-api";

export interface MessageActionConfig {
  messageId: string;
  conversationId: string;
  content: string;
  isUser: boolean;
  isPinned?: boolean;
}

type ReactionType = "thumbsUp" | "thumbsDown";

interface MessageActionSheetProps {
  config: MessageActionConfig | null;
  onPin: (messageId: string, conversationId: string) => void;
  onReply: (messageId: string, conversationId: string) => void;
}

interface ActionRowProps {
  icon: React.ReactNode;
  label: string;
  onPress: () => void;
  destructive?: boolean;
}

function ActionRow({
  icon,
  label,
  onPress,
  destructive = false,
}: ActionRowProps) {
  const { fontSize } = useResponsive();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        padding: 14,
        borderRadius: 12,
        backgroundColor: pressed ? "rgba(255,255,255,0.05)" : "transparent",
      })}
    >
      {icon}
      <Text
        style={{
          fontSize: fontSize.base,
          color: destructive ? "#ef4444" : "#e4e4e7",
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

function SectionDivider() {
  return (
    <View
      style={{
        height: 1,
        backgroundColor: "rgba(255,255,255,0.08)",
        marginVertical: 4,
        marginHorizontal: 14,
      }}
    />
  );
}

export interface MessageActionSheetRef {
  open: () => void;
  close: () => void;
}

export const MessageActionSheet = forwardRef<
  MessageActionSheetRef,
  MessageActionSheetProps
>(({ config, onPin, onReply }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const snapPoints = useMemo(() => ["38%"], []);
  const [selectedReaction, setSelectedReaction] = useState<ReactionType | null>(
    null,
  );

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const handleCopyText = useCallback(async () => {
    if (!config) return;
    await Clipboard.setStringAsync(config.content);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    setIsOpen(false);
  }, [config]);

  const handleShare = useCallback(async () => {
    if (!config) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setIsOpen(false);
    await Share.share({ message: config.content });
  }, [config]);

  const handleReply = useCallback(() => {
    if (!config) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onReply(config.messageId, config.conversationId);
    setIsOpen(false);
  }, [config, onReply]);

  const handlePin = useCallback(() => {
    if (!config) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onPin(config.messageId, config.conversationId);
    setIsOpen(false);
  }, [config, onPin]);

  const handleReaction = useCallback(
    (reaction: ReactionType) => {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      const newReaction = selectedReaction === reaction ? null : reaction;
      setSelectedReaction(newReaction);
      if (config && newReaction) {
        void chatApi.submitMessageFeedback(
          config.conversationId,
          config.messageId,
          newReaction,
        );
      }
    },
    [config, selectedReaction],
  );

  return (
    <BottomSheet
      isOpen={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        if (!open) setSelectedReaction(null);
      }}
    >
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={snapPoints}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1a1a1a" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{
              paddingHorizontal: 16,
              paddingTop: 8,
              paddingBottom: 28,
            }}
          >
            {/* Reaction bar — AI messages only */}
            {config && !config.isUser ? (
              <>
                <View
                  style={{
                    flexDirection: "row",
                    justifyContent: "center",
                    gap: 16,
                    paddingVertical: 12,
                    marginBottom: 4,
                  }}
                >
                  <Pressable
                    onPress={() => handleReaction("thumbsUp")}
                    style={({ pressed }) => ({
                      alignItems: "center",
                      justifyContent: "center",
                      width: 52,
                      height: 52,
                      borderRadius: 26,
                      backgroundColor:
                        selectedReaction === "thumbsUp"
                          ? "rgba(34, 197, 94, 0.2)"
                          : pressed
                            ? "rgba(255,255,255,0.08)"
                            : "rgba(255,255,255,0.05)",
                    })}
                  >
                    <AppIcon
                      icon={ThumbsUpIcon}
                      size={22}
                      color={
                        selectedReaction === "thumbsUp" ? "#22c55e" : "#a1a1aa"
                      }
                    />
                  </Pressable>

                  <Pressable
                    onPress={() => handleReaction("thumbsDown")}
                    style={({ pressed }) => ({
                      alignItems: "center",
                      justifyContent: "center",
                      width: 52,
                      height: 52,
                      borderRadius: 26,
                      backgroundColor:
                        selectedReaction === "thumbsDown"
                          ? "rgba(239, 68, 68, 0.2)"
                          : pressed
                            ? "rgba(255,255,255,0.08)"
                            : "rgba(255,255,255,0.05)",
                    })}
                  >
                    <AppIcon
                      icon={ThumbsDownIcon}
                      size={22}
                      color={
                        selectedReaction === "thumbsDown"
                          ? "#ef4444"
                          : "#a1a1aa"
                      }
                    />
                  </Pressable>
                </View>
                <SectionDivider />
              </>
            ) : null}

            {/* Message operations */}
            <ActionRow
              icon={<AppIcon icon={Copy01Icon} size={20} color="#a1a1aa" />}
              label="Copy Text"
              onPress={() => void handleCopyText()}
            />
            <ActionRow
              icon={<AppIcon icon={Share01Icon} size={20} color="#a1a1aa" />}
              label="Share"
              onPress={() => void handleShare()}
            />

            <SectionDivider />

            {/* Thread operations */}
            <ActionRow
              icon={
                <AppIcon icon={LinkBackwardIcon} size={20} color="#a1a1aa" />
              }
              label="Reply"
              onPress={handleReply}
            />
            <ActionRow
              icon={
                <AppIcon
                  icon={Pin02Icon}
                  size={20}
                  color={config?.isPinned ? "#00bbff" : "#a1a1aa"}
                />
              }
              label={config?.isPinned ? "Unpin Message" : "Pin Message"}
              onPress={handlePin}
            />
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

MessageActionSheet.displayName = "MessageActionSheet";
