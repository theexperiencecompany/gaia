import type React from "react";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useHotkeys } from "react-hotkeys-hook";

import FilePreview, {
  type UploadedFilePreview,
} from "@/features/chat/components/files/FilePreview";
import FileUpload from "@/features/chat/components/files/FileUpload";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useSendMessage } from "@/hooks/useSendMessage";
import { posthog } from "@/lib";
import {
  useComposerFiles,
  useComposerModeSelection,
  useComposerTextActions,
  useComposerUI,
  useInputText,
} from "@/stores/composerStore";
import { useReplyToMessage } from "@/stores/replyToMessageStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";
import type { FileData, SearchMode } from "@/types/shared";

import ComposerInput, { type ComposerInputRef } from "./ComposerInput";
import ComposerToolbar from "./ComposerToolbar";
import IntegrationsBanner from "./IntegrationsBanner";
import SelectedCalendarEventIndicator from "./SelectedCalendarEventIndicator";
import SelectedReplyIndicator from "./SelectedReplyIndicator";
import SelectedToolIndicator from "./SelectedToolIndicator";
import SelectedWorkflowIndicator from "./SelectedWorkflowIndicator";

interface MainSearchbarProps {
  scrollToBottom: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  fileUploadRef?: React.RefObject<{
    openFileUploadModal: () => void;
    handleDroppedFiles: (files: File[]) => void;
  } | null>;
  appendToInputRef?: React.RefObject<((text: string) => void) | null>;
  droppedFiles?: File[];
  onDroppedFilesProcessed?: () => void;
  hasMessages: boolean;
  conversationId?: string;
  // voiceModeActive: () => void;
}

const Composer: React.FC<MainSearchbarProps> = ({
  scrollToBottom,
  inputRef,
  fileUploadRef,
  appendToInputRef,
  droppedFiles,
  onDroppedFilesProcessed,
  hasMessages,
  conversationId,
  // voiceModeActive,
}) => {
  const [currentHeight, setCurrentHeight] = useState<number>(24);
  const composerInputRef = useRef<ComposerInputRef>(null);
  const inputText = useInputText();
  const { setInputText, clearInputText } = useComposerTextActions();
  const {
    selectedMode,
    selectedTool,
    selectedToolCategory,
    setSelectedMode,
    setSelectedTool,
    setSelectedToolCategory,
    clearToolSelection,
  } = useComposerModeSelection();
  const {
    fileUploadModal,
    uploadedFiles,
    uploadedFileData,
    pendingDroppedFiles,
    setFileUploadModal,
    setUploadedFiles,
    setUploadedFileData,
    setPendingDroppedFiles,
    removeUploadedFile,
    clearAllFiles,
  } = useComposerFiles();
  const { isSlashCommandDropdownOpen, setIsSlashCommandDropdownOpen } =
    useComposerUI();
  const { selectedWorkflow, clearSelectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent, clearSelectedCalendarEvent } =
    useCalendarEventSelection();
  const { replyToMessage, clearReplyToMessage, setInputFocusCallback } =
    useReplyToMessage();
  const { autoSend } = useWorkflowSelectionStore();

  const sendMessage = useSendMessage();
  const { isLoading, setIsLoading } = useLoading();
  const { setContextualLoading } = useLoadingText();
  const { integrations, isLoading: integrationsLoading } = useIntegrations();
  const currentMode = useMemo(
    () => Array.from(selectedMode)[0],
    [selectedMode],
  );

  // Ref to prevent duplicate execution in StrictMode
  const autoSendExecutedRef = useRef(false);

  // Set up input focus callback for reply-to-message functionality
  useEffect(() => {
    setInputFocusCallback(() => {
      if (inputRef.current) {
        inputRef.current.focus();
      }
    });

    // Clean up on unmount
    return () => setInputFocusCallback(null);
  }, [inputRef, setInputFocusCallback]);

  // When workflow is selected, handle auto-send with a brief delay to allow UI to update
  useEffect(() => {
    if (!(selectedWorkflow && autoSend)) return;

    // Prevent duplicate execution in React StrictMode
    if (autoSendExecutedRef.current) {
      console.warn("Auto-send already executed, preventing duplicate");
      return;
    }
    autoSendExecutedRef.current = true;

    // Clear state immediately to prevent any race conditions
    // Note: clearSelectedWorkflow() already sets autoSend to false
    clearSelectedWorkflow();

    setIsLoading(true);
    sendMessage("Run this workflow", {
      files: uploadedFileData,
      selectedWorkflow,
      selectedTool: selectedTool ?? null,
      selectedToolCategory: selectedToolCategory ?? null,
    });

    if (inputRef.current) inputRef.current.focus();

    // Scroll to show the composer instead of bottom when workflow runs
    setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }
    }, 200); // Small delay to allow message to render
  }, [
    inputRef,
    selectedWorkflow,
    selectedTool,
    selectedToolCategory,
    uploadedFileData,
    autoSend,
    clearSelectedWorkflow,
    sendMessage,
    setIsLoading,
  ]);

  // Reset the auto-send guard when state changes
  useEffect(() => {
    if (!selectedWorkflow || !autoSend) autoSendExecutedRef.current = false;
  }, [selectedWorkflow, autoSend]);

  // Expose file upload functions to parent component via ref
  useImperativeHandle(
    fileUploadRef,
    () => ({
      openFileUploadModal: () => setFileUploadModal(true),
      handleDroppedFiles: (files: File[]) => {
        setPendingDroppedFiles(files);
      },
    }),
    [setFileUploadModal, setPendingDroppedFiles],
  );

  useEffect(() => {
    if (fileUploadModal && pendingDroppedFiles.length > 0) {
      // Just clear the pending files here after the modal is opened
      setPendingDroppedFiles([]);
      if (onDroppedFilesProcessed) {
        onDroppedFilesProcessed();
      }
    }
  }, [
    fileUploadModal,
    pendingDroppedFiles,
    onDroppedFilesProcessed,
    setPendingDroppedFiles,
  ]);

  // Process any droppedFiles passed from parent when they change
  useEffect(() => {
    if (droppedFiles && droppedFiles.length > 0) {
      setPendingDroppedFiles(droppedFiles);
      setFileUploadModal(true);
    }
  }, [droppedFiles, setPendingDroppedFiles, setFileUploadModal]);

  const handleFormSubmit = (e?: React.FormEvent<HTMLFormElement>) => {
    if (e) e.preventDefault();

    // Prevent double execution when workflow is auto-sending
    if (autoSend) return;

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
    // Use contextual loading with user's message for similarity-based loading text
    setContextualLoading(true, inputText);

    // Track message send event with PostHog
    posthog.capture("chat:message_sent", {
      has_text: !!inputText,
      has_files: uploadedFiles.length > 0,
      file_count: uploadedFiles.length,
      has_tool: !!selectedTool,
      tool_name: selectedTool,
      tool_category: selectedToolCategory,
      has_workflow: !!selectedWorkflow,
      workflow_name: selectedWorkflow?.title,
      conversation_id: conversationId,
    });

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

  const handleKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (
    event,
  ) => {
    if (event.key === "Enter" && !event.shiftKey && !isLoading) {
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
    }
  };

  const openFileUploadModal = () => {
    setFileUploadModal(true);
  };

  const handleSelectionChange = (mode: SearchMode) => {
    if (currentMode === mode) setSelectedMode(new Set([null]));
    else setSelectedMode(new Set([mode]));
    // Clear selected tool when mode changes
    setSelectedTool(null);
    setSelectedToolCategory(null);
    // Clear selected workflow when mode changes
    clearSelectedWorkflow();
    // Clear selected calendar event when mode changes
    clearSelectedCalendarEvent();
    // If the user selects upload_file mode, open the file selector immediately
    if (mode === "upload_file")
      setTimeout(() => {
        openFileUploadModal();
      }, 100);
  };

  const handleSlashCommandSelect = (toolName: string, toolCategory: string) => {
    setSelectedTool(toolName);
    setSelectedToolCategory(toolCategory);
    // Clear the current mode when a tool is selected via slash command
    setSelectedMode(new Set([null]));
    // Clear selected workflow when tool is selected
    clearSelectedWorkflow();
    // Clear selected calendar event when tool is selected
    clearSelectedCalendarEvent();
  };

  const handleRemoveSelectedTool = () => {
    setSelectedTool(null);
    setSelectedToolCategory(null);
  };

  const handleToggleSlashCommandDropdown = () => {
    console.log("test");
    // Focus the input first - this will naturally trigger slash command detection
    if (inputRef.current) {
      inputRef.current.focus();
    }

    composerInputRef.current?.toggleSlashCommandDropdown();
    // Update the state to reflect the current dropdown state
    setIsSlashCommandDropdownOpen(
      composerInputRef.current?.isSlashCommandDropdownOpen() || false,
    );
  };

  // Global hotkey to trigger slash command dropdown with '/' key
  useHotkeys(
    "slash",
    () => {
      handleToggleSlashCommandDropdown();
    },
    {
      enableOnFormTags: false, // Don't trigger when typing in inputs
      preventDefault: true,
    },
  );

  // Sync the state with the actual dropdown state
  useEffect(() => {
    const interval = setInterval(() => {
      const isOpen =
        composerInputRef.current?.isSlashCommandDropdownOpen() || false;
      setIsSlashCommandDropdownOpen(isOpen);
    }, 100);

    return () => clearInterval(interval);
  }, [setIsSlashCommandDropdownOpen]);

  const handleFilesUploaded = (files: UploadedFilePreview[]) => {
    if (files.length === 0) {
      // If no files, just clear the uploaded files
      setUploadedFiles([]);
      setUploadedFileData([]);
      return;
    }

    // Check if these are temporary files (with loading state) or final uploaded files
    const tempFiles = files.some((file) => file.isUploading);

    if (tempFiles) {
      // These are temporary files with loading state, just set them
      setUploadedFiles(files);
      return;
    }
    // These are the final uploaded files, replace temp files with final versions
    setUploadedFiles(
      files.map((file) => {
        // Find the corresponding final file (if any)
        const finalFile = files.find((f) => f.tempId === file.id);
        // If found, return the final file, otherwise keep the previous file
        return finalFile || file;
      }),
    );

    // Now process the complete file data from the response
    const fileDataArray = files.map((file) => {
      // For files that have complete response data (not temp files):
      // Use the data from the API response, including description and message
      return {
        fileId: file.id,
        url: file.url,
        filename: file.name,
        description: file.description || `File: ${file.name}`,
        type: file.type,
        message: file.message || "File uploaded successfully",
      } as FileData;
    });

    // Store the complete file data
    setUploadedFileData(fileDataArray);
  };

  // Handle paste event for images
  const handlePaste = useCallback(
    (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf("image") !== -1) {
          const file = items[i].getAsFile();
          if (file) {
            e.preventDefault();
            // Open the file upload modal with the pasted image
            setFileUploadModal(true);
            setPendingDroppedFiles([file]); // Store the pasted file
            break;
          }
        }
      }
    },
    [setFileUploadModal, setPendingDroppedFiles],
  );

  // Add paste event listener for images
  useEffect(() => {
    document.addEventListener("paste", handlePaste);
    return () => {
      document.removeEventListener("paste", handlePaste);
    };
  }, [handlePaste]);

  // Function to append text to the input
  const appendToInput = useCallback(
    (text: string) => {
      const newText = inputText ? `${inputText} ${text}` : text;
      setInputText(newText);
      // Focus the input after appending
      if (inputRef.current) {
        inputRef.current.focus();
      }
    },
    [inputText, setInputText, inputRef],
  );

  // Expose appendToInput function to parent via ref
  useImperativeHandle(appendToInputRef, () => appendToInput, [appendToInput]);

  return (
    <div className="searchbar_container relative flex w-full flex-col justify-center pb-1">
      <div className="searchbar relative transition-all z-2 rounded-3xl bg-zinc-800 px-1 pt-1 pb-2">
        <IntegrationsBanner
          integrations={integrations}
          isLoading={integrationsLoading}
          hasMessages={hasMessages}
          onToggleSlashCommand={handleToggleSlashCommandDropdown}
        />
        <FilePreview files={uploadedFiles} onRemove={removeUploadedFile} />
        <SelectedToolIndicator
          toolName={selectedTool}
          toolCategory={selectedToolCategory}
          onRemove={handleRemoveSelectedTool}
        />
        <SelectedWorkflowIndicator
          workflow={selectedWorkflow}
          onRemove={clearSelectedWorkflow}
        />
        <SelectedCalendarEventIndicator
          event={selectedCalendarEvent}
          onRemove={clearSelectedCalendarEvent}
        />
        <SelectedReplyIndicator
          replyToMessage={replyToMessage}
          onRemove={clearReplyToMessage}
          onNavigate={(messageId) => {
            // Scroll to the message being replied to
            const messageElement = document.getElementById(messageId);
            if (messageElement) {
              messageElement.scrollIntoView({
                behavior: "smooth",
                block: "center",
              });
              // Brief visual highlight
              messageElement.style.transition = "all 0.3s ease";
              messageElement.style.scale = "1.02";
              setTimeout(() => {
                messageElement.style.scale = "1";
              }, 300);
            }
          }}
        />
        <ComposerInput
          ref={composerInputRef}
          searchbarText={inputText}
          onSearchbarTextChange={setInputText}
          handleFormSubmit={handleFormSubmit}
          handleKeyDown={handleKeyDown}
          currentHeight={currentHeight}
          onHeightChange={setCurrentHeight}
          inputRef={inputRef}
          hasMessages={hasMessages}
          onSlashCommandSelect={handleSlashCommandSelect}
        />
        <ComposerToolbar
          selectedMode={selectedMode}
          openFileUploadModal={openFileUploadModal}
          handleFormSubmit={handleFormSubmit}
          searchbarText={inputText}
          handleSelectionChange={handleSelectionChange}
          selectedTool={selectedTool}
          onToggleSlashCommandDropdown={handleToggleSlashCommandDropdown}
          isSlashCommandDropdownOpen={isSlashCommandDropdownOpen}
          // voiceModeActive={voiceModeActive}
        />
      </div>
      <FileUpload
        open={fileUploadModal}
        onOpenChange={setFileUploadModal}
        onFilesUploaded={handleFilesUploaded}
        initialFiles={pendingDroppedFiles}
        isPastedFile={pendingDroppedFiles.some((file) =>
          file.type.includes("image"),
        )}
      />
    </div>
  );
};

export default Composer;
