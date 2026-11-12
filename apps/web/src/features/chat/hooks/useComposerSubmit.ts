"use client";

import type React from "react";

import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { sendMessage } from "@/features/chat/live/sendMessage";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { toast } from "@/lib/toast";
import {
  useComposerFiles,
  useComposerIsUploading,
  useComposerModeSelection,
  useComposerStore,
  useComposerTextActions,
  useComposerUI,
  useInputText,
  useReplyToMessage,
} from "@/stores/composerStore";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

const UNSENDABLE_SELECTION_MESSAGE =
  "Sending a selected tool, workflow or calendar event isn't available yet. Remove it and send your message.";

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
  const autoSend = useComposerStore((state) => state.workflowAutoSend);
  const { isPaid, isUnknown: isSubscriptionStatusUnknown } = useIsPaid();
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);

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

    // GAIA is paid-only: block send with the paywall unless subscription
    // status is unknown (cold cache / rehydrating), in which case let it
    // proceed — the send route's 402 is the backstop.
    if (!isSubscriptionStatusUnknown && !isPaid) {
      openUpgradeModal(undefined, { source: "composer_submit" });
      return;
    }
    // The send route carries text, files and a reply only; a selection it cannot carry is refused, not dropped.
    if (selectedTool || selectedWorkflow || selectedCalendarEvent) {
      toast.error(UNSENDABLE_SELECTION_MESSAGE);
      return;
    }

    sendMessage(inputText, {
      files: uploadedFileData,
      replyToMessage,
    }).catch((error) => {
      console.error("Chat send failed", error);
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
    // Enter always submits, also while GAIA is busy: the server folds it into the conversation.
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
