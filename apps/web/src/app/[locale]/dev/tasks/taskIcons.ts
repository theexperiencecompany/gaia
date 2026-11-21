import {
  BubbleChatIcon,
  Calendar03Icon,
  CalendarAdd01Icon,
  CheckmarkCircle02Icon,
  FlashIcon,
  Link01Icon,
  RepeatIcon,
  ViewIcon,
  ViewOffIcon,
} from "@icons";
import type { ComponentType } from "react";

import type { Need, WhenKind } from "./taskModel";

type IconComponent = ComponentType<{ className?: string; size?: number }>;

export const WHEN_ICONS: Record<WhenKind, IconComponent> = {
  anytime: CalendarAdd01Icon,
  at: Calendar03Icon,
  schedule: RepeatIcon,
  event: FlashIcon,
  watch: ViewIcon,
};

/** What a task needs from you, as an icon and two words; the detail is inside the task. */
export const NEEDS: Record<Need, { label: string; Icon: IconComponent }> = {
  approval: { label: "Needs approval", Icon: CheckmarkCircle02Icon },
  question: { label: "Has a question", Icon: BubbleChatIcon },
  reconnect: { label: "Needs reconnecting", Icon: Link01Icon },
  blind: { label: "Can't see it", Icon: ViewOffIcon },
};
