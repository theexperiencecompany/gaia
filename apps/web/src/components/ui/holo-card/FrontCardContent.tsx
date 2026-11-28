import type React from "react";

import { CARD_CLASSES } from "./constants";
import { RotatingExperienceLogo } from "./RotatingExperienceLogo";
import type { HoloCardDisplayData } from "./types";

interface FrontCardContentProps {
  card: Pick<
    HoloCardDisplayData,
    "name" | "personality_phrase" | "account_number" | "member_since"
  >;
  isStatic?: boolean;
}

export const FrontCardContent: React.FC<FrontCardContentProps> = ({
  card,
  isStatic = false,
}) => {
  return (
    <>
      <div
        style={{
          position: "absolute",
          right: 32,
          bottom: 32,
          zIndex: 3,
          pointerEvents: "none",
        }}
      >
        <RotatingExperienceLogo size={96} />
      </div>
      <div className={CARD_CLASSES.INFO_BOX}>
        <div
          className={
            isStatic
              ? "font-serif! text-4xl font-normal! text-white"
              : "font-serif text-4xl text-white"
          }
        >
          {card.name}
        </div>
        <div className="mb-10 font-light text-white italic">
          {card.personality_phrase}
        </div>

        <div className="flex w-full items-center justify-between">
          <div className="flex flex-col items-start gap-1">
            <span
              className={
                isStatic
                  ? "text-sm text-white/80"
                  : "text-sm text-white/80 font-mono uppercase"
              }
            >
              User #{card.account_number}
            </span>
            <span
              className={
                isStatic
                  ? "text-xs text-white/50"
                  : "text-xs text-white/50 font-mono uppercase"
              }
            >
              {card.member_since}
            </span>
          </div>
        </div>
      </div>
    </>
  );
};
