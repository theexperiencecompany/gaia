import type { CalendarFetchData } from "../../../chat/types";
import type { Card, CardListItem } from "../types";
import { eventDayLabel, eventTimeLabel } from "./calendar-event-time";
import { cappedList, joinMeta } from "./card-parts";
import { countLabel } from "./count-label";

const EVENTS_TITLE = "Events";
/** Past this many the list stops and says how many more there are. */
const MAX_LISTED_EVENTS = 10;

/** The day the events share, or `undefined` when they span several. */
function sharedDay(events: CalendarFetchData[]): string | undefined {
  const days = new Set(events.map((event) => eventDayLabel(event.start_time)));
  const [day] = days;
  return days.size === 1 ? day : undefined;
}

function eventItem(event: CalendarFetchData, showDay: boolean): CardListItem {
  return {
    title: event.summary,
    meta: joinMeta([
      showDay ? eventDayLabel(event.start_time) : undefined,
      eventTimeLabel(event.start_time, event.end_time),
      event.calendar_name,
    ]),
  };
}

/**
 * The events a fetch, search or day summary found, each with its time and
 * calendar. Events on one day name it in the title ("Thu, Nov 12 · 3 events");
 * otherwise each row carries its own day.
 */
export function buildCalendarFetchCards(events: CalendarFetchData[]): Card[] {
  if (events.length === 0) return [];
  const day = sharedDay(events);
  return [
    {
      title: day
        ? joinMeta([day, countLabel(events.length, "event")])
        : joinMeta([EVENTS_TITLE, String(events.length)]),
      accent: "brand",
      blocks: [
        cappedList(events, MAX_LISTED_EVENTS, (event) =>
          eventItem(event, day === undefined),
        ),
      ],
      actions: [],
    },
  ];
}
