"use client";

import { Bell, CalendarIcon, CheckSquare, Mail, Undo } from "@/icons";
import { NotificationSource } from "@/types/notifications";

export const getNotificationIcon = (type: NotificationSource) => {
  switch (type) {
    case "ai_email_draft":
      return <Mail className="h-4 w-4" />;
    case "ai_calendar_event":
      return <CalendarIcon className="h-4 w-4" />;
    case "ai_todo_suggestion":
    case "ai_todo_added":
      return <CheckSquare className="h-4 w-4" />;
    case "ai_reminder":
      return <Bell className="h-4 w-4" />;
    default:
      return <Bell className="h-4 w-4" />;
  }
};

export const getActionIcon = (label: string) => {
  switch (label) {
    case "Undo":
      return <Undo className="mr-2 h-4 w-4 text-white" />;
    case "Snooze":
      return <Bell className="mr-2 h-4 w-4 text-white" />;
    case "View Draft":
      return <Mail className="mr-2 h-4 w-4 text-white" />;
    case "View Event":
      return <CalendarIcon className="mr-2 h-4 w-4 text-white" />;
    case "View Task":
      return <CheckSquare className="mr-2 h-4 w-4 text-white" />;
    case "Mark as Done":
      return <CheckSquare className="mr-2 h-4 w-4 text-white" />;
    default:
      return null;
  }
};

export const getActionColor = (label: string) => {
  switch (label) {
    case "Send Email":
      return "bg-blue-600";
    case "Add to Todo":
      return "bg-green-600";
    case "Mark as Done":
      return "bg-green-600";
    case "Undo":
      return "bg-yellow-600";
    case "View Draft":
    case "View Event":
    case "View Task":
      return "bg-purple-600";
    case "Snooze":
      return "bg-orange-600";
    default:
      return "bg-blue-600";
  }
};
