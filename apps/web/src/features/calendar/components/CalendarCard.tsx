import Twemoji from "react-twemoji";

import {
  formatEventDate,
  getEventColor,
  getEventIcon,
  isTooDark,
} from "@/features/calendar/utils/calendarUtils";
import { Timer02Icon } from "@/icons";
import type {
  CalendarCardProps,
  GoogleCalendarEvent,
} from "@/types/features/calendarTypes";

const CalendarCard: React.FC<CalendarCardProps> = ({
  event,
  onClick,
  calendars,
}) => {
  const calendar = calendars?.find((cal) => cal.id === event?.organizer?.email);

  const color =
    calendar?.backgroundColor ||
    getEventColor(event as GoogleCalendarEvent) ||
    "#00bbff";

  const backgroundColor = isTooDark(color) ? "#ffffff" : color;
  const icon = getEventIcon(event as GoogleCalendarEvent);

  // Use formatEventDate if available; otherwise, fall back to simple extraction.
  let dateDisplay: string = "";
  if ("start" in event && typeof event.start !== "string") {
    // For GoogleCalendarEvent, try formatting the date range.
    dateDisplay = formatEventDate(event as GoogleCalendarEvent) || "";
  }

  if (!dateDisplay) {
    // For TimedEvent where start is a string.
    if ("start" in event && typeof event.start === "string") {
      dateDisplay = event.start;
    } else if ("time" in event) {
      // For SingleTimeEvent.
      dateDisplay = event.time;
    }
  }

  return (
    <div
      className="hover:bg-opacity-100 relative z-1 w-full cursor-pointer overflow-hidden rounded-lg p-4 text-white shadow-md transition-colors duration-200"
      onClick={onClick}
    >
      <div
        className="absolute inset-0 z-2 border-l-5"
        style={{ borderColor: backgroundColor }}
      />
      <div className="relative z-1 flex items-center gap-2">
        <Twemoji options={{ className: "twemoji max-w-[20px]" }}>
          <span className="text-xl">{icon}</span>
        </Twemoji>
        <div className="text-lg font-bold">{event.summary}</div>
      </div>
      {dateDisplay && (
        <div
          className="relative z-1 mt-2 flex items-center gap-1 text-sm"
          style={{ color: backgroundColor }}
        >
          <Timer02Icon height={17} width={17} />
          {dateDisplay}
        </div>
      )}
      <div
        className="absolute inset-0 z-0 w-full rounded-lg opacity-20"
        style={{ backgroundColor }}
      />
    </div>
  );
};

export default CalendarCard;
