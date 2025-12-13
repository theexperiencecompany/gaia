import Link from "next/link";
import type React from "react";

import { parseDate } from "@/utils/date/dateUtils";

interface PinCardProps {
  message: {
    message_id: string;
    response: string;
    date: string | Date;
    type: string;
  };
  conversation_id: string;
}

export const PinCard: React.FC<PinCardProps> = ({
  message,
  conversation_id,
}) => {
  return (
    <Link
      key={message.message_id}
      className="relative flex h-full max-h-[195px] min-h-[150px] flex-col gap-2 overflow-hidden rounded-xl bg-zinc-800 p-3 transition-colors hover:bg-zinc-700"
      href={{
        pathname: `/c/${conversation_id}`,
        query: { messageId: message.message_id },
      }}
    >
      {/* <Chip
        className="min-h-7"
        color={message.type === "bot" ? "primary" : "default"}
      >
        {message.type === "bot" ? "From GAIA" : "From You"}
      </Chip> */}

      {/* <div className="absolute right-1 top-1">
        <PinIcon color="#00bbff" fill="#00bbff" height={25} width={25} />
      </div> */}

      <div className="max-h-[135px] overflow-hidden text-sm">
        {message.response.slice(0, 350)}
        {message.response.length > 350 ? "..." : ""}
      </div>

      <div className="mt-auto text-xs text-foreground-500">
        {parseDate(message.date as string)}
      </div>
    </Link>
  );
};
