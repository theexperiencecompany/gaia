import Image from "next/image";
import type React from "react";

import { CARD_CLASSES, CARD_IMAGES, LOGO_SIZES } from "./constants";

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
      <Image
        src={CARD_IMAGES.EXPERIENCE_LOGO}
        alt="Experience Logo"
        className={CARD_CLASSES.EXPERIENCE_LOGO}
        fill
      />

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

          <div className="flex gap-2">
            <Image
              src={CARD_IMAGES.EXPERIENCE_LOGO}
              alt="Experience Logo"
              width={LOGO_SIZES.EXPERIENCE.width}
              height={LOGO_SIZES.EXPERIENCE.height}
            />
          </div>
        </div>
      </div>
    </>
  );
};
