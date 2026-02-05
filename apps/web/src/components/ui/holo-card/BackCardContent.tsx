import type React from "react";

import { CARD_CLASSES } from "./constants";

interface BackCardContentProps {
  name: string;
  personalityPhrase?: string;
  userBio?: string;
  accountNumber: string | number;
  memberSince: string | number;
  isStatic?: boolean;
}

export const BackCardContent: React.FC<BackCardContentProps> = ({
  name,
  personalityPhrase,
  userBio,
  isStatic = false,
}) => {
  return (
    <div className="flex w-full flex-col gap-4">
      <div className={CARD_CLASSES.INFO_BOX_BACK}>
        <div
          className={
            isStatic
              ? "mb-2 font-serif text-2xl font-normal text-white"
              : "mb-0 font-serif text-2xl font-normal text-white"
          }
        >
          {name}
        </div>
        <div
          className={
            isStatic
              ? "mb-4 text-sm font-light text-white/80 italic"
              : "mb-2 text-sm font-light text-white/80 italic"
          }
        >
          {personalityPhrase}
        </div>
        <p className="text-sm text-white/80">{userBio}</p>
      </div>
    </div>
  );
};

interface BackCardFooterProps {
  accountNumber: string | number;
  memberSince: string | number;
  isStatic?: boolean;
}

export const BackCardFooter: React.FC<BackCardFooterProps> = ({
  accountNumber,
  memberSince,
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
          {memberSince}
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
          {accountNumber}
        </span>
      </div>
    </div>
  );
};
