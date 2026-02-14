"use client";

import { Gmail, GoogleCalendarIcon } from "@/components/shared/icons";
import CardStack from "./CardStack";

interface Notification {
  id: string;
  title: string;
  message: string;
  time: string;
}

interface Email {
  id: string;
  sender: string;
  subject: string;
  preview: string;
  time: string;
}

interface CalendarEvent {
  id: string;
  title: string;
  description: string;
  time: string;
}

const mockNotifications: Notification[] = [
  {
    id: "1",
    title: "New Message",
    message: "Hey! How are you doing today? Want to grab coffee later?",
    time: "2m ago",
  },
  {
    id: "2",
    title: "System Update",
    message: "Your account settings have been updated successfully.",
    time: "5m ago",
  },
  {
    id: "3",
    title: "Security Alert",
    message: "New login detected from Chrome on MacBook Pro.",
    time: "10m ago",
  },
];

const mockEmails: Email[] = [
  {
    id: "1",
    sender: "Sarah Johnson",
    subject: "Meeting Rescheduled",
    preview: "The team meeting has been moved to 3 PM tomorrow...",
    time: "1h ago",
  },
  {
    id: "2",
    sender: "GitHub",
    subject: "Pull Request Review",
    preview: "Your pull request #123 is ready for review...",
    time: "2h ago",
  },
  {
    id: "3",
    sender: "Newsletter",
    subject: "Weekly Tech Updates",
    preview: "This week's highlights in technology and development...",
    time: "1d ago",
  },
];

const mockCalendarEvents: CalendarEvent[] = [
  {
    id: "1",
    title: "Team Standup",
    description: "Daily standup meeting with the development team",
    time: "9:00 AM",
  },
  {
    id: "2",
    title: "Client Call",
    description: "Project review call with ABC Corp",
    time: "2:00 PM",
  },
  {
    id: "3",
    title: "Workshop",
    description: "React Advanced Patterns workshop",
    time: "4:00 PM",
  },
];

interface CardStackContainerProps {
  className?: string;
}

export default function CardStackContainer({
  className = "flex flex-row gap-6 w-full max-w-3xl mx-auto",
}: CardStackContainerProps) {
  return (
    <div className={className}>
      {/* Notifications Stack */}
      <CardStack
        title="Notifications"
        data={mockNotifications}
        indicator={<div className="min-h-2 min-w-2 rounded-full bg-red-500" />}
        renderCard={(notification) => (
          <div className="w-full min-w-0 flex-1">
            <div className="mb-1 flex w-full items-center justify-between">
              <h3 className="text-xs font-semibold text-foreground">
                {notification.title}
              </h3>
              <span className="ml-2 flex-shrink-0 text-xs text-foreground-400">
                {notification.time}
              </span>
            </div>
            <p className="line-clamp-1 text-xs text-foreground-500">
              {notification.message}
            </p>
          </div>
        )}
        viewAllHref="/notifications"
        className="w-full"
        collapsedMessage={(count) =>
          `${count} unread notification${count !== 1 ? "s" : ""}`
        }
      />

      {/* Emails Stack */}
      <CardStack
        title="Unread Emails"
        data={mockEmails}
        indicator={<Gmail className="h-4 w-4 text-red-500" />}
        renderCard={(email) => (
          <div className="w-full min-w-0 flex-1">
            <div className="mb-1 flex w-full items-center justify-between">
              <h3 className="text-xs font-semibold text-foreground">
                {email.subject}
              </h3>
              <span className="ml-2 flex-shrink-0 text-xs text-foreground-400">
                {email.time}
              </span>
            </div>
            <p className="mb-1 text-xs text-foreground-600">
              from {email.sender}
            </p>
            <p className="line-clamp-1 text-xs text-foreground-500">
              {email.preview}
            </p>
          </div>
        )}
        viewAllHref="/emails"
        className="w-full"
        collapsedMessage={(count) =>
          `${count} unread email${count === 1 ? "" : "s"}`
        }
      />

      {/* Calendar Events Stack */}
      <CardStack
        title="Today's Events"
        data={mockCalendarEvents}
        indicator={<GoogleCalendarIcon className="h-4 w-4 text-red-500" />}
        renderCard={(event) => (
          <div className="w-full min-w-0 flex-1">
            <div className="mb-1 flex w-full items-center justify-between">
              <h3 className="text-xs font-semibold text-foreground">
                {event.title}
              </h3>
              <span className="ml-2 flex-shrink-0 text-xs text-foreground-400">
                {event.time}
              </span>
            </div>
            <p className="line-clamp-1 text-xs text-foreground-500">
              {event.description}
            </p>
          </div>
        )}
        viewAllHref="/calendar"
        className="w-full"
        collapsedMessage={(count) =>
          `${count} event${count !== 1 ? "s" : ""} today`
        }
      />
    </div>
  );
}
