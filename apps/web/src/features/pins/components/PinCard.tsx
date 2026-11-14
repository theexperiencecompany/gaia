import { itemText } from "@shared/conversation";
import Link from "next/link";
import type React from "react";
import { track } from "@/lib/analytics";
import type { PinCardProps } from "@/types/features/pinTypes";
import { parseDate } from "@/utils/date/dateUtils";

export const PinCard: React.FC<PinCardProps> = ({ item, conversation_id }) => {
  const text = itemText(item);
  return (
    <Link
      key={item.id}
      className="relative flex h-full max-h-[195px] min-h-[150px] flex-col gap-2 overflow-hidden rounded-xl bg-zinc-800 p-3 transition-colors hover:bg-zinc-700"
      href={{
        pathname: `/c/${conversation_id}`,
        query: { messageId: item.id },
      }}
      onClick={() => {
        track("pin:viewed", {
          message_id: item.id,
          conversation_id,
        });
      }}
    >
      <div className="max-h-[135px] overflow-hidden text-sm">
        {text.slice(0, 350)}
        {text.length > 350 ? "..." : ""}
      </div>

      <div
        className="mt-auto text-xs text-foreground-500"
        suppressHydrationWarning
      >
        {parseDate(item.at)}
      </div>
    </Link>
  );
};
