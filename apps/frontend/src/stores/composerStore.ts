import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

import type { UploadedFilePreview } from "@/features/chat/components/files/FilePreview";
import type { FileData, SearchMode } from "@/types/shared";

interface ComposerState {
  // Text input state
  pendingPrompt: string | null;
  inputText: string;

  // Mode and tool selection
  selectedMode: Set<SearchMode>;
  selectedTool: string | null;
  selectedToolCategory: string | null;

  // File management
  fileUploadModal: boolean;
  uploadedFiles: UploadedFilePreview[];
  uploadedFileData: FileData[];
  pendingDroppedFiles: File[];

  // UI state
  isSlashCommandDropdownOpen: boolean;
}

interface ComposerActions {
  // Text input actions
  appendToInput: (text: string) => void;
  setPendingPrompt: (prompt: string | null) => void;
  clearPendingPrompt: () => void;
  setInputText: (text: string) => void;
  appendToInputText: (text: string) => void;
  clearInputText: () => void;

  // Mode and tool actions
  setSelectedMode: (mode: Set<SearchMode>) => void;
  setSelectedTool: (tool: string | null, category?: string | null) => void;
  setSelectedToolCategory: (category: string | null) => void;
  clearToolSelection: () => void;

  // File management actions
  setFileUploadModal: (open: boolean) => void;
  setUploadedFiles: (files: UploadedFilePreview[]) => void;
  addUploadedFile: (file: UploadedFilePreview) => void;
  removeUploadedFile: (fileId: string) => void;
  setUploadedFileData: (data: FileData[]) => void;
  addUploadedFileData: (data: FileData) => void;
  removeUploadedFileData: (fileId: string) => void;
  setPendingDroppedFiles: (files: File[]) => void;
  clearAllFiles: () => void;

  // UI actions
  setIsSlashCommandDropdownOpen: (open: boolean) => void;

  // Reset actions
  resetComposer: () => void;
}

type ComposerStore = ComposerState & ComposerActions;

const initialState: ComposerState = {
  // Text input state
  pendingPrompt: null,
  inputText: "",

  // Mode and tool selection
  selectedMode: new Set([null]),
  selectedTool: null,
  selectedToolCategory: null,

  // File management
  fileUploadModal: false,
  uploadedFiles: [],
  uploadedFileData: [],
  pendingDroppedFiles: [],

  // UI state
  isSlashCommandDropdownOpen: false,
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
            window.location.pathname.startsWith("/c") === false
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
        setFileUploadModal: (fileUploadModal) =>
          set({ fileUploadModal }, false, "setFileUploadModal"),

        setUploadedFiles: (uploadedFiles) =>
          set({ uploadedFiles }, false, "setUploadedFiles"),

        addUploadedFile: (file) =>
          set(
            (state) => ({ uploadedFiles: [...state.uploadedFiles, file] }),
            false,
            "addUploadedFile",
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

        setPendingDroppedFiles: (pendingDroppedFiles) =>
          set({ pendingDroppedFiles }, false, "setPendingDroppedFiles"),

        clearAllFiles: () =>
          set(
            {
              uploadedFiles: [],
              uploadedFileData: [],
              pendingDroppedFiles: [],
              fileUploadModal: false,
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
      pendingDroppedFiles: state.pendingDroppedFiles,
      fileUploadModal: state.fileUploadModal,
      setFileUploadModal: state.setFileUploadModal,
      setUploadedFiles: state.setUploadedFiles,
      addUploadedFile: state.addUploadedFile,
      removeUploadedFile: state.removeUploadedFile,
      setUploadedFileData: state.setUploadedFileData,
      addUploadedFileData: state.addUploadedFileData,
      removeUploadedFileData: state.removeUploadedFileData,
      setPendingDroppedFiles: state.setPendingDroppedFiles,
      clearAllFiles: state.clearAllFiles,
    })),
  );

export const useComposerUI = () =>
  useComposerStore(
    useShallow((state) => ({
      isSlashCommandDropdownOpen: state.isSlashCommandDropdownOpen,
      setIsSlashCommandDropdownOpen: state.setIsSlashCommandDropdownOpen,
    })),
  );

export const useComposerActions = () =>
  useComposerStore(
    useShallow((state) => ({
      resetComposer: state.resetComposer,
      setInputText: state.setInputText,
      appendToInputText: state.appendToInputText,
      clearPendingPrompt: state.clearPendingPrompt,
      setPendingPrompt: state.setPendingPrompt,
    })),
  );
