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

  // clipPath ID must be unique per instance so multiple cards on a page don't collide.
  const clipId = useId();
  const clipUrl = `url(#${clipId})`;
  const clipTransform = `scale(${width / STAMP_NATURAL_HEIGHT} ${height / STAMP_NATURAL_WIDTH}) translate(${STAMP_NATURAL_HEIGHT} 0) rotate(90)`;
  const clipStyle = {
    clipPath: clipUrl,
    WebkitClipPath: clipUrl,
  };

  // Use CSS `border` not mask-composite: html-to-image drops the mask and downloads it as a filled rectangle.
  const stampBorderStyle = {
    position: "absolute" as const,
    inset: 22,
    border: "4px solid rgba(255, 255, 255, 0.92)",
    borderRadius: 0,
    pointerEvents: "none" as const,
    zIndex: 4,
    boxSizing: "border-box" as const,
  };
  const StampBorder = () => <div aria-hidden style={stampBorderStyle} />;

  return (
    <div
      className={forceSide ? "" : "perspective-1000"}
      onClick={handleCardClick}
      style={containerStyle}
    >
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
      <div
        className={
          forceSide ? "relative" : "relative transition-transform duration-700"
        }
        style={innerStyle}
      >
        {/* Front Side */}
        <div style={frontStyle}>
          {forceSide ? (
            <div className="relative h-full w-full" style={clipStyle}>
              <StampBorder />
              <CardOverlay
                overlayColor={overlay_color}
                overlayOpacity={overlay_opacity}
              />

              <div className={CARD_CLASSES.CONTENT_WRAPPER}>
                <LogoHeader variant="front" />
                <FrontCardContent
                  name={name}
                  personalityPhrase={personality_phrase}
                  accountNumber={account_number}
                  memberSince={member_since}
                  isStatic
                />
              </div>

              {/* <DitherEffect intensity={1}> */}
              <StyledHoloCard
                $url={houseImage}
                ref={ref}
                $active={false}
                $animated={false}
                $activeRotation={activeRotation}
                $activeBackgroundPosition={activeBackgroundPosition}
                $height={height}
                $width={width}
                $showSparkles={showSparkles}
              >
                {children}
              </StyledHoloCard>
              {/* </DitherEffect> */}
            </div>
          ) : (
            <Tilt className="relative h-full w-full p-0!" style={clipStyle}>
              <StampBorder />
              <CardOverlay
                overlayColor={overlay_color}
                overlayOpacity={overlay_opacity}
              />

              <div className={CARD_CLASSES.CONTENT_WRAPPER}>
                <LogoHeader variant="front" />
                <FrontCardContent
                  name={name}
                  personalityPhrase={personality_phrase}
                  accountNumber={account_number}
                  memberSince={member_since}
                />
              </div>

              {/* <DitherEffect intensity={1}> */}
              <StyledHoloCard
                $url={houseImage}
                ref={ref}
                $active={hover}
                $animated={animated}
                $activeRotation={activeRotation}
                $activeBackgroundPosition={activeBackgroundPosition}
                onMouseMove={handleOnMouseMove}
                onTouchMove={handleOnTouchMove}
                onMouseOut={handleOnMouseOut}
                $height={height}
                $width={width}
                $showSparkles={showSparkles}
              >
                {children}
              </StyledHoloCard>
              {/* </DitherEffect> */}
            </Tilt>
          )}
        </div>

        {/* Back Side */}
        <div style={backStyle}>
          {forceSide ? (
            <div className="relative h-full w-full" style={clipStyle}>
              <StampBorder />
              <CardOverlay
                overlayColor={overlay_color}
                overlayOpacity={overlay_opacity}
              />

              <div className={CARD_CLASSES.CONTENT_WRAPPER_BACK}>
                <div className="flex min-h-0 w-full flex-1 flex-col gap-4">
                  <BackCardContent
                    name={name}
                    personalityPhrase={personality_phrase}
                    userBio={user_bio}
                    accountNumber={account_number}
                    memberSince={member_since}
                    isStatic
                  />
                </div>

                <BackCardFooter
                  accountNumber={account_number}
                  memberSince={member_since}
                  isStatic
                />
              </div>

              {/* <DitherEffect intensity={1}> */}
              <StyledHoloCard
                $url={houseImage}
                ref={ref}
                $active={false}
                $animated={false}
                $activeRotation={activeRotation}
                $activeBackgroundPosition={activeBackgroundPosition}
                $height={height}
                $width={width}
                $showSparkles={showSparkles}
              >
                {children}
              </StyledHoloCard>
              {/* </DitherEffect> */}
            </div>
          ) : (
            <Tilt className="relative h-full w-full p-0!" style={clipStyle}>
              <StampBorder />
              <CardOverlay
                overlayColor={overlay_color}
                overlayOpacity={overlay_opacity}
              />

              <div className={CARD_CLASSES.CONTENT_WRAPPER_BACK}>
                <div className="flex min-h-0 w-full flex-1 flex-col gap-4">
                  <BackCardContent
                    name={name}
                    personalityPhrase={personality_phrase}
                    userBio={user_bio}
                    accountNumber={account_number}
                    memberSince={member_since}
                  />
                </div>

                <BackCardFooter
                  accountNumber={account_number}
                  memberSince={member_since}
                />
              </div>

              {/* <DitherEffect intensity={1}> */}
              <StyledHoloCard
                $url={houseImage}
                ref={ref}
                $active={hover}
                $animated={animated}
                $activeRotation={activeRotation}
                $activeBackgroundPosition={activeBackgroundPosition}
                onMouseMove={handleOnMouseMove}
                onTouchMove={handleOnTouchMove}
                onMouseOut={handleOnMouseOut}
                $height={height}
                $width={width}
                $showSparkles={showSparkles}
              >
                {children}
              </StyledHoloCard>
              {/* </DitherEffect> */}
            </Tilt>
          )}
        </div>
      </div>
    </div>
  );
};
