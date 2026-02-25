import CharacterCount from "@tiptap/extension-character-count";
import Highlight from "@tiptap/extension-highlight";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import Typography from "@tiptap/extension-typography";
import Underline from "@tiptap/extension-underline";
import { type EditorOptions, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import type { Tag } from "emblor";
import { marked } from "marked";
import { useCallback, useState } from "react";
import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailSuggestion } from "@/features/mail/components/EmailChip";
import { toast } from "@/lib/toast";

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

const defaultFormState: EmailCompositionFormState = {
  toEmails: [],
  subject: "",
  body: "",
  prompt: "",
  writingStyle: "formal",
  contentLength: "none",
  clarityOption: "none",
};

const defaultUIState: EmailCompositionUIState = {
  loading: false,
  error: null,
  isAiModalOpen: false,
  activeTagIndex: null,
};

export function useEmailComposition(): UseEmailCompositionReturn {
  // Form state
  const [toEmails, setToEmails] = useState<Tag[]>(defaultFormState.toEmails);
  const [subject, setSubject] = useState(defaultFormState.subject);
  const [body, setBody] = useState(defaultFormState.body);
  const [prompt, setPrompt] = useState(defaultFormState.prompt);
  const [writingStyle, setWritingStyle] = useState(
    defaultFormState.writingStyle,
  );
  const [contentLength, setContentLength] = useState(
    defaultFormState.contentLength,
  );
  const [clarityOption, setClarityOption] = useState(
    defaultFormState.clarityOption,
  );

  // UI state
  const [loading, setLoading] = useState(defaultUIState.loading);
  const [error, setError] = useState<string | null>(defaultUIState.error);
  const [isAiModalOpen, setIsAiModalOpen] = useState(
    defaultUIState.isAiModalOpen,
  );
  const [activeTagIndex, setActiveTagIndex] = useState<number | null>(
    defaultUIState.activeTagIndex,
  );

  // Editor configuration
  const editorConfig: Partial<EditorOptions> = {
    extensions: [
      StarterKit,
      Highlight,
      Typography,
      Underline,
      Link.configure({
        openOnClick: true,
        autolink: true,
        linkOnPaste: true,
      }),
      CharacterCount.configure({ limit: 10_000 }),
      Placeholder.configure({
        placeholder: () => "Body",
      }),
    ],
    editorProps: {
      attributes: {
        class: "h-[50vh] overflow-y-auto",
      },
    },
    content: body,
    onUpdate: ({ editor }) => {
      setBody(editor.getHTML());
    },
  };

  const editor = useEditor(editorConfig);

  // Options
  const options = {
    writingStyles: [
      { id: "formal", label: "Formal" },
      { id: "friendly", label: "Friendly" },
      { id: "casual", label: "Casual" },
      { id: "persuasive", label: "Persuasive" },
      { id: "humorous", label: "Humorous" },
    ],
    contentLengthOptions: [
      { id: "none", label: "None" },
      { id: "shorten", label: "Shorten" },
      { id: "lengthen", label: "Lengthen" },
      { id: "summarize", label: "Summarize" },
    ],
    clarityOptions: [
      { id: "none", label: "None" },
      { id: "simplify", label: "Simplify" },
      { id: "rephrase", label: "Rephrase" },
    ],
  };

  // Actions
  const handleAiSelect = useCallback(
    (selectedSuggestions: EmailSuggestion[]) => {
      const newTags: Tag[] = selectedSuggestions.map((s) => ({
        id: s.email,
        label: s.email,
        text: s.email,
      }));
      setToEmails((prev) => [...prev, ...newTags]);
    },
    [],
  );

  const handleAskGaia = useCallback(
    async (overrideStyle?: string) => {
      setLoading(true);
      setError(null);
      try {
        const response = await mailApi.composeWithAI({
          subject,
          body,
          prompt,
          writingStyle: overrideStyle || writingStyle,
          contentLength,
          clarityOption,
        });

        if (response.content) {
          const parsedContent = JSON.parse(response.content);
          if (parsedContent.subject && parsedContent.body) {
            const formattedBody = marked(
              parsedContent.body.replace(/\n/g, "<br />"),
            );
            if (editor) editor.commands.setContent(formattedBody);
            setSubject(parsedContent.subject);
          } else {
            console.log(`Invalid response format: ${JSON.stringify(response)}`);
            setError("Invalid response format from server");
            toast.error("Invalid response format from server");
          }
        } else {
          console.log(`Invalid response format: ${JSON.stringify(response)}`);
          setError("Invalid response format from server");
          toast.error("Invalid response format from server");
        }
      } catch (error) {
        console.error("Error processing email:", error);
        toast.error("Error processing email. Please try again later.");
      } finally {
        setLoading(false);
      }
    },
    [subject, body, prompt, writingStyle, contentLength, clarityOption, editor],
  );

  const handleAskGaiaKeyPress = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (loading) return;
      if (e.key === "Enter") {
        e.preventDefault();
        handleAskGaia();
      }
    },
    [loading, handleAskGaia],
  );

  const resetForm = useCallback(() => {
    setToEmails(defaultFormState.toEmails);
    setSubject(defaultFormState.subject);
    setBody(defaultFormState.body);
    setPrompt(defaultFormState.prompt);
    setWritingStyle(defaultFormState.writingStyle);
    setContentLength(defaultFormState.contentLength);
    setClarityOption(defaultFormState.clarityOption);
    setLoading(defaultUIState.loading);
    setError(defaultUIState.error);
    setIsAiModalOpen(defaultUIState.isAiModalOpen);
    setActiveTagIndex(defaultUIState.activeTagIndex);
    if (editor) {
      editor.commands.setContent("");
    }
  }, [editor]);

  return {
    formState: {
      toEmails,
      subject,
      body,
      prompt,
      writingStyle,
      contentLength,
      clarityOption,
    },
    uiState: {
      loading,
      error,
      isAiModalOpen,
      activeTagIndex,
    },
    actions: {
      setToEmails,
      setSubject,
      setBody,
      setPrompt,
      setWritingStyle,
      setContentLength,
      setClarityOption,
      setIsAiModalOpen,
      setActiveTagIndex,
      setError,
      handleAiSelect,
      handleAskGaia,
      handleAskGaiaKeyPress,
      resetForm,
    },
    editor,
    editorConfig,
    options,
  };
}
