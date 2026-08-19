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
  onVoiceModeHover?: () => void;
}

function ComposerIndicators({
  uploadedFiles,
  removeUploadedFile,
  selectedTool,
  selectedToolCategory,
  onRemoveSelectedTool,
  selectedWorkflow,
  onRemoveWorkflow,
  selectedCalendarEvent,
  onRemoveCalendarEvent,
  replyToMessage,
  onRemoveReply,
}: {
  uploadedFiles: ReturnType<typeof useComposerFiles>["uploadedFiles"];
  removeUploadedFile: ReturnType<typeof useComposerFiles>["removeUploadedFile"];
  selectedTool: string | null;
  selectedToolCategory: string | null;
  onRemoveSelectedTool: () => void;
  selectedWorkflow: ReturnType<typeof useWorkflowSelection>["selectedWorkflow"];
  onRemoveWorkflow: () => void;
  selectedCalendarEvent: ReturnType<
    typeof useCalendarEventSelection
  >["selectedCalendarEvent"];
  onRemoveCalendarEvent: () => void;
  replyToMessage: ReturnType<typeof useReplyToMessage>["replyToMessage"];
  onRemoveReply: () => void;
}) {
  return (
    <div className="relative z-10">
      <FilePreview files={uploadedFiles} onRemove={removeUploadedFile} />
      <SelectedToolIndicator
        toolName={selectedTool}
        toolCategory={selectedToolCategory}
        onRemove={onRemoveSelectedTool}
      />
      <SelectedWorkflowIndicator
        workflow={selectedWorkflow}
        onRemove={onRemoveWorkflow}
      />
      <SelectedCalendarEventIndicator
        event={selectedCalendarEvent}
        onRemove={onRemoveCalendarEvent}
      />
      <SelectedReplyIndicator
        replyToMessage={replyToMessage}
        onRemove={onRemoveReply}
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
  );
}

function ComposerHiddenFileInput({
  fileInputRef,
  onFileChange,
}: {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <input
      type="file"
      ref={fileInputRef}
      className="hidden"
      onChange={onFileChange}
      accept={ALLOWED_FILE_TYPES.join(",")}
      multiple
    />
  );
}

function useComposerPaste(
  inputRef: React.RefObject<HTMLTextAreaElement | null>,
  attachFiles: (files: File[]) => Promise<void>,
) {
  const handlePasteRef = useRef<(e: ClipboardEvent) => void>(() => {
    // placeholder: replaced in effect below
  });

  useEffect(() => {
    handlePasteRef.current = (e: ClipboardEvent) => {
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
      const text = e.clipboardData?.getData("text/plain");
      if (text && text.length > LARGE_PASTE_THRESHOLD_CHARS) {
        e.preventDefault();
        attachFiles([
          new File([text], PASTED_TEXT_FILENAME, { type: "text/plain" }),
        ]);
      }
    };
  });

  useEffect(() => {
    const listener = (e: ClipboardEvent) => handlePasteRef.current(e);
    document.addEventListener("paste", listener);
    return () => {
      document.removeEventListener("paste", listener);
    };
  }, []);
}

function useComposerSlashSync(
  composerInputRef: React.RefObject<ComposerInputRef | null>,
  setIsSlashCommandDropdownOpen: (open: boolean) => void,
) {
  useEffect(() => {
    const interval = setInterval(() => {
      const isOpen =
        composerInputRef.current?.isSlashCommandDropdownOpen() || false;
      setIsSlashCommandDropdownOpen(isOpen);
    }, 100);
    return () => clearInterval(interval);
  }, [composerInputRef, setIsSlashCommandDropdownOpen]);
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

  useEffect(() => {
    setInputFocusCallback(() => {
      if (inputRef.current) {
        inputRef.current.focus();
      }
    });
    return () => setInputFocusCallback(null);
  }, [inputRef, setInputFocusCallback]);

  useImperativeHandle(fileUploadRef, () => ({ attachFiles }), [attachFiles]);

  const handleFormSubmit = (e?: React.FormEvent<HTMLFormElement>) => {
    if (e) e.preventDefault();
    if (autoSend) return;
    if (isUploadingFiles) return;
    if (
      !inputText &&
      uploadedFiles.length === 0 &&
      !selectedTool &&
      !selectedWorkflow &&
      !selectedCalendarEvent
    ) {
      return;
    }
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
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleFormSubmit();
    }
    if (event.key === "Escape" && !isSlashCommandDropdownOpen) {
      if (selectedTool) {
        event.preventDefault();
        handleRemoveSelectedTool();
      } else if (selectedWorkflow) {
        event.preventDefault();
        clearSelectedWorkflow();
      } else if (replyToMessage) {
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
    e.target.value = "";
    if (files.length > 0) attachFiles(files);
  };

  const handleSelectionChange = (mode: SearchMode) => {
    if (currentMode === mode) setSelectedMode(new Set([null]));
    else setSelectedMode(new Set([mode]));
    setSelectedTool(null);
    setSelectedToolCategory(null);
    clearSelectedWorkflow();
    clearSelectedCalendarEvent();
    if (mode === "upload_file")
      setTimeout(() => {
        openFilePicker();
      }, 100);
  };

  const handleSlashCommandSelect = (toolName: string, toolCategory: string) => {
    setSelectedTool(toolName);
    setSelectedToolCategory(toolCategory);
    setSelectedMode(new Set([null]));
    clearSelectedWorkflow();
    clearSelectedCalendarEvent();
  };

  const handleRemoveSelectedTool = () => {
    setSelectedTool(null);
    setSelectedToolCategory(null);
  };

  const handleIntegrationClick = useCallback(
    (integrationId: string) => {
      composerInputRef.current?.toggleSlashCommandDropdown();
      setIsSlashCommandDropdownOpen(false);
      router.push(`/integrations?id=${encodeURIComponent(integrationId)}`);
    },
    [router, setIsSlashCommandDropdownOpen],
  );

  const handleToggleSlashCommandDropdown = () => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
    composerInputRef.current?.toggleSlashCommandDropdown();
    setIsSlashCommandDropdownOpen(
      composerInputRef.current?.isSlashCommandDropdownOpen() || false,
    );
  };

  useHotkeys(
    "slash",
    () => {
      handleToggleSlashCommandDropdown();
    },
    {
      enableOnFormTags: false,
      preventDefault: true,
    },
  );

  useComposerSlashSync(composerInputRef, setIsSlashCommandDropdownOpen);
  useComposerPaste(inputRef, attachFiles);

  const appendToInput = useCallback(
    (text: string) => {
      const newText = inputText ? `${inputText} ${text}` : text;
      setInputText(newText);
      if (inputRef.current) {
        inputRef.current.focus();
      }
    },
    [inputText, setInputText, inputRef],
  );

  useImperativeHandle(appendToInputRef, () => appendToInput, [appendToInput]);

  return (
    <div className="searchbar_container relative flex w-full flex-col justify-center pb-1">
      <div className="searchbar relative transition-[width] z-2 rounded-3xl bg-zinc-800 px-1 pt-1 pb-2">
        <IntegrationsBanner
          integrations={integrations}
          isLoading={integrationsLoading}
          hasMessages={hasMessages}
          onToggleSlashCommand={handleToggleSlashCommandDropdown}
        />
        <ComposerIndicators
          uploadedFiles={uploadedFiles}
          removeUploadedFile={removeUploadedFile}
          selectedTool={selectedTool}
          selectedToolCategory={selectedToolCategory}
          onRemoveSelectedTool={handleRemoveSelectedTool}
          selectedWorkflow={selectedWorkflow}
          onRemoveWorkflow={clearSelectedWorkflow}
          selectedCalendarEvent={selectedCalendarEvent}
          onRemoveCalendarEvent={clearSelectedCalendarEvent}
          replyToMessage={replyToMessage}
          onRemoveReply={clearReplyToMessage}
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
      <ComposerHiddenFileInput
        fileInputRef={fileInputRef}
        onFileChange={handleFileInputChange}
      />
    </div>
  );
};

export default Composer;
