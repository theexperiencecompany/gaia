"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { Moon02Icon, Sun03Icon, SunriseIcon, SunsetIcon } from "@icons";
import type { FC } from "react";
import type { TimeOfDay } from "@/features/landing/utils/timeOfDay";

type IconComponent = FC<{ width: number; height: number }>;

const TOD_ICON: Record<TimeOfDay, IconComponent> = {
  morning: SunriseIcon,
  day: Sun03Icon,
  evening: SunsetIcon,
  night: Moon02Icon,
};

interface TimeOfDayToggleProps {
  timeOfDay: TimeOfDay;
  onPress: () => void;
}

export function TimeOfDayToggle({ timeOfDay, onPress }: TimeOfDayToggleProps) {
  const Icon = TOD_ICON[timeOfDay];
  return (
    <Tooltip
      content="P.S. did you know you can click on the hero title 3 times to change the time?"
      placement="left"
      delay={300}
      classNames={{ content: "max-w-[180px] text-center" }}
    >
      <Button
        isIconOnly
        variant="flat"
        size="sm"
        radius="full"
        onPress={onPress}
        aria-label={`Switch time of day, currently ${timeOfDay}`}
        className="opacity-40 hover:opacity-85 transition-opacity text-white"
      >
        <Icon width={17} height={17} />
      </Button>
    </Tooltip>
  );
}
