import type React from "react";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

import FilePreview from "@/features/chat/components/files/FilePreview";
import { ALLOWED_FILE_TYPES } from "@/features/chat/constants/files";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useComposerPaste } from "@/features/chat/hooks/useComposerPaste";
import { useComposerSubmit } from "@/features/chat/hooks/useComposerSubmit";
import { useFileAttachments } from "@/features/chat/hooks/useFileAttachments";
import { useSlashCommandDropdownControl } from "@/features/chat/hooks/useSlashCommandDropdownControl";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import {
  useComposerFiles,
  useComposerModeSelection,
  useComposerTextActions,
  useComposerUI,
  useInputText,
} from "@/stores/composerStore";
import { useReplyToMessage } from "@/stores/replyToMessageStore";
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
  const [currentHeight, setCurrentHeight] = useState<number>(24);
  const composerInputRef = useRef<ComposerInputRef>(null);
  const inputText = useInputText();
  const { setInputText } = useComposerTextActions();
  const {
    selectedMode,
    selectedTool,
    selectedToolCategory,
    setSelectedMode,
    setSelectedTool,
    setSelectedToolCategory,
  } = useComposerModeSelection();
  const { uploadedFiles, removeUploadedFile } = useComposerFiles();
  const { isSlashCommandDropdownOpen, setIsSlashCommandDropdownOpen } =
    useComposerUI();
  const { selectedWorkflow, clearSelectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent, clearSelectedCalendarEvent } =
    useCalendarEventSelection();
  const { replyToMessage, clearReplyToMessage, setInputFocusCallback } =
    useReplyToMessage();

  const { handleFormSubmit, handleRemoveSelectedTool, handleKeyDown } =
    useComposerSubmit({ inputRef, scrollToBottom });
  const { attachFiles } = useFileAttachments();
  useComposerPaste({ inputRef, attachFiles });
  const { handleToggleSlashCommandDropdown, handleIntegrationClick } =
    useSlashCommandDropdownControl({
      composerInputRef,
      inputRef,
      setIsSlashCommandDropdownOpen,
    });
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

  const fileInputRef = useRef<HTMLInputElement>(null);

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
      <div className="searchbar relative transition-[height] z-2 rounded-3xl bg-zinc-800 px-1 pt-1 pb-2">
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
                messageElement.style.transition = "scale 0.3s ease";
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
