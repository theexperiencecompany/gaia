"use client";

import { useState } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import TaskSection from "../tasks/TaskSection";
import { AppRow } from "./AppRow";
import type { App } from "./appModel";

/** Rows a shelf shows before "Show all"; the rest open in place, below, so nothing above moves. */
const SHELF_ROWS = 12;

export function AppShelf({
  id,
  title,
  description,
  apps,
}: {
  id: string;
  title: string;
  description: string;
  apps: App[];
}) {
  const [isOpen, setIsOpen] = useState(false);
  if (apps.length === 0) return null;
  const shown = isOpen ? apps : apps.slice(0, SHELF_ROWS);
  return (
    <TaskSection
      id={id}
      title={title}
      count={apps.length}
      description={description}
    >
      <ul>
        {shown.map((app) => (
          <AppRow key={app.integrationId} app={app} />
        ))}
      </ul>
      {apps.length > SHELF_ROWS && (
        <GaiaButton
          size="sm"
          variant="quiet"
          tone="faint"
          hoverTone="bright"
          inset="tight"
          aria-expanded={isOpen}
          onPress={() => setIsOpen((open) => !open)}
          className="mt-1 h-9 min-w-0 text-[13px]"
        >
          {isOpen ? "Show fewer" : `Show all ${apps.length}`}
        </GaiaButton>
      )}
    </TaskSection>
  );
}
