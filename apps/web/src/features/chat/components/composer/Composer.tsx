import { useRouter } from "next/navigation";
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

import FilePreview from "@/features/chat/components/files/FilePreview";
import {
  ALLOWED_FILE_TYPES,
  LARGE_PASTE_THRESHOLD_CHARS,
  PASTED_TEXT_FILENAME,
} from "@/features/chat/constants/files";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useFileAttachments } from "@/features/chat/hooks/useFileAttachments";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
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
import type { SearchMode } from "@/types/shared/searchTypes";

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
    attachFiles: (files: File[]) => Promise<void>;
  } | null>;
  appendToInputRef?: React.RefObject<((text: string) => void) | null>;
  hasMessages: boolean;
  voiceModeActive: () => void;
  /** Hover intent on the voice button — used to prefetch the session token. */
  onVoiceModeHover?: () => void;
}

const Composer: React.FC<MainSearchbarProps> = ({
  scrollToBottom,
  inputRef,
  fileUploadRef,
  appendToInputRef,
  hasMessages,
  voiceModeActive,
  onVoiceModeHover,
}) => {
  const router = useRouter();
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
  const { uploadedFiles, uploadedFileData, removeUploadedFile, clearAllFiles } =
    useComposerFiles();
  const isUploadingFiles = useComposerIsUploading();
  const { isSlashCommandDropdownOpen, setIsSlashCommandDropdownOpen } =
    useComposerUI();
  const { selectedWorkflow, clearSelectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent, clearSelectedCalendarEvent } =
    useCalendarEventSelection();
  const { replyToMessage, clearReplyToMessage, setInputFocusCallback } =
    useReplyToMessage();
  const { autoSend } = useWorkflowSelectionStore();

  const sendMessage = useSendMessage();
  const { attachFiles } = useFileAttachments();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { integrations, isLoading: integrationsLoading } = useIntegrations();
  const currentMode = useMemo(
    () => Array.from(selectedMode)[0],
    [selectedMode],
  );

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

  // NOTE: Workflow auto-send logic lives in ChatPage, NOT here.
  // Composer remounts across the NewChatLayout → ChatWithMessages layout
  // switch that happens when the optimistic message makes hasMessages toggle
  // to true, which would reset the once-only guard and fire the workflow
  // twice. ChatPage is memoized and never remounts, so it hosts that guard.

  // Let the parent (drag-and-drop on the chat page) attach files directly.
  useImperativeHandle(fileUploadRef, () => ({ attachFiles }), [attachFiles]);

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

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    // Reset so picking the same file again re-triggers onChange.
    e.target.value = "";
    if (files.length > 0) attachFiles(files);
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
        openFilePicker();
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

  // Handle clicking on an integration in the slash command dropdown
  const handleIntegrationClick = useCallback(
    (integrationId: string) => {
      // Close the dropdown first
      composerInputRef.current?.toggleSlashCommandDropdown();
      setIsSlashCommandDropdownOpen(false);
      // Navigate to integrations page with id param
      router.push(`/integrations?id=${encodeURIComponent(integrationId)}`);
    },
    [router, setIsSlashCommandDropdownOpen],
  );

  const handleToggleSlashCommandDropdown = () => {
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

  // Store paste handler in a ref to avoid re-subscribing the event listener
  // whenever dependencies change (advanced-event-handler-refs pattern).
  const handlePasteRef = useRef((_e: ClipboardEvent) => {
    /* placeholder: replaced with the real handler on the next line */
  });
  handlePasteRef.current = (e: ClipboardEvent) => {
    // Only react to pastes inside the composer input — an image pasted into
    // any other element while Composer is mounted must not be captured.
    if (e.target !== inputRef.current) return;

    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image") !== -1) {
        const file = items[i].getAsFile();
        if (file) {
          e.preventDefault();
          attachFiles([file]);
          return;
        }
      }
    }

    // Large text pasted into the composer becomes a .txt attachment instead of
    // inline text — keeps the input responsive and rides the file pipeline.
    const text = e.clipboardData?.getData("text/plain");
    if (text && text.length > LARGE_PASTE_THRESHOLD_CHARS) {
      e.preventDefault();
      attachFiles([
        new File([text], PASTED_TEXT_FILENAME, { type: "text/plain" }),
      ]);
    }
  };

  // Add paste event listener for images (stable subscription)
  useEffect(() => {
    const listener = (e: ClipboardEvent) => handlePasteRef.current(e);
    document.addEventListener("paste", listener);
    return () => {
      document.removeEventListener("paste", listener);
    };
  }, []);

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
        {/* relative z-10 ensures indicators always paint above the absolute banner */}
        <div className="relative z-10">
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
              const messageElement = document.getElementById(messageId);
              if (messageElement) {
                messageElement.scrollIntoView({
                  behavior: "smooth",
                  block: "center",
                });
                messageElement.style.transition = "all 0.3s ease";
                messageElement.style.scale = "1.02";
                setTimeout(() => {
                  messageElement.style.scale = "1";
                }, 300);
              }
            }}
          />
        </div>
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
          onIntegrationClick={handleIntegrationClick}
        />
        <ComposerToolbar
          selectedMode={selectedMode}
          openFilePicker={openFilePicker}
          handleFormSubmit={handleFormSubmit}
          searchbarText={inputText}
          handleSelectionChange={handleSelectionChange}
          selectedTool={selectedTool}
          onToggleSlashCommandDropdown={handleToggleSlashCommandDropdown}
          isSlashCommandDropdownOpen={isSlashCommandDropdownOpen}
          voiceModeActive={voiceModeActive}
          onVoiceModeHover={onVoiceModeHover}
        />
      </div>
      <input
        type="file"
        ref={fileInputRef}
        className="hidden"
        onChange={handleFileInputChange}
        accept={ALLOWED_FILE_TYPES.join(",")}
        multiple
      />
    </div>
  );
};

export default Composer;
