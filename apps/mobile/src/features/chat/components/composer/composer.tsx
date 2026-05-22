import * as Haptics from "expo-haptics";
import { PressableFeedback } from "heroui-native";
import { useCallback, useRef, useState } from "react";
import { Keyboard, Pressable, TextInput, View } from "react-native";
import Animated, {
  FadeIn,
  FadeInDown,
  FadeOutUp,
  useAnimatedStyle,
  useSharedValue,
  withSequence,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowUp02Icon,
  Cancel01Icon,
  LinkBackwardIcon,
  PlusSignIcon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { haptics } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import type { AttachmentFile } from "./attachment-preview";
import { AttachmentPreview } from "./attachment-preview";
import { AttachmentSheet, type AttachmentSheetRef } from "./attachment-sheet";
import { SelectedIndicator } from "./selected-indicator";
import {
  SlashCommandSheet,
  type SlashCommandSheetRef,
} from "./slash-command-sheet";
import {
  WorkflowPickerSheet,
  type WorkflowPickerSheetRef,
} from "./workflow-picker-sheet";

const DEFAULT_COMMANDS = [
  "new",
  "clear",
  "help",
  "integrations",
  "notifications",
  "settings",
  "workflows",
];

interface SelectedToolData {
  name: string;
  category: string;
}

interface SelectedWorkflowData {
  id: string;
  title: string;
}

interface SelectedCalendarEventData {
  id: string;
  title: string;
}

export interface ReplyToData {
  id: string;
  content: string;
  role: "user" | "assistant";
}

interface ComposerProps {
  onSend?: (message: string, attachments: AttachmentFile[]) => void;
  placeholder?: string;
  value?: string;
  onChangeText?: (text: string) => void;
  onCommand?: (command: string) => boolean | undefined;
  isStreaming?: boolean;
  onCancel?: () => void;
  selectedTool?: SelectedToolData | null;
  onRemoveTool?: () => void;
  selectedWorkflow?: SelectedWorkflowData | null;
  onRemoveWorkflow?: () => void;
  onToolSelected?: (toolName: string, toolCategory: string) => void;
  onWorkflowSelected?: (workflow: { id: string; title: string }) => void;
  replyTo?: ReplyToData | null;
  onRemoveReply?: () => void;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
  onRemoveCalendarEvent?: () => void;
}

function truncateContent(content: string, maxLength = 60): string {
  if (content.length <= maxLength) return content;
  return `${content.slice(0, maxLength).trim()}...`;
}

export function Composer({
  onSend,
  placeholder = "Ask anything",
  value,
  onChangeText,
  onCommand,
  isStreaming = false,
  onCancel,
  selectedTool,
  onRemoveTool,
  selectedWorkflow,
  onRemoveWorkflow,
  onToolSelected,
  onWorkflowSelected,
  replyTo,
  onRemoveReply,
  selectedCalendarEvent,
  onRemoveCalendarEvent,
}: ComposerProps) {
  const [internalMessage, setInternalMessage] = useState("");
  const [attachments, setAttachments] = useState<AttachmentFile[]>([]);
  const inputRef = useRef<TextInput>(null);
  const slashCommandRef = useRef<SlashCommandSheetRef>(null);
  const workflowPickerRef = useRef<WorkflowPickerSheetRef>(null);
  const attachmentSheetRef = useRef<AttachmentSheetRef>(null);

  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();

  const message = value ?? internalMessage;
  const setMessage = onChangeText ?? setInternalMessage;
  const trimmed = message.trim();
  const hasContent =
    !!trimmed ||
    !!selectedTool ||
    !!selectedWorkflow ||
    !!selectedCalendarEvent ||
    attachments.length > 0;

  // Slash command detection for built-in commands
  const isCommandMode = trimmed.startsWith("/");
  const commandQuery = isCommandMode ? trimmed.slice(1).toLowerCase() : "";
  const matchingCommands = DEFAULT_COMMANDS.filter((command) =>
    command.startsWith(commandQuery),
  );

  // Auto-grow text input height (max 5 lines)
  const [inputHeight, setInputHeight] = useState(0);
  const lineHeight = fontSize.base + 6;
  const minInputHeight = moderateScale(24, 0.5);
  const maxInputHeight = lineHeight * 5;

  // Send button animated scale
  const sendScale = useSharedValue(1);
  const sendAnimatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: sendScale.value }],
  }));

  // Plus button animated scale
  const plusScale = useSharedValue(1);
  const plusAnimatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: plusScale.value }],
  }));

  const dismissKeyboard = useCallback(() => {
    inputRef.current?.blur();
    Keyboard.dismiss();
  }, []);

  const runCommand = useCallback(
    (command: string) => {
      if (command === "workflows") {
        setMessage("");
        dismissKeyboard();
        workflowPickerRef.current?.open();
        return;
      }
      const handled = onCommand?.(command) ?? false;
      if (handled) {
        setMessage("");
        dismissKeyboard();
      }
    },
    [onCommand, setMessage, dismissKeyboard],
  );

  const handleWorkflowSelected = useCallback(
    (workflow: { id: string; title: string }) => {
      onWorkflowSelected?.(workflow);
    },
    [onWorkflowSelected],
  );

  const handleSend = useCallback(() => {
    if (isStreaming) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      onCancel?.();
      return;
    }

    if (!hasContent) return;

    if (isCommandMode) {
      const command = trimmed.split(/\s+/)[0]?.slice(1).toLowerCase();
      if (command) {
        runCommand(command);
        return;
      }
    }

    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);

    // Animate send button press
    sendScale.value = withSequence(
      withTiming(0.92, { duration: 80 }),
      withSpring(1, { damping: 20, stiffness: 400 }),
    );

    const pendingAttachments = attachments;
    onSend?.(message, pendingAttachments);
    setMessage("");
    setAttachments([]);
    Keyboard.dismiss();
  }, [
    isStreaming,
    onCancel,
    hasContent,
    isCommandMode,
    trimmed,
    runCommand,
    sendScale,
    onSend,
    message,
    attachments,
    setMessage,
  ]);

  const handlePlusPress = useCallback(() => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    dismissKeyboard();
    attachmentSheetRef.current?.open();
  }, [dismissKeyboard]);

  const handleTextChange = useCallback(
    (text: string) => {
      setMessage(text);

      // Detect "/" at the start to open tool picker
      if (text === "/") {
        slashCommandRef.current?.open();
        // Clear the slash so the input stays clean
        setTimeout(() => setMessage(""), 50);
      }
    },
    [setMessage],
  );

  const handleToolSelected = useCallback(
    (toolName: string, toolCategory: string) => {
      onToolSelected?.(toolName, toolCategory);
    },
    [onToolSelected],
  );

  const handleContentSizeChange = useCallback(
    (e: { nativeEvent: { contentSize: { height: number } } }) => {
      const newHeight = Math.min(
        Math.max(e.nativeEvent.contentSize.height, minInputHeight),
        maxInputHeight,
      );
      setInputHeight(newHeight);
    },
    [minInputHeight, maxInputHeight],
  );

  const handleAttachmentsSelected = useCallback(
    (newAttachments: AttachmentFile[]) => {
      setAttachments((prev) => [...prev, ...newAttachments]);
    },
    [],
  );

  const handleRemoveAttachment = useCallback((localId: string) => {
    setAttachments((prev) => prev.filter((a) => a.localId !== localId));
  }, []);

  return (
    <View style={{ width: "100%" }}>
      {/* Built-in slash commands overlay — rendered above the composer box */}
      {isCommandMode && matchingCommands.length > 0 && (
        <Animated.View
          entering={FadeIn.duration(150)}
          style={{
            marginHorizontal: spacing.xs,
            marginBottom: spacing.xs,
            borderRadius: moderateScale(12, 0.5),
            backgroundColor: "#1a1a1a",
            overflow: "hidden",
          }}
        >
          {matchingCommands.map((command, index) => (
            <PressableFeedback
              key={command}
              onPress={() => runCommand(command)}
              style={{
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm + 2,
                borderBottomWidth:
                  index === matchingCommands.length - 1 ? 0 : 1,
                borderBottomColor: "rgba(255,255,255,0.05)",
              }}
            >
              <Text style={{ color: "#ffffff", fontSize: fontSize.sm }}>
                /{command}
              </Text>
            </PressableFeedback>
          ))}
        </Animated.View>
      )}

      <View
        style={{
          backgroundColor: "#27272a",
          borderRadius: moderateScale(20, 0.5),
        }}
      >
        {/* Reply-to indicator */}
        {replyTo && (
          <Animated.View
            entering={FadeInDown.duration(200)}
            exiting={FadeOutUp.duration(150)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              marginHorizontal: spacing.sm + 2,
              marginTop: spacing.sm,
              paddingHorizontal: spacing.sm + 2,
              paddingVertical: spacing.sm,
              borderRadius: moderateScale(12, 0.5),
              backgroundColor: "rgba(63,63,70,0.6)",
            }}
          >
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.xs,
                flex: 1,
                overflow: "hidden",
              }}
            >
              <AppIcon
                icon={LinkBackwardIcon}
                size={iconSize.sm}
                color="#a1a1aa"
              />
              <View style={{ flex: 1, overflow: "hidden" }}>
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#a1a1aa",
                    fontWeight: "600",
                    marginBottom: 2,
                  }}
                >
                  {replyTo.role === "user" ? "You" : "GAIA"}
                </Text>
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#e4e4e7",
                  }}
                  numberOfLines={1}
                >
                  {truncateContent(replyTo.content)}
                </Text>
              </View>
            </View>
            {onRemoveReply && (
              <PressableFeedback
                onPress={onRemoveReply}
                hitSlop={8}
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 12,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "rgba(161,161,170,0.15)",
                  marginLeft: spacing.xs,
                }}
              >
                <AppIcon
                  icon={Cancel01Icon}
                  size={iconSize.sm - 2}
                  color="#a1a1aa"
                />
              </PressableFeedback>
            )}
          </Animated.View>
        )}

        {/* Selected tool / workflow / calendar indicators */}
        {(selectedTool || selectedWorkflow || selectedCalendarEvent) && (
          <View
            style={{
              paddingHorizontal: spacing.sm + 2,
              paddingTop: replyTo ? spacing.xs : spacing.sm,
            }}
          >
            {selectedTool && onRemoveTool && (
              <SelectedIndicator
                label={selectedTool.name}
                variant="tool"
                onRemove={onRemoveTool}
              />
            )}
            {selectedWorkflow && onRemoveWorkflow && (
              <SelectedIndicator
                label={selectedWorkflow.title}
                variant="workflow"
                onRemove={onRemoveWorkflow}
              />
            )}
            {selectedCalendarEvent && onRemoveCalendarEvent && (
              <SelectedIndicator
                label={selectedCalendarEvent.title}
                variant="calendar"
                onRemove={onRemoveCalendarEvent}
              />
            )}
          </View>
        )}

        {/* Attachment previews */}
        {attachments.length > 0 && (
          <AttachmentPreview
            attachments={attachments}
            onRemove={handleRemoveAttachment}
          />
        )}

        {/* Two-row composer: input on top, toolbar below — reserves space for
            tools / voice / future affordances. Web-style density. */}
        <TextInput
          ref={inputRef}
          style={{
            paddingHorizontal: 16,
            paddingTop: 14,
            paddingBottom: 6,
            fontSize: fontSize.base,
            lineHeight: Math.round(fontSize.base * 1.35),
            color: "#ffffff",
            minHeight: 36,
            maxHeight: maxInputHeight,
            ...(inputHeight > 0 && {
              height: Math.min(inputHeight, maxInputHeight),
            }),
          }}
          placeholder={placeholder}
          placeholderTextColor="#71717a"
          value={message}
          onChangeText={handleTextChange}
          onContentSizeChange={handleContentSizeChange}
          multiline
          maxLength={4000}
          textAlignVertical="top"
        />

        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: 10,
            paddingBottom: 10,
            paddingTop: 6,
            gap: 8,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Animated.View style={plusAnimatedStyle}>
              <Pressable
                onPress={handlePlusPress}
                hitSlop={8}
                onPressIn={() => {
                  plusScale.value = withSpring(0.92, {
                    damping: 15,
                    stiffness: 400,
                  });
                }}
                onPressOut={() => {
                  plusScale.value = withSpring(1, {
                    damping: 15,
                    stiffness: 400,
                  });
                }}
                style={{
                  width: 36,
                  height: 36,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <AppIcon
                  icon={PlusSignIcon}
                  size={iconSize.md}
                  color="#a1a1aa"
                />
              </Pressable>
            </Animated.View>

            <Pressable
              onPress={() => {
                haptics.light();
                dismissKeyboard();
                slashCommandRef.current?.open();
              }}
              hitSlop={6}
              style={{
                width: 32,
                height: 32,
                alignItems: "center",
                justifyContent: "center",
              }}
              android_ripple={{
                color: "rgba(255,255,255,0.08)",
                radius: 16,
              }}
              accessibilityLabel="Tools"
            >
              <AppIcon icon={Wrench01Icon} size={20} color="#a1a1aa" />
            </Pressable>
          </View>

          <Animated.View style={sendAnimatedStyle}>
            <Pressable
              onPress={handleSend}
              hitSlop={8}
              disabled={!isStreaming && !hasContent}
              style={{
                width: 36,
                height: 36,
                borderRadius: 18,
                backgroundColor: isStreaming
                  ? "rgba(63,63,70,0.8)"
                  : hasContent
                    ? "#00bbff"
                    : "rgba(63,63,70,0.6)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {isStreaming ? (
                <View
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    backgroundColor: "#e4e4e7",
                  }}
                />
              ) : (
                <AppIcon
                  icon={ArrowUp02Icon}
                  size={iconSize.sm}
                  strokeWidth={2.5}
                  color={hasContent ? "#000000" : "#71717a"}
                />
              )}
            </Pressable>
          </Animated.View>
        </View>
      </View>

      {/* Slash command bottom sheet for tool selection */}
      <SlashCommandSheet
        ref={slashCommandRef}
        onSelectTool={handleToolSelected}
      />

      {/* Workflow picker bottom sheet */}
      <WorkflowPickerSheet
        ref={workflowPickerRef}
        onSelectWorkflow={handleWorkflowSelected}
      />

      {/* Attachment picker bottom sheet */}
      <AttachmentSheet
        ref={attachmentSheetRef}
        onAttachmentsSelected={handleAttachmentsSelected}
      />
    </View>
  );
}
