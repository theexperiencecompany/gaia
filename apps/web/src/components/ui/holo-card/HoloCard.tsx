import type React from "react";
import { useRef, useState } from "react";
import Tilt from "react-parallax-tilt";

import { StyledHoloCard } from "@/app/styles/holo-card.styles";
import { getHouseImage } from "@/features/onboarding/constants/houses";

import { BackCardContent, BackCardFooter } from "./BackCardContent";
import { CardOverlay } from "./CardOverlay";
import { CARD_CLASSES } from "./constants";
import { FrontCardContent } from "./FrontCardContent";
import { LogoHeader } from "./LogoHeader";
import type { HoloCardProps } from "./types";
import { calculateBackgroundPosition } from "./utils";

interface CardFaceWrapperProps {
  isStatic: boolean;
  hover: boolean;
  animated: boolean;
  activeRotation: { x: number; y: number };
  activeBackgroundPosition: { tp: number; lp: number };
  houseImage: string;
  height: number;
  width: number;
  showSparkles: boolean;
  cardRef: React.RefObject<HTMLInputElement | null>;
  onMouseMove?: (event: React.MouseEvent<HTMLDivElement>) => void;
  onTouchMove?: (event: React.TouchEvent<HTMLDivElement>) => void;
  onMouseOut?: () => void;
  overlayColor?: string;
  overlayOpacity: number;
  children?: React.ReactNode;
  innerContent: React.ReactNode;
  contentWrapperClass: string;
}

const CardFaceWrapper = ({
  isStatic,
  hover,
  animated,
  activeRotation,
  activeBackgroundPosition,
  houseImage,
  height,
  width,
  showSparkles,
  cardRef,
  onMouseMove,
  onTouchMove,
  onMouseOut,
  overlayColor,
  overlayOpacity,
  children,
  innerContent,
  contentWrapperClass,
}: CardFaceWrapperProps) => {
  const holoCardProps = isStatic
    ? {
        $active: false as const,
        $animated: false as const,
      }
    : {
        $active: hover,
        $animated: animated,
        onMouseMove,
        onTouchMove,
        onMouseOut,
      };

  const content = (
    <div className="relative h-full w-full overflow-hidden rounded-2xl shadow-xl">
      <CardOverlay
        overlayColor={overlayColor}
        overlayOpacity={overlayOpacity}
      />

      <div className={contentWrapperClass}>{innerContent}</div>

      {/* <DitherEffect intensity={1}> */}
      <StyledHoloCard
        $url={houseImage}
        ref={cardRef}
        $activeRotation={activeRotation}
        $activeBackgroundPosition={activeBackgroundPosition}
        $height={height}
        $width={width}
        $showSparkles={showSparkles}
        {...holoCardProps}
      >
        {children}
      </StyledHoloCard>
      {/* </DitherEffect> */}
    </div>
  );

  if (isStatic) {
    return content;
  }

  return (
    <Tilt className="relative h-full w-full overflow-hidden rounded-2xl p-0! shadow-xl">
      <CardOverlay
        overlayColor={overlayColor}
        overlayOpacity={overlayOpacity}
      />

      <div className={contentWrapperClass}>{innerContent}</div>

      {/* <DitherEffect intensity={1}> */}
      <StyledHoloCard
        $url={houseImage}
        ref={cardRef}
        $activeRotation={activeRotation}
        $activeBackgroundPosition={activeBackgroundPosition}
        $height={height}
        $width={width}
        $showSparkles={showSparkles}
        {...holoCardProps}
      >
        {children}
      </StyledHoloCard>
      {/* </DitherEffect> */}
    </Tilt>
  );
};

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
      setIsFlipped(!isFlipped);
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
  const isStatic = !!forceSide;

  const sharedFaceProps = {
    isStatic,
    hover,
    animated,
    activeRotation,
    activeBackgroundPosition,
    houseImage,
    height,
    width,
    showSparkles,
    cardRef: ref,
    onMouseMove: handleOnMouseMove,
    onTouchMove: handleOnTouchMove,
    onMouseOut: handleOnMouseOut,
    overlayColor: overlay_color,
    overlayOpacity: overlay_opacity,
    children,
  };

  // Static mode styles for download
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
        transform: "none", // Crucial: No rotation for static back view
      }
    : {
        position: "absolute" as const,
        inset: 0,
        backfaceVisibility: "hidden" as const,
        WebkitBackfaceVisibility: "hidden" as const,
        transform: "rotateY(180deg)",
      };

  return (
    <div
      className={forceSide ? "" : "perspective-1000"}
      onClick={handleCardClick}
      style={containerStyle}
    >
      <div
        className={
          forceSide ? "relative" : "relative transition-transform duration-700"
        }
        style={innerStyle}
      >
        {/* Front Side */}
        <div style={frontStyle}>
          <CardFaceWrapper
            {...sharedFaceProps}
            contentWrapperClass={CARD_CLASSES.CONTENT_WRAPPER}
            innerContent={
              <>
                <LogoHeader house={house} variant="front" />
                <FrontCardContent
                  name={name}
                  personalityPhrase={personality_phrase}
                  accountNumber={account_number}
                  memberSince={member_since}
                  isStatic={isStatic}
                />
              </>
            }
          />
        </div>

        {/* Back Side */}
        <div style={backStyle}>
          <CardFaceWrapper
            {...sharedFaceProps}
            contentWrapperClass={CARD_CLASSES.CONTENT_WRAPPER_BACK}
            innerContent={
              <>
                <div className="flex w-full flex-col gap-4">
                  <LogoHeader house={house} variant="back" />
                  <BackCardContent
                    name={name}
                    personalityPhrase={personality_phrase}
                    userBio={user_bio}
                    accountNumber={account_number}
                    memberSince={member_since}
                    isStatic={isStatic}
                  />
                </div>

                <BackCardFooter
                  accountNumber={account_number}
                  memberSince={member_since}
                  isStatic={isStatic}
                />
              </>
            }
          />
        </div>
      </div>
    </div>
  );
};
