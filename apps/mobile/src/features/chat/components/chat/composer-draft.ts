import type { ReplyToMessageData } from "../../types";

interface SelectedTool {
  name: string;
  category: string;
}

export interface SelectedWorkflow {
  id: string;
  title: string;
}

/**
 * The unsent turn: what the user has typed plus the attachments-of-intent
 * (tool, workflow, reply) that travel with it. They are one unit because
 * almost every event that touches one clears the others — sending, switching
 * conversation, `/clear` — and a tool and a workflow are mutually exclusive.
 */
export interface ComposerDraftState {
  inputValue: string;
  /** Kept after a send so the thinking-message rotation can stay on-topic. */
  lastUserMessage: string;
  selectedTool: SelectedTool | null;
  selectedWorkflow: SelectedWorkflow | null;
  replyingTo: ReplyToMessageData | null;
}

export type ComposerDraftAction =
  | { type: "inputChanged"; value: string }
  | { type: "conversationSwitched" }
  | { type: "messageSent"; text: string }
  | { type: "toolSelected"; tool: SelectedTool }
  | { type: "toolRemoved" }
  | { type: "workflowSelected"; workflow: SelectedWorkflow }
  | { type: "workflowRemoved" }
  | { type: "replySelected"; reply: ReplyToMessageData }
  | { type: "replyRemoved" }
  | { type: "newChatCommand" }
  | { type: "clearCommand" };

export const initialComposerDraft: ComposerDraftState = {
  inputValue: "",
  lastUserMessage: "",
  selectedTool: null,
  selectedWorkflow: null,
  replyingTo: null,
};

const EMPTY_ATTACHMENTS = {
  selectedTool: null,
  selectedWorkflow: null,
  replyingTo: null,
} as const;

export function composerDraftReducer(
  state: ComposerDraftState,
  action: ComposerDraftAction,
): ComposerDraftState {
  switch (action.type) {
    case "inputChanged":
      return { ...state, inputValue: action.value };
    case "conversationSwitched":
      return { ...state, inputValue: "", ...EMPTY_ATTACHMENTS };
    case "messageSent":
      return {
        ...state,
        inputValue: "",
        lastUserMessage: action.text,
        ...EMPTY_ATTACHMENTS,
      };
    case "toolSelected":
      return { ...state, selectedTool: action.tool, selectedWorkflow: null };
    case "toolRemoved":
      return { ...state, selectedTool: null };
    case "workflowSelected":
      return {
        ...state,
        selectedWorkflow: action.workflow,
        selectedTool: null,
      };
    case "workflowRemoved":
      return { ...state, selectedWorkflow: null };
    case "replySelected":
      return { ...state, replyingTo: action.reply };
    case "replyRemoved":
      return { ...state, replyingTo: null };
    // `/new` only resets the typed text here: it also sets the active chat to
    // null, and the conversation-switch effect clears the attachments.
    case "newChatCommand":
      return { ...state, inputValue: "", lastUserMessage: "" };
    case "clearCommand":
      return {
        ...state,
        inputValue: "",
        lastUserMessage: "",
        ...EMPTY_ATTACHMENTS,
      };
  }
}
