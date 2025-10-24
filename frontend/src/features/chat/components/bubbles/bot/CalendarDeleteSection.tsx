import React from "react";

import { CalendarDeleteOptions } from "@/types/features/calendarTypes";

import { CalendarActionListCard } from "./CalendarActionListCard";

interface CalendarDeleteSectionProps {
  calendar_delete_options: CalendarDeleteOptions[];
}

export function CalendarDeleteSection({
  calendar_delete_options,
}: CalendarDeleteSectionProps) {
  if (!calendar_delete_options?.length) return null;

  return (
    <CalendarActionListCard
      actionType="delete"
      events={calendar_delete_options}
    />
  );
}
