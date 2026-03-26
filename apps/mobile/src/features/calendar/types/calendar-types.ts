export interface CalendarEvent {
  id: string;
  title: string;
  description?: string;
  start_time: string;
  end_time: string;
  all_day: boolean;
  location?: string;
  calendar_name?: string;
}

export interface CalendarSection {
  title: string;
  data: CalendarEvent[];
}
