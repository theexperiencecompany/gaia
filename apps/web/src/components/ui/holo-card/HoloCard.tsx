import type React from "react";
import { useId, useRef, useState } from "react";
import Tilt from "react-parallax-tilt";

import { StyledHoloCard } from "@/app/styles/holo-card.styles";
import { getHouseImage } from "@/features/onboarding/constants/houses";

import { BackCardContent, BackCardFooter } from "./BackCardContent";
import { CardOverlay } from "./CardOverlay";
import { CARD_CLASSES } from "./constants";
import { FrontCardContent } from "./FrontCardContent";
import { LogoHeader } from "./LogoHeader";
import {
  STAMP_NATURAL_HEIGHT,
  STAMP_NATURAL_WIDTH,
  STAMP_OUTER_PATH_D,
} from "./stampShape";
import type { HoloCardProps } from "./types";
import { calculateBackgroundPosition } from "./utils";

// Use CSS `border` not mask-composite: html-to-image drops the mask and downloads it as a filled rectangle.
const STAMP_BORDER_STYLE = {
  position: "absolute" as const,
  inset: 22,
  border: "4px solid rgba(255, 255, 255, 0.92)",
  borderRadius: 0,
  pointerEvents: "none" as const,
  zIndex: 4,
  boxSizing: "border-box" as const,
};

// Hoisted out of `HoloCard` so the component keeps a stable identity across
// renders (defining it inline would remount it every frame).
const StampBorder = () => <div aria-hidden style={STAMP_BORDER_STYLE} />;

interface HoloCardFaceCommonProps {
  overlayColor?: string;
  overlayOpacity: number;
  clipStyle: React.CSSProperties;
  houseImage: string;
  height: number;
  width: number;
  showSparkles: boolean;
  cardRef: React.RefObject<HTMLInputElement | null>;
  hover: boolean;
  animated: boolean;
  activeBackgroundPosition: { tp: number; lp: number };
  activeRotation: { x: number; y: number };
  onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void;
  onTouchMove: (e: React.TouchEvent<HTMLDivElement>) => void;
  onMouseOut: () => void;
  isStatic: boolean;
  children?: React.ReactNode;
}

interface HoloCardFrontFaceProps extends HoloCardFaceCommonProps {
  name: string;
  personalityPhrase: string;
  accountNumber: string | number;
  memberSince: string | number;
}

function HoloCardFrontFace({
  name,
  personalityPhrase,
  accountNumber,
  memberSince,
  overlayColor,
  overlayOpacity,
  clipStyle,
  houseImage,
  height,
  width,
  showSparkles,
  cardRef,
  hover,
  animated,
  activeBackgroundPosition,
  activeRotation,
  onMouseMove,
  onTouchMove,
  onMouseOut,
  isStatic,
  children,
}: HoloCardFrontFaceProps) {
  const content = (
    <>
      <StampBorder />
      <CardOverlay
        overlayColor={overlayColor}
        overlayOpacity={overlayOpacity}
      />
      <div className={CARD_CLASSES.CONTENT_WRAPPER}>
        <LogoHeader variant="front" />
        <FrontCardContent
          name={name}
          personalityPhrase={personalityPhrase}
          accountNumber={accountNumber}
          memberSince={memberSince}
          isStatic={isStatic ? true : undefined}
        />
      </div>
      <StyledHoloCard
        $url={houseImage}
        ref={cardRef}
        $active={isStatic ? false : hover}
        $animated={isStatic ? false : animated}
        $activeRotation={activeRotation}
        $activeBackgroundPosition={activeBackgroundPosition}
        onMouseMove={isStatic ? undefined : onMouseMove}
        onTouchMove={isStatic ? undefined : onTouchMove}
        onMouseOut={isStatic ? undefined : onMouseOut}
        $height={height}
        $width={width}
        $showSparkles={showSparkles}
      >
        {children}
      </StyledHoloCard>
    </>
  );

  if (isStatic) {
    return (
      <div className="relative h-full w-full" style={clipStyle}>
        {content}
      </div>
    );
  }

  return (
    <Tilt className="relative h-full w-full p-0!" style={clipStyle}>
      {content}
    </Tilt>
  );
}

interface HoloCardBackFaceProps extends HoloCardFaceCommonProps {
  name: string;
  personalityPhrase: string;
  userBio: string;
  accountNumber: string | number;
  memberSince: string | number;
}

function HoloCardBackFace({
  name,
  personalityPhrase,
  userBio,
  accountNumber,
  memberSince,
  overlayColor,
  overlayOpacity,
  clipStyle,
  houseImage,
  height,
  width,
  showSparkles,
  cardRef,
  hover,
  animated,
  activeBackgroundPosition,
  activeRotation,
  onMouseMove,
  onTouchMove,
  onMouseOut,
  isStatic,
  children,
}: HoloCardBackFaceProps) {
  const content = (
    <>
      <StampBorder />
      <CardOverlay
        overlayColor={overlayColor}
        overlayOpacity={overlayOpacity}
      />
      <div className={CARD_CLASSES.CONTENT_WRAPPER_BACK}>
        <div className="flex min-h-0 w-full flex-1 flex-col gap-4">
          <BackCardContent
            name={name}
            personalityPhrase={personalityPhrase}
            userBio={userBio}
            accountNumber={accountNumber}
            memberSince={memberSince}
            isStatic={isStatic ? true : undefined}
          />
        </div>
        <BackCardFooter
          accountNumber={accountNumber}
          memberSince={memberSince}
          isStatic={isStatic ? true : undefined}
        />
      </div>
      <StyledHoloCard
        $url={houseImage}
        ref={cardRef}
        $active={isStatic ? false : hover}
        $animated={isStatic ? false : animated}
        $activeRotation={activeRotation}
        $activeBackgroundPosition={activeBackgroundPosition}
        onMouseMove={isStatic ? undefined : onMouseMove}
        onTouchMove={isStatic ? undefined : onTouchMove}
        onMouseOut={isStatic ? undefined : onMouseOut}
        $height={height}
        $width={width}
        $showSparkles={showSparkles}
      >
        {children}
      </StyledHoloCard>
    </>
  );

  if (isStatic) {
    return (
      <div className="relative h-full w-full" style={clipStyle}>
        {content}
      </div>
    );
  }

  return (
    <Tilt className="relative h-full w-full p-0!" style={clipStyle}>
      {content}
    </Tilt>
  );
}

function HoloCardClipDefs({
  clipId,
  clipTransform,
}: {
  clipId: string;
  clipTransform: string;
}) {
  return (
    <svg
      aria-hidden
      width="0"
      height="0"
      style={{ position: "absolute", width: 0, height: 0 }}
    >
      <title>Stamp clip-path</title>
      <defs>
        <clipPath id={clipId} clipPathUnits="userSpaceOnUse">
          <path d={STAMP_OUTER_PATH_D} transform={clipTransform} />
        </clipPath>
      </defs>
    </svg>
  );
}

export const HoloCard = ({
  data,
  height = 446,
  width = 320,
  showSparkles = true,
  forceSide,
  children,
}: HoloCardProps & { forceSide?: "front" | "back" }) => {
  const [hover, setHover] = useState(false);
  const [animated, setAnimated] = useState(true);
  const [isFlipped, setIsFlipped] = useState(false);
  const [activeBackgroundPosition, setActiveBackgroundPosition] = useState({
    tp: 0,
    lp: 0,
  });
  const [activeRotation, setActiveRotation] = useState({
    y: 0,
    x: 0,
  });
  const ref = useRef<HTMLInputElement>(null);

  const {
    house,
    name,
    personality_phrase,
    user_bio,
    account_number,
    member_since,
    overlay_color,
    overlay_opacity = 40,
  } = data;

  const houseImage = getHouseImage(house);

  const handleCardClick = () => {
    if (!forceSide) {
      setIsFlipped((prev) => !prev);
    }
  };

  const handleOnMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    setAnimated(false);
    setHover(true);
    const card = ref.current;
    if (!card) return;
    const offsetX = event.nativeEvent.offsetX;
    const offsetY = event.nativeEvent.offsetY;
    const { clientWidth, clientHeight } = card;
    const position = calculateBackgroundPosition(
      offsetX,
      offsetY,
      clientWidth,
      clientHeight,
    );
    setActiveBackgroundPosition(position);
  };

  const handleOnTouchMove = (event: React.TouchEvent<HTMLDivElement>) => {
    setAnimated(false);
    setHover(true);
    const card = ref.current;
    if (!card) return;
    const touch = event.touches[0];
    const rect = card.getBoundingClientRect();
    const offsetX = touch.clientX - rect.left;
    const offsetY = touch.clientY - rect.top;
    const { clientWidth, clientHeight } = card;
    const position = calculateBackgroundPosition(
      offsetX,
      offsetY,
      clientWidth,
      clientHeight,
    );
    setActiveBackgroundPosition(position);
  };

  const handleOnMouseOut = () => {
    setHover(false);
    setAnimated(true);
    setActiveRotation({ x: 0, y: 0 });
  };

  const effectiveFlipped = forceSide ? forceSide === "back" : isFlipped;

  const containerStyle = forceSide
    ? {
        perspective: "none",
        transform: "none",
      }
    : {
        perspective: "1000px",
        cursor: "pointer",
      };

  const innerStyle = forceSide
    ? {
        transform: "none",
        position: "relative" as const,
        height: `${height}px`,
        width: `${width}px`,
      }
    : {
        transformStyle: "preserve-3d" as const,
        transform: effectiveFlipped ? "rotateY(180deg)" : "rotateY(0deg)",
        height: `${height}px`,
        width: `${width}px`,
      };

  const frontStyle = forceSide
    ? {
        display: forceSide === "front" ? "block" : "none",
        position: "absolute" as const,
        inset: 0,
      }
    : {
        position: "absolute" as const,
        inset: 0,
        backfaceVisibility: "hidden" as const,
        WebkitBackfaceVisibility: "hidden" as const,
      };

  const backStyle = forceSide
    ? {
        display: forceSide === "back" ? "block" : "none",
        position: "absolute" as const,
        inset: 0,
        transform: "none",
      }
    : {
        position: "absolute" as const,
        inset: 0,
        backfaceVisibility: "hidden" as const,
        WebkitBackfaceVisibility: "hidden" as const,
        transform: "rotateY(180deg)",
      };

  const clipId = useId();
  const clipUrl = `url(#${clipId})`;
  const clipTransform = `scale(${width / STAMP_NATURAL_HEIGHT} ${height / STAMP_NATURAL_WIDTH}) translate(${STAMP_NATURAL_HEIGHT} 0) rotate(90)`;
  const clipStyle = {
    clipPath: clipUrl,
    WebkitClipPath: clipUrl,
  };

  const isFlippable = !forceSide;
  const isStatic = Boolean(forceSide);

  const faceCommon = {
    overlayColor: overlay_color,
    overlayOpacity: overlay_opacity,
    clipStyle,
    houseImage,
    height,
    width,
    showSparkles,
    cardRef: ref,
    hover,
    animated,
    activeBackgroundPosition,
    activeRotation,
    onMouseMove: handleOnMouseMove,
    onTouchMove: handleOnTouchMove,
    onMouseOut: handleOnMouseOut,
    isStatic,
  } as const;

  return (
    <div
      className={forceSide ? "" : "perspective-1000"}
      onClick={handleCardClick}
      role={isFlippable ? "button" : undefined}
      tabIndex={isFlippable ? 0 : undefined}
      onKeyDown={
        isFlippable
          ? (event: React.KeyboardEvent<HTMLDivElement>) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                handleCardClick();
              }
            }
          : undefined
      }
      style={containerStyle}
    >
      <HoloCardClipDefs clipId={clipId} clipTransform={clipTransform} />
      <div
        className={
          forceSide ? "relative" : "relative transition-transform duration-700"
        }
        style={innerStyle}
      >
        <div style={frontStyle}>
          <HoloCardFrontFace
            name={name}
            personalityPhrase={personality_phrase}
            accountNumber={account_number}
            memberSince={member_since}
            {...faceCommon}
          >
            {children}
          </HoloCardFrontFace>
        </div>
        <div style={backStyle}>
          <HoloCardBackFace
            name={name}
            personalityPhrase={personality_phrase}
            userBio={user_bio}
            accountNumber={account_number}
            memberSince={member_since}
            {...faceCommon}
          >
            {children}
          </HoloCardBackFace>
        </div>
      </div>
    </div>
  );
};
