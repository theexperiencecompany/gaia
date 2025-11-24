import { type Notification, NotificationSource } from "@/types/notifications";

export const notifications: Notification[] = [
  {
    id: "1",
    source: NotificationSource.AI_EMAIL_DRAFT,
    title: "Email Draft Created",
    description: "I've drafted a response to Sarah about the project timeline.",
    timestamp: "10:46 AM",
    timeGroup: "Today",
    actions: {
      primary: { label: "Send Email" },
      secondary: { label: "View Draft", variant: "outline" },
    },
  },
  {
    id: "2",
    source: NotificationSource.AI_CALENDAR_EVENT,
    title: "Calendar Event Added",
    description:
      "Team meeting with Design department on June 5, 2025\n2:00 PM - 3:30 PM",
    timestamp: "9:30 AM",
    timeGroup: "Today",
    actions: {
      primary: { label: "View Event", variant: "secondary" },
      secondary: { label: "Undo", variant: "ghost" },
    },
  },
  {
    id: "3",
    source: NotificationSource.AI_TODO_SUGGESTION,
    title: "Todo Suggestion",
    description: "Prepare presentation slides for client meeting on Friday",
    timestamp: "9:15 AM",
    timeGroup: "Today",
    actions: {
      primary: { label: "Add to Todo" },
    },
  },
  {
    id: "4",
    source: NotificationSource.AI_REMINDER,
    title: "Reminder",
    description: "Follow up with the marketing team about Q2 campaign metrics",
    timestamp: "Yesterday, 4:30 PM",
    timeGroup: "Yesterday",
    actions: {
      primary: { label: "Mark as Done", variant: "secondary" },
      secondary: { label: "Snooze", variant: "ghost" },
    },
  },
  {
    id: "5",
    source: NotificationSource.EMAIL_TRIGGER,
    title: "Email Draft Created",
    description: "I've drafted a monthly newsletter for June 2025.",
    timestamp: "Yesterday, 2:15 PM",
    timeGroup: "Yesterday",
    actions: {
      primary: { label: "Send Email" },
      secondary: { label: "View Draft", variant: "outline" },
    },
  },
  {
    id: "6",
    source: NotificationSource.AI_TODO_ADDED,
    title: "Todo Added",
    description: "Review and approve design mockups for the new landing page",
    timestamp: "Jun 1, 2025",
    timeGroup: "Earlier",
    actions: {
      primary: { label: "View Task", variant: "secondary" },
      secondary: { label: "Undo", variant: "ghost" },
    },
  },
];
