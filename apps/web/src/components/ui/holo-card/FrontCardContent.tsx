import type React from "react";

import { CARD_CLASSES } from "./constants";
import { RotatingExperienceLogo } from "./RotatingExperienceLogo";

interface FrontCardContentProps {
  name: string;
  personalityPhrase?: string;
  accountNumber: string | number;
  memberSince: string | number;
  isStatic?: boolean;
}

export const FrontCardContent: React.FC<FrontCardContentProps> = ({
  name,
  personalityPhrase,
  accountNumber,
  memberSince,
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
          {name}
        </div>
        <div className="mb-10 font-light text-white italic">
          {personalityPhrase}
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
              User {accountNumber}
            </span>
            <span
              className={
                isStatic
                  ? "text-xs text-white/50"
                  : "text-xs text-white/50 font-mono uppercase"
              }
            >
              {memberSince}
            </span>
          </div>
        </div>
      </div>
    </>
  );
};
