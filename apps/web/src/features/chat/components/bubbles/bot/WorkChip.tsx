"use client";

import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { AlertCircleIcon, CheckmarkCircle02Icon } from "@icons";
import type { ReactNode } from "react";

import {
  type WorkChipState,
  workChipState,
} from "@/features/chat/utils/workChip";
import { useChatStore } from "@/stores/chatStore";

const CHIP_LOOK: Record<
  WorkChipState,
  { label: string; color: "default" | "success" | "danger"; icon: ReactNode }
> = {
  working: {
    label: "Working on it",
    color: "default",
    icon: <Spinner size="sm" color="current" className="scale-75" />,
  },
  done: {
    label: "Done",
    color: "success",
    icon: <CheckmarkCircle02Icon className="size-3.5" />,
  },
  nothing_new: {
    label: "Nothing to report",
    color: "success",
    icon: <CheckmarkCircle02Icon className="size-3.5" />,
  },
  failed: {
    label: "Could not finish",
    color: "danger",
    icon: <AlertCircleIcon className="size-3.5" />,
  },
};

/**
 * The status chip of a turn that handed work off while GAIA said nothing: it
 * reads "Working on it" until the run behind it settles, then says how it
 * ended. It is the saved turn itself (kind `accepted`), so a reload shows it too.
 */
export default function WorkChip({ messageId }: { messageId: string }) {
  const state = useChatStore((store) => {
    for (const messages of Object.values(store.messagesByConversation)) {
      if (messages.some((m) => m.id === messageId)) {
        return workChipState(messages, messageId);
      }
    }
    return "working";
  });
  const { label, color, icon } = CHIP_LOOK[state];

  return (
    <Chip size="sm" variant="flat" color={color} startContent={icon}>
      {label}
    </Chip>
  );
}
