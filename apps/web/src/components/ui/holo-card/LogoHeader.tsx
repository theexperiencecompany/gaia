import Image from "next/image";
import type React from "react";

import { CARD_CLASSES, CARD_IMAGES, LOGO_SIZES } from "./constants";

interface LogoHeaderProps {
  house?: string;
  variant?: "front" | "back";
}

export const LogoHeader: React.FC<LogoHeaderProps> = ({
  house,
  variant = "front",
}) => {
  const logoSize = variant === "front" ? LOGO_SIZES.FRONT : LOGO_SIZES.BACK;
  const houseBadgeClass =
    variant === "front"
      ? CARD_CLASSES.HOUSE_BADGE
      : CARD_CLASSES.HOUSE_BADGE_BACK;

  return (
    <div className="absolute top-4 left-0 flex w-full justify-between px-3">
      <div className={CARD_CLASSES.LOGO_BADGE}>
        <Image
          src={CARD_IMAGES.LOGO_WHITE}
          alt="GAIA Logo"
          width={logoSize.width}
          height={logoSize.height}
          className="object-contain"
        />
      </div>
      {house && <div className={houseBadgeClass}>{house}</div>}
    </div>
  );
};
