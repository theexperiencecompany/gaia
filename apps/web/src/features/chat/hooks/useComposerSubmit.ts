"use client";

import type React from "react";

import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useSendMessage } from "@/hooks/useSendMessage";
import {
  useComposerFiles,
  useComposerIsUploading,
  useComposerModeSelection,
  useComposerTextActions,
  useComposerUI,
  useInputText,
} from "@/stores/composerStore";
import { useReplyToMessage } from "@/stores/replyToMessageStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";

interface UseComposerSubmitParams {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  scrollToBottom: () => void;
}

/**
 * Sending a chat message from the composer: the guards (workflow auto-send,
 * pending uploads, empty input), dispatch and post-send cleanup, plus the
 * Enter/Escape keyboard contract on the input.
 */
export function useComposerSubmit({
  inputRef,
  scrollToBottom,
}: UseComposerSubmitParams) {
  const inputText = useInputText();
  const { clearInputText } = useComposerTextActions();
  const {
    selectedTool,
    selectedToolCategory,
    setSelectedTool,
    setSelectedToolCategory,
    clearToolSelection,
  } = useComposerModeSelection();
  const { uploadedFiles, uploadedFileData, clearAllFiles } = useComposerFiles();
  const isUploadingFiles = useComposerIsUploading();
  const { isSlashCommandDropdownOpen } = useComposerUI();
  const { selectedWorkflow, clearSelectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent, clearSelectedCalendarEvent } =
    useCalendarEventSelection();
  const { replyToMessage, clearReplyToMessage } = useReplyToMessage();
  const { autoSend } = useWorkflowSelectionStore();

  const sendMessage = useSendMessage();

  const handleFormSubmit = (e?: React.FormEvent<HTMLFormElement>) => {
    if (e) e.preventDefault();

    // Prevent double execution when workflow is auto-sending
    if (autoSend) return;

    // Hold the send until every attachment has finished uploading, otherwise the
    // message goes out before its file data is ready and the attachment is lost.
    if (isUploadingFiles) return;

    // Only prevent submission if there's no text AND no files AND no selected tool AND no selected workflow AND no selected calendar event
    if (
      !inputText &&
      uploadedFiles.length === 0 &&
      !selectedTool &&
      !selectedWorkflow &&
      !selectedCalendarEvent
    ) {
      return;
    }
    // Note: Loading state is now set in useSendMessage AFTER user message is persisted
    // This ensures the loading indicator appears AFTER the user message in the UI

    sendMessage(inputText, {
      files: uploadedFileData,
      selectedTool: selectedTool ?? null,
      selectedToolCategory: selectedToolCategory ?? null,
      selectedWorkflow,
      selectedCalendarEvent,
      replyToMessage,
    });

    clearInputText();
    clearAllFiles();
    clearToolSelection();
    clearSelectedWorkflow();
    clearSelectedCalendarEvent();
    clearReplyToMessage();

    if (inputRef) inputRef.current?.focus();
    scrollToBottom();
  };

  const handleRemoveSelectedTool = () => {
    setSelectedTool(null);
    setSelectedToolCategory(null);
  };

  const handleKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (
    event,
  ) => {
    // Enter always submits. If a stream is still open (initial response OR a
    // background executor still running), the send is held in the turn
    // manager's per-conversation queue rather than starting a new turn.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleFormSubmit();
    }

    // Handle Escape key when slash command dropdown is closed
    if (event.key === "Escape" && !isSlashCommandDropdownOpen) {
      // If there's a selected tool, remove it
      if (selectedTool) {
        event.preventDefault();
        handleRemoveSelectedTool();
      }
      // If there's a selected workflow, clear it
      else if (selectedWorkflow) {
        event.preventDefault();
        clearSelectedWorkflow();
      }
      // If there's a reply-to message, clear it
      else if (replyToMessage) {
        event.preventDefault();
        clearReplyToMessage();
      }
    }
  };

  return { handleFormSubmit, handleRemoveSelectedTool, handleKeyDown };
}
