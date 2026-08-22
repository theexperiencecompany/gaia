import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";
import type { UploadedFilePreview } from "@/features/chat/components/files/FilePreview";
import {
  DEFAULT_DEV_COMMS_MODEL,
  DEFAULT_DEV_EXECUTOR_MODEL,
} from "@/features/chat/constants/devModels";
import { stripLocalePrefix } from "@/i18n/config";
import type { FileData } from "@/types/shared/fileTypes";
import type { SearchMode } from "@/types/shared/searchTypes";

interface ComposerState {
  // Text input state
  pendingPrompt: string | null;
  /** True when the pending prompt should be SENT on chat mount, not prefilled. */
  pendingAutoSend: boolean;
  inputText: string;

  // Mode and tool selection
  selectedMode: Set<SearchMode>;
  selectedTool: string | null;
  selectedToolCategory: string | null;

  // File management
  uploadedFiles: UploadedFilePreview[];
  uploadedFileData: FileData[];

  // UI state
  isSlashCommandDropdownOpen: boolean;

  // DEV-ONLY model selection (chat-header selector; only used in development)
  useDefaultModels: boolean;
  commsModel: string;
  executorModel: string;
}

interface ComposerActions {
  // Text input actions
  appendToInput: (text: string) => void;
  setPendingPrompt: (prompt: string | null) => void;
  clearPendingPrompt: () => void;
  /** Palette ask-handoff flag: the pending prompt sends instead of prefilling. */
  setPendingAutoSend: (autoSend: boolean) => void;
  setInputText: (text: string) => void;
  appendToInputText: (text: string) => void;
  clearInputText: () => void;

  // Mode and tool actions
  setSelectedMode: (mode: Set<SearchMode>) => void;
  setSelectedTool: (tool: string | null, category?: string | null) => void;
  setSelectedToolCategory: (category: string | null) => void;
  clearToolSelection: () => void;

  // File management actions
  setUploadedFiles: (files: UploadedFilePreview[]) => void;
  addUploadedFile: (file: UploadedFilePreview) => void;
  replaceUploadedFile: (tempId: string, file: UploadedFilePreview) => void;
  removeUploadedFile: (fileId: string) => void;
  setUploadedFileData: (data: FileData[]) => void;
  addUploadedFileData: (data: FileData) => void;
  removeUploadedFileData: (fileId: string) => void;
  clearAllFiles: () => void;

  // UI actions
  setIsSlashCommandDropdownOpen: (open: boolean) => void;

  // DEV-ONLY model selection actions
  setUseDefaultModels: (use: boolean) => void;
  setCommsModel: (model: string) => void;
  setExecutorModel: (model: string) => void;

  // Reset actions
  resetComposer: () => void;
}

type ComposerStore = ComposerState & ComposerActions;

const initialState: ComposerState = {
  // Text input state
  pendingPrompt: null,
  pendingAutoSend: false,
  inputText: "",

  // Mode and tool selection
  selectedMode: new Set([null]),
  selectedTool: null,
  selectedToolCategory: null,

  // File management
  uploadedFiles: [],
  uploadedFileData: [],

  // UI state
  isSlashCommandDropdownOpen: false,

  // DEV-ONLY model selection
  useDefaultModels: true,
  commsModel: DEFAULT_DEV_COMMS_MODEL,
  executorModel: DEFAULT_DEV_EXECUTOR_MODEL,
};

export const useComposerStore = create<ComposerStore>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,

        // Text input actions
        appendToInput: (text) => {
          set({ pendingPrompt: text }, false, "appendToInput");
          // Navigate to chat page if not already there
          if (
            typeof window !== "undefined" &&
            stripLocalePrefix(window.location.pathname).startsWith("/c") ===
              false
          ) {
            // Use Next.js programmatic navigation
            window.location.assign("/c");
          }
        },

        setPendingPrompt: (pendingPrompt) =>
          set({ pendingPrompt }, false, "setPendingPrompt"),

        clearPendingPrompt: () => {
          set({ pendingPrompt: null }, false, "clearPendingPrompt");
        },

        setPendingAutoSend: (pendingAutoSend) =>
          set({ pendingAutoSend }, false, "setPendingAutoSend"),

        setInputText: (inputText) => {
          set({ inputText }, false, "setInputText");
        },

        appendToInputText: (text) =>
          set(
            (state) => {
              const newText = state.inputText
                ? `${state.inputText} ${text}`
                : text;
              return { inputText: newText };
            },
            false,
            "appendToInputText",
          ),

        clearInputText: () => {
          set({ inputText: "" }, false, "clearInputText");
        },

        // Mode and tool actions
        setSelectedMode: (selectedMode) =>
          set({ selectedMode }, false, "setSelectedMode"),

        setSelectedTool: (selectedTool, selectedToolCategory = null) =>
          set({ selectedTool, selectedToolCategory }, false, "setSelectedTool"),

        setSelectedToolCategory: (selectedToolCategory) =>
          set({ selectedToolCategory }, false, "setSelectedToolCategory"),

        clearToolSelection: () =>
          set(
            { selectedTool: null, selectedToolCategory: null },
            false,
            "clearToolSelection",
          ),

        // File management actions
        setUploadedFiles: (uploadedFiles) =>
          set({ uploadedFiles }, false, "setUploadedFiles"),

        addUploadedFile: (file) =>
          set(
            (state) => ({ uploadedFiles: [...state.uploadedFiles, file] }),
            false,
            "addUploadedFile",
          ),

        replaceUploadedFile: (tempId, file) =>
          set(
            (state) => ({
              uploadedFiles: state.uploadedFiles.map((f) =>
                f.id === tempId ? file : f,
              ),
            }),
            false,
            "replaceUploadedFile",
          ),

        removeUploadedFile: (fileId) =>
          set(
            (state) => ({
              uploadedFiles: state.uploadedFiles.filter((f) => f.id !== fileId),
              uploadedFileData: state.uploadedFileData.filter(
                (f) => f.fileId !== fileId,
              ),
            }),
            false,
            "removeUploadedFile",
          ),

        setUploadedFileData: (uploadedFileData) =>
          set({ uploadedFileData }, false, "setUploadedFileData"),

        addUploadedFileData: (data) =>
          set(
            (state) => ({
              uploadedFileData: [...state.uploadedFileData, data],
            }),
            false,
            "addUploadedFileData",
          ),

        removeUploadedFileData: (fileId) =>
          set(
            (state) => ({
              uploadedFileData: state.uploadedFileData.filter(
                (f) => f.fileId !== fileId,
              ),
            }),
            false,
            "removeUploadedFileData",
          ),

        clearAllFiles: () =>
          set(
            {
              uploadedFiles: [],
              uploadedFileData: [],
            },
            false,
            "clearAllFiles",
          ),

        // UI actions
        setIsSlashCommandDropdownOpen: (isSlashCommandDropdownOpen) =>
          set(
            { isSlashCommandDropdownOpen },
            false,
            "setIsSlashCommandDropdownOpen",
          ),

        // DEV-ONLY model selection actions
        setUseDefaultModels: (useDefaultModels) =>
          set({ useDefaultModels }, false, "setUseDefaultModels"),
        setCommsModel: (commsModel) =>
          set({ commsModel }, false, "setCommsModel"),
        setExecutorModel: (executorModel) =>
          set({ executorModel }, false, "setExecutorModel"),

        // Reset actions
        resetComposer: () => {
          set(initialState, false, "resetComposer");
        },
      }),
      {
        name: "composer-storage",
        partialize: (state) => ({
          inputText: state.inputText,
          pendingPrompt: state.pendingPrompt,
          useDefaultModels: state.useDefaultModels,
          commsModel: state.commsModel,
          executorModel: state.executorModel,
        }),
      },
    ),
    { name: "composer-store" },
  ),
); // Selectors for easy access
export const usePendingPrompt = () =>
  useComposerStore((state) => state.pendingPrompt);

export const useAppendToInput = () =>
  useComposerStore((state) => state.appendToInput);

export const useInputText = () => useComposerStore((state) => state.inputText);

export const useComposerTextActions = () =>
  useComposerStore(
    useShallow((state) => ({
      setInputText: state.setInputText,
      appendToInputText: state.appendToInputText,
      clearInputText: state.clearInputText,
      clearPendingPrompt: state.clearPendingPrompt,
      setPendingPrompt: state.setPendingPrompt,
    })),
  );

export const useComposerModeSelection = () =>
  useComposerStore(
    useShallow((state) => ({
      selectedMode: state.selectedMode,
      selectedTool: state.selectedTool,
      selectedToolCategory: state.selectedToolCategory,
      setSelectedMode: state.setSelectedMode,
      setSelectedTool: state.setSelectedTool,
      setSelectedToolCategory: state.setSelectedToolCategory,
      clearToolSelection: state.clearToolSelection,
    })),
  );

export const useComposerFiles = () =>
  useComposerStore(
    useShallow((state) => ({
      uploadedFiles: state.uploadedFiles,
      uploadedFileData: state.uploadedFileData,
      setUploadedFiles: state.setUploadedFiles,
      addUploadedFile: state.addUploadedFile,
      replaceUploadedFile: state.replaceUploadedFile,
      removeUploadedFile: state.removeUploadedFile,
      setUploadedFileData: state.setUploadedFileData,
      addUploadedFileData: state.addUploadedFileData,
      removeUploadedFileData: state.removeUploadedFileData,
      clearAllFiles: state.clearAllFiles,
    })),
  );

// True while any composer file is still uploading. Send is blocked until this
// clears so a message never goes out before its attachment finishes uploading.
export const useComposerIsUploading = () =>
  useComposerStore((state) =>
    state.uploadedFiles.some((file) => file.isUploading),
  );

export const useComposerUI = () =>
  useComposerStore(
    useShallow((state) => ({
      isSlashCommandDropdownOpen: state.isSlashCommandDropdownOpen,
      setIsSlashCommandDropdownOpen: state.setIsSlashCommandDropdownOpen,
    })),
  );

export const useComposerModelSelection = () =>
  useComposerStore(
    useShallow((state) => ({
      useDefaultModels: state.useDefaultModels,
      commsModel: state.commsModel,
      executorModel: state.executorModel,
      setUseDefaultModels: state.setUseDefaultModels,
      setCommsModel: state.setCommsModel,
      setExecutorModel: state.setExecutorModel,
    })),
  );
