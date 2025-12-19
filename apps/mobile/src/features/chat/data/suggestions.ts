/**
 * Chat Suggestions Data
 * Default suggestions for new chat sessions
 */

import type { Suggestion } from "../types";

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
