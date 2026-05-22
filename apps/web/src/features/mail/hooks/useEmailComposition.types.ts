import type { EditorOptions, useEditor } from "@tiptap/react";
import type { Tag } from "emblor";
import type { EmailSuggestion } from "@/features/mail/components/EmailChip";

export interface EmailCompositionFormState {
  toEmails: Tag[];
  subject: string;
  body: string;
  prompt: string;
  writingStyle: string;
  contentLength: string;
  clarityOption: string;
}

export interface EmailCompositionUIState {
  loading: boolean;
  error: string | null;
  isAiModalOpen: boolean;
  activeTagIndex: number | null;
}

export interface EmailCompositionActions {
  setToEmails: (emails: Tag[] | ((prev: Tag[]) => Tag[])) => void;
  setSubject: (subject: string) => void;
  setBody: (body: string) => void;
  setPrompt: (prompt: string) => void;
  setWritingStyle: (style: string) => void;
  setContentLength: (length: string) => void;
  setClarityOption: (clarity: string) => void;
  setIsAiModalOpen: (open: boolean) => void;
  setActiveTagIndex: React.Dispatch<React.SetStateAction<number | null>>;
  setError: (error: string | null) => void;
  handleAiSelect: (suggestions: EmailSuggestion[]) => void;
  handleAskGaia: (overrideStyle?: string) => Promise<void>;
  handleAskGaiaKeyPress: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  resetForm: () => void;
}

export interface UseEmailCompositionReturn {
  formState: EmailCompositionFormState;
  uiState: EmailCompositionUIState;
  actions: EmailCompositionActions;
  editor: ReturnType<typeof useEditor>;
  editorConfig: Partial<EditorOptions>;
  options: {
    writingStyles: Array<{ id: string; label: string }>;
    contentLengthOptions: Array<{ id: string; label: string }>;
    clarityOptions: Array<{ id: string; label: string }>;
  };
}
