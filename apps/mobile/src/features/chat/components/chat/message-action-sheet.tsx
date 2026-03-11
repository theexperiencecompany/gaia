import { BottomSheetView } from "@gorhom/bottom-sheet";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { Pressable } from "react-native";
import {
  AppIcon,
  Copy01Icon,
  Delete02Icon,
  Pin02Icon,
  RepeatIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

export interface MessageActionConfig {
  messageId: string;
  conversationId: string;
  content: string;
  isUser: boolean;
  isPinned?: boolean;
}

interface MessageActionSheetProps {
  config: MessageActionConfig | null;
  onDelete: (messageId: string, conversationId: string) => void;
  onPin: (messageId: string, conversationId: string) => void;
  onRetry: (messageId: string, conversationId: string) => void;
}

export interface MessageActionSheetRef {
  open: () => void;
  close: () => void;
}

export const MessageActionSheet = forwardRef<
  MessageActionSheetRef,
  MessageActionSheetProps
>(({ config, onDelete, onPin, onRetry }, ref) => {
  const [isOpen, setIsOpen] = useState(false);

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const handleCopy = useCallback(async () => {
    if (!config) return;
    await Clipboard.setStringAsync(config.content);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    setIsOpen(false);
  }, [config]);

  const handlePin = useCallback(() => {
    if (!config) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onPin(config.messageId, config.conversationId);
    setIsOpen(false);
  }, [config, onPin]);

  const handleRetry = useCallback(() => {
    if (!config) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onRetry(config.messageId, config.conversationId);
    setIsOpen(false);
  }, [config, onRetry]);

  const handleDelete = useCallback(() => {
    if (!config) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onDelete(config.messageId, config.conversationId);
    setIsOpen(false);
  }, [config, onDelete]);

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["25%"]}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <BottomSheetView
            style={{ paddingHorizontal: 16, paddingTop: 8, paddingBottom: 24 }}
          >
            <Pressable
              onPress={() => void handleCopy()}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 12,
                padding: 14,
                borderRadius: 10,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.05)"
                  : "transparent",
              })}
            >
              <AppIcon icon={Copy01Icon} size={20} color="#a1a1aa" />
              <Text style={{ fontSize: 16, color: "#e4e4e7" }}>Copy</Text>
            </Pressable>

            <Pressable
              onPress={handlePin}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 12,
                padding: 14,
                borderRadius: 10,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.05)"
                  : "transparent",
              })}
            >
              <AppIcon icon={Pin02Icon} size={20} color="#a1a1aa" />
              <Text style={{ fontSize: 16, color: "#e4e4e7" }}>
                {config?.isPinned ? "Unpin" : "Pin"}
              </Text>
            </Pressable>

            {config?.isUser ? (
              <Pressable
                onPress={handleRetry}
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  padding: 14,
                  borderRadius: 10,
                  backgroundColor: pressed
                    ? "rgba(255,255,255,0.05)"
                    : "transparent",
                })}
              >
                <AppIcon icon={RepeatIcon} size={20} color="#a1a1aa" />
                <Text style={{ fontSize: 16, color: "#e4e4e7" }}>Retry</Text>
              </Pressable>
            ) : null}

            <Pressable
              onPress={handleDelete}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: 12,
                padding: 14,
                borderRadius: 10,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.05)"
                  : "transparent",
              })}
            >
              <AppIcon icon={Delete02Icon} size={20} color="#ef4444" />
              <Text style={{ fontSize: 16, color: "#ef4444" }}>Delete</Text>
            </Pressable>
          </BottomSheetView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

MessageActionSheet.displayName = "MessageActionSheet";
