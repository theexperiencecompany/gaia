"use client";

import { ArrowLeft01Icon,CalendarIcon, CheckmarkSquare03Icon, Mail01Icon, NotificationIcon } from '@/icons';
import { NotificationSource } from "@/types/notifications";

export const getNotificationIcon = (type: NotificationSource) => {
  switch (type) {
    case "ai_email_draft":
      return <Mail01Icon className="h-4 w-4" />;
    case "ai_calendar_event":
      return <CalendarIcon className="h-4 w-4" />;
    case "ai_todo_suggestion":
    case "ai_todo_added":
      return <CheckmarkSquare03Icon className="h-4 w-4" />;
    case "ai_reminder":
      return <NotificationIcon className="h-4 w-4" />;
    default:
      return <NotificationIcon className="h-4 w-4" />;
  }
};

export const getActionIcon = (label: string) => {
  switch (label) {
    case "Undo":
      return <ArrowLeft01Icon className="mr-2 h-4 w-4 text-white" />;
    case "Snooze":
      return <NotificationIcon className="mr-2 h-4 w-4 text-white" />;
    case "View Draft":
      return <Mail01Icon className="mr-2 h-4 w-4 text-white" />;
    case "View Event":
      return <CalendarIcon className="mr-2 h-4 w-4 text-white" />;
    case "View Task":
      return <CheckmarkSquare03Icon className="mr-2 h-4 w-4 text-white" />;
    case "Mark as Done":
      return <CheckmarkSquare03Icon className="mr-2 h-4 w-4 text-white" />;
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
