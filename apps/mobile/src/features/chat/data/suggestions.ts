/**
 * Chat Suggestions Data
 * Default suggestions for new chat sessions
 */

import type { Suggestion } from "../types";

export interface SuggestionChip {
  id: string;
  icon: string;
  label: string;
  prompt: string;
  category: string;
  accentColor: string;
}

export const SUGGESTION_CHIPS: SuggestionChip[] = [
  {
    id: "1",
    icon: "Mail01Icon",
    label: "Check emails",
    prompt: "Check my unread emails and give me a summary",
    category: "productivity",
    accentColor: "#60a5fa",
  },
  {
    id: "2",
    icon: "Calendar03Icon",
    label: "Today's agenda",
    prompt: "What's on my calendar today?",
    category: "productivity",
    accentColor: "#34d399",
  },
  {
    id: "3",
    icon: "CheckListIcon",
    label: "My tasks",
    prompt: "Show me my pending tasks and to-dos",
    category: "productivity",
    accentColor: "#a78bfa",
  },
  {
    id: "4",
    icon: "Search01Icon",
    label: "Web search",
    prompt: "Search the web for ",
    category: "research",
    accentColor: "#f472b6",
  },
  {
    id: "5",
    icon: "SourceCodeCircleIcon",
    label: "Write code",
    prompt: "Help me write code for ",
    category: "coding",
    accentColor: "#22d3ee",
  },
  {
    id: "6",
    icon: "PencilEdit01Icon",
    label: "Draft email",
    prompt: "Help me draft a professional email about ",
    category: "writing",
    accentColor: "#fb923c",
  },
  {
    id: "7",
    icon: "Brain02Icon",
    label: "Brainstorm",
    prompt: "Help me brainstorm ideas for ",
    category: "creative",
    accentColor: "#e879f9",
  },
  {
    id: "8",
    icon: "Analytics01Icon",
    label: "Summarize",
    prompt: "Summarize this for me: ",
    category: "research",
    accentColor: "#facc15",
  },
];

export const DEFAULT_SUGGESTIONS: Suggestion[] = [
  {
    id: "1",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/960px-Gmail_icon_%282020%29.svg.png",
    text: "Check my unread emails",
  },
  {
    id: "2",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/960px-Gmail_icon_%282020%29.svg.png",
    text: "Compose a new email",
  },
  {
    id: "3",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/2048px-Google_Calendar_icon_%282020%29.svg.png",
    text: "What's on my calendar today?",
  },
  {
    id: "4",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/2048px-Google_Calendar_icon_%282020%29.svg.png",
    text: "Schedule a new meeting",
  },
];
