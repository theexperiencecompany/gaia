import React from "react";

import { CalendarEditOptions } from "@/types/features/calendarTypes";

import { CalendarActionListCard } from "./CalendarActionListCard";

interface CalendarEditSectionProps {
  calendar_edit_options: CalendarEditOptions[];
}

export function CalendarEditSection({
  calendar_edit_options,
}: CalendarEditSectionProps) {
  if (!calendar_edit_options?.length) return null;

  return (
    <CalendarActionListCard actionType="edit" events={calendar_edit_options} />
  );
}
