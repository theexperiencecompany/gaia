"use client";

import { Tab, Tabs } from "@heroui/tabs";
import { NotificationIcon } from "@icons";
import type { UpdateFilter } from "@shared/api/generated";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import {
  UPDATE_FILTER_LABELS,
  UPDATE_FILTERS,
} from "@/features/updates/constants";

interface UpdatesHeaderProps {
  filter: UpdateFilter;
  onFilterChange: (filter: UpdateFilter) => void;
}

export default function UpdatesHeader({
  filter,
  onFilterChange,
}: UpdatesHeaderProps) {
  return (
    <div className="flex w-full items-center justify-between gap-4">
      <HeaderTitle
        icon={<NotificationIcon width={20} height={20} />}
        text="Updates"
      />

      <Tabs
        aria-label="Filter updates"
        selectedKey={filter}
        onSelectionChange={(key) => onFilterChange(key as UpdateFilter)}
        variant="underlined"
      >
        {UPDATE_FILTERS.map((key) => (
          <Tab key={key} title={UPDATE_FILTER_LABELS[key]} />
        ))}
      </Tabs>
    </div>
  );
}
