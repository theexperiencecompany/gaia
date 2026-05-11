/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { UploadedFilePreview } from "@/features/chat/components/files/FilePreview";
import type { FileData } from "@/types/shared/fileTypes";
import type { SearchMode } from "@/types/shared/searchTypes";

interface ComposerState {
  pendingPrompt: string | null;
  inputText: string;
  selectedMode: Set<SearchMode>;
  selectedTool: string | null;
  selectedToolCategory: string | null;
  fileUploadModal: boolean;
  uploadedFiles: UploadedFilePreview[];
  uploadedFileData: FileData[];
  pendingDroppedFiles: File[];
  isSlashCommandDropdownOpen: boolean;
}

interface ComposerActions {
  appendToInput: (text: string) => void;
  setPendingPrompt: (prompt: string | null) => void;
  clearPendingPrompt: () => void;
  setInputText: (text: string) => void;
  appendToInputText: (text: string) => void;
  clearInputText: () => void;
  setSelectedMode: (mode: Set<SearchMode>) => void;
  setSelectedTool: (tool: string | null, category?: string | null) => void;
  setSelectedToolCategory: (category: string | null) => void;
  clearToolSelection: () => void;
  setFileUploadModal: (open: boolean) => void;
  setUploadedFiles: (files: UploadedFilePreview[]) => void;
  addUploadedFile: (file: UploadedFilePreview) => void;
  removeUploadedFile: (fileId: string) => void;
  setUploadedFileData: (data: FileData[]) => void;
  addUploadedFileData: (data: FileData) => void;
  removeUploadedFileData: (fileId: string) => void;
  setPendingDroppedFiles: (files: File[]) => void;
  clearAllFiles: () => void;
  setIsSlashCommandDropdownOpen: (open: boolean) => void;
  resetComposer: () => void;
}

type ComposerStore = ComposerState & ComposerActions;

const noop = () => {};

const frozenState: ComposerStore = Object.freeze({
  pendingPrompt: null,
  inputText: "",
  selectedMode: new Set<SearchMode>([null as unknown as SearchMode]),
  selectedTool: null,
  selectedToolCategory: null,
  fileUploadModal: false,
  uploadedFiles: [] as UploadedFilePreview[],
  uploadedFileData: [] as FileData[],
  pendingDroppedFiles: [] as File[],
  isSlashCommandDropdownOpen: false,
  appendToInput: noop,
  setPendingPrompt: noop,
  clearPendingPrompt: noop,
  setInputText: noop,
  appendToInputText: noop,
  clearInputText: noop,
  setSelectedMode: noop,
  setSelectedTool: noop,
  setSelectedToolCategory: noop,
  clearToolSelection: noop,
  setFileUploadModal: noop,
  setUploadedFiles: noop,
  addUploadedFile: noop,
  removeUploadedFile: noop,
  setUploadedFileData: noop,
  addUploadedFileData: noop,
  removeUploadedFileData: noop,
  setPendingDroppedFiles: noop,
  clearAllFiles: noop,
  setIsSlashCommandDropdownOpen: noop,
  resetComposer: noop,
});

type Selector<U> = (state: ComposerStore) => U;

interface UseComposerStoreFn {
  <U>(selector: Selector<U>): U;
  (): ComposerStore;
  getState: () => ComposerStore;
  setState: (partial: Partial<ComposerStore>) => void;
  subscribe: (listener: (state: ComposerStore) => void) => () => void;
}

export const useComposerStore: UseComposerStoreFn = (<U,>(
  selector?: Selector<U>,
) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseComposerStoreFn;
useComposerStore.getState = () => frozenState;
useComposerStore.setState = noop;
useComposerStore.subscribe = () => noop;

export const usePendingPrompt = (): string | null => null;
export const useAppendToInput = (): ((text: string) => void) => noop;
export const useInputText = (): string => "";

export const useComposerTextActions = () => ({
  setInputText: noop as ComposerActions["setInputText"],
  appendToInputText: noop as ComposerActions["appendToInputText"],
  clearInputText: noop as ComposerActions["clearInputText"],
  clearPendingPrompt: noop as ComposerActions["clearPendingPrompt"],
  setPendingPrompt: noop as ComposerActions["setPendingPrompt"],
});

export const useComposerModeSelection = () => ({
  selectedMode: new Set<SearchMode>([null as unknown as SearchMode]),
  selectedTool: null as string | null,
  selectedToolCategory: null as string | null,
  setSelectedMode: noop as ComposerActions["setSelectedMode"],
  setSelectedTool: noop as ComposerActions["setSelectedTool"],
  setSelectedToolCategory: noop as ComposerActions["setSelectedToolCategory"],
  clearToolSelection: noop as ComposerActions["clearToolSelection"],
});

export const useComposerFiles = () => ({
  uploadedFiles: [] as UploadedFilePreview[],
  uploadedFileData: [] as FileData[],
  pendingDroppedFiles: [] as File[],
  fileUploadModal: false,
  setFileUploadModal: noop as ComposerActions["setFileUploadModal"],
  setUploadedFiles: noop as ComposerActions["setUploadedFiles"],
  addUploadedFile: noop as ComposerActions["addUploadedFile"],
  removeUploadedFile: noop as ComposerActions["removeUploadedFile"],
  setUploadedFileData: noop as ComposerActions["setUploadedFileData"],
  addUploadedFileData: noop as ComposerActions["addUploadedFileData"],
  removeUploadedFileData: noop as ComposerActions["removeUploadedFileData"],
  setPendingDroppedFiles: noop as ComposerActions["setPendingDroppedFiles"],
  clearAllFiles: noop as ComposerActions["clearAllFiles"],
});

export const useComposerUI = () => ({
  isSlashCommandDropdownOpen: false,
  setIsSlashCommandDropdownOpen:
    noop as ComposerActions["setIsSlashCommandDropdownOpen"],
});
