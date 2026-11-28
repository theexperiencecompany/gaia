import type React from "react";

import { CARD_CLASSES } from "./constants";
import type { HoloCardDisplayData } from "./types";

interface BackCardContentProps {
  card: Pick<HoloCardDisplayData, "name" | "personality_phrase" | "user_bio">;
  isStatic?: boolean;
}

export const BackCardContent: React.FC<BackCardContentProps> = ({
  card,
  isStatic = false,
}) => {
  return (
    <div className="flex min-h-0 w-full flex-1 flex-col gap-4">
      <div className={CARD_CLASSES.INFO_BOX_BACK}>
        <div
          className={
            isStatic
              ? "mb-2 font-serif text-2xl font-normal text-white"
              : "mb-0 font-serif text-2xl font-normal text-white"
          }
        >
          {card.name}
        </div>
        <div
          className={
            isStatic
              ? "mb-4 text-sm font-light text-white/80 italic"
              : "mb-2 text-sm font-light text-white/80 italic"
          }
        >
          {card.personality_phrase}
        </div>
        <p className="scrollbar-faint pointer-events-auto min-h-0 flex-1 overflow-y-auto overscroll-contain text-sm text-white/80">
          {card.user_bio}
        </p>
      </div>
    </div>
  );
};

interface BackCardFooterProps {
  card: Pick<HoloCardDisplayData, "account_number" | "member_since">;
  isStatic?: boolean;
}

export const BackCardFooter: React.FC<BackCardFooterProps> = ({
  card,
  isStatic = false,
}) => {
  return (
    <div className={CARD_CLASSES.FOOTER_BOX}>
      <div className="flex flex-col gap-1">
        <span
          className={
            isStatic
              ? "text-xs text-white/50 font-mono! uppercase"
              : "text-xs text-white/50 font-mono uppercase"
          }
        >
          Member Since
        </span>
        <span className="text-sm font-medium text-white/80 font-mono uppercase">
          {card.member_since}
        </span>
      </div>
      <div className="flex flex-col items-end gap-1">
        <span className="text-xs text-white/50 font-mono uppercase">
          User ID
        </span>
        <span
          className={
            isStatic
              ? "text-sm font-medium text-white/80 font-mono uppercase"
              : "text-sm font-medium text-white/80"
          }
        >
          #{card.account_number}
        </span>
      </div>
    </div>
  );
};
