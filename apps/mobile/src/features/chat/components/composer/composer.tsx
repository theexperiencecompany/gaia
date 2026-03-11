import * as Haptics from "expo-haptics";
import { Button, PressableFeedback } from "heroui-native";
import { useCallback, useRef, useState } from "react";
import { Keyboard, TextInput, View } from "react-native";
import Animated, {
  FadeIn,
  FadeOut,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowUp02Icon,
  Cancel01Icon,
  LinkBackwardIcon,
  PlusSignIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { AI_MODELS } from "@/features/chat/data/models";
import { ConnectDrawerTrigger } from "@/features/integrations";
import { useResponsive } from "@/lib/responsive";
import { cn } from "@/lib/utils";
import type { AttachmentFile } from "./attachment-preview";
import { AttachmentPreview } from "./attachment-preview";
import { AttachmentSheet, type AttachmentSheetRef } from "./attachment-sheet";
import {
  ModelPickerSheet,
  type ModelPickerSheetRef,
} from "./model-picker-sheet";
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
  "model",
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
  currentModelId?: string;
  onModelChange?: (modelId: string) => void;
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
  currentModelId,
  onModelChange,
}: ComposerProps) {
  const [internalMessage, setInternalMessage] = useState("");
  const [attachments, setAttachments] = useState<AttachmentFile[]>([]);
  const inputRef = useRef<TextInput>(null);
  const slashCommandRef = useRef<SlashCommandSheetRef>(null);
  const workflowPickerRef = useRef<WorkflowPickerSheetRef>(null);
  const modelPickerRef = useRef<ModelPickerSheetRef>(null);
  const attachmentSheetRef = useRef<AttachmentSheetRef>(null);

  const currentModelName = currentModelId
    ? (AI_MODELS.find((m) => m.id === currentModelId)?.name ??
      currentModelId.slice(0, 8))
    : (AI_MODELS.find((m) => m.isDefault)?.name ?? "GPT-4o");
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
      if (command === "model") {
        setMessage("");
        dismissKeyboard();
        modelPickerRef.current?.open();
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
    sendScale.value = withSpring(0.85, { damping: 15, stiffness: 400 });
    setTimeout(() => {
      sendScale.value = withSpring(1, { damping: 15, stiffness: 400 });
    }, 100);

    const pendingAttachments = attachments;
    onSend?.(message, pendingAttachments);
    setMessage("");
    setAttachments([]);
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

  const hasIndicators =
    !!selectedTool ||
    !!selectedWorkflow ||
    !!selectedCalendarEvent ||
    !!replyTo ||
    attachments.length > 0;

  return (
    <View style={{ width: "100%" }}>
      {/* Built-in slash commands overlay — rendered above the composer box */}
      {isCommandMode && matchingCommands.length > 0 && (
        <View
          style={{
            marginHorizontal: spacing.xs,
            marginBottom: spacing.xs,
            borderRadius: moderateScale(12, 0.5),
            backgroundColor: "#0e0f11",
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.08)",
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
        </View>
      )}

      <View
        style={{
          backgroundColor: "rgba(23,25,32,0.95)",
          borderRadius: moderateScale(20, 0.5),
          borderWidth: 1,
          borderColor: "rgba(255,255,255,0.1)",
        }}
      >
        {/* Reply-to indicator */}
        {replyTo && (
          <Animated.View
            entering={FadeIn.duration(200)}
            exiting={FadeOut.duration(150)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              marginHorizontal: spacing.sm + 2,
              marginTop: spacing.sm,
              paddingHorizontal: spacing.sm + 2,
              paddingVertical: spacing.sm,
              borderRadius: moderateScale(12, 0.5),
              backgroundColor: "rgba(63,63,70,0.4)",
              borderWidth: 1,
              borderStyle: "dashed",
              borderColor: "rgba(161,161,170,0.4)",
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
                  backgroundColor: "rgba(142,142,147,0.15)",
                  marginLeft: spacing.xs,
                }}
              >
                <AppIcon
                  icon={Cancel01Icon}
                  size={iconSize.sm - 2}
                  color="#8e8e93"
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

        {/* Text input area */}
        <TextInput
          ref={inputRef}
          style={{
            paddingHorizontal: spacing.md,
            paddingTop: hasIndicators ? spacing.xs : spacing.md,
            paddingBottom: spacing.xs,
            fontSize: fontSize.base,
            color: "#ffffff",
            minHeight: moderateScale(44, 0.5),
            maxHeight: maxInputHeight + spacing.lg,
            ...(inputHeight > 0 && { height: inputHeight + spacing.lg }),
          }}
          placeholder={placeholder}
          placeholderTextColor="#8e8e93"
          value={message}
          onChangeText={handleTextChange}
          onContentSizeChange={handleContentSizeChange}
          multiline
          maxLength={4000}
          textAlignVertical="top"
        />

        {/* Toolbar row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: spacing.sm + 2,
            paddingBottom: spacing.sm + 2,
          }}
        >
          {/* Left side buttons */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <Button
              variant="secondary"
              isIconOnly
              size="sm"
              className="rounded-full"
              onPress={handlePlusPress}
            >
              <AppIcon
                icon={PlusSignIcon}
                size={iconSize.md - 2}
                color="#8e8e93"
              />
            </Button>

            <ConnectDrawerTrigger onOpen={dismissKeyboard} />

            <PressableFeedback
              onPress={() => modelPickerRef.current?.open()}
              style={{
                paddingHorizontal: spacing.sm,
                paddingVertical: 4,
                borderRadius: 8,
                backgroundColor: "rgba(63,63,70,0.5)",
                maxWidth: 80,
              }}
            >
              <Text
                style={{ fontSize: fontSize.xs, color: "#a1a1aa" }}
                numberOfLines={1}
              >
                {currentModelName.length > 8
                  ? `${currentModelName.slice(0, 8)}…`
                  : currentModelName}
              </Text>
            </PressableFeedback>
          </View>

          {/* Right side: send / stop button */}
          <Animated.View style={sendAnimatedStyle}>
            <Button
              variant="ghost"
              isIconOnly
              size="sm"
              className={cn("rounded-full", {
                "bg-danger": isStreaming,
                "bg-accent": !isStreaming && hasContent,
                "bg-default": !isStreaming && !hasContent,
              })}
              onPress={handleSend}
              isDisabled={!isStreaming && !hasContent}
            >
              {isStreaming ? (
                <View
                  style={{
                    width: iconSize.sm - 2,
                    height: iconSize.sm - 2,
                    borderRadius: 2,
                    backgroundColor: "#ffffff",
                  }}
                />
              ) : (
                <AppIcon
                  icon={ArrowUp02Icon}
                  size={iconSize.sm}
                  strokeWidth={2.5}
                  color={hasContent ? "#000000" : "#8e8e93"}
                />
              )}
            </Button>
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

      {/* Model picker bottom sheet */}
      <ModelPickerSheet
        ref={modelPickerRef}
        currentModelId={currentModelId}
        onSelectModel={onModelChange ?? (() => {})}
      />

      {/* Attachment picker bottom sheet */}
      <AttachmentSheet
        ref={attachmentSheetRef}
        onAttachmentsSelected={handleAttachmentsSelected}
      />
    </View>
  );
}
