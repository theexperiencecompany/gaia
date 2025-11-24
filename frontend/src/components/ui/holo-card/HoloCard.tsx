import Image from "next/image";
import React, { useRef, useState } from "react";
import Tilt from "react-parallax-tilt";

import { StyledHoloCard } from "@/app/styles/holo-card.styles";
import { getHouseImage } from "@/features/onboarding/constants/houses";

import { HoloCardProps } from "./types";

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
    const l = event.nativeEvent.offsetX;
    const t = event.nativeEvent.offsetY;

    const h = card ? card.clientHeight : 0;
    const w = card ? card.clientWidth : 0;

    const px = Math.abs(Math.floor((100 / w) * l) - 100);
    const py = Math.abs(Math.floor((100 / h) * t) - 100);

    const lp = 50 + (px - 50) / 1.5;
    const tp = 50 + (py - 50) / 1.5;

    setActiveBackgroundPosition({ lp, tp });
  };

  const handleOnTouchMove = (event: React.TouchEvent<HTMLDivElement>) => {
    setAnimated(false);
    setHover(true);

    const card = ref.current;
    if (!card) return;

    const touch = event.touches[0];
    const rect = card.getBoundingClientRect();
    const l = touch.clientX - rect.left;
    const t = touch.clientY - rect.top;

    const h = card.clientHeight;
    const w = card.clientWidth;

    const px = Math.abs(Math.floor((100 / w) * l) - 100);
    const py = Math.abs(Math.floor((100 / h) * t) - 100);

    const lp = 50 + (px - 50) / 1.5;
    const tp = 50 + (py - 50) / 1.5;

    setActiveBackgroundPosition({ lp, tp });
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
          {forceSide ? (
            <div className="relative h-full w-full overflow-hidden rounded-2xl shadow-xl">
              {overlay_color && (
                <div
                  className="pointer-events-none absolute inset-0 z-[3]"
                  style={{
                    background: overlay_color,
                    mixBlendMode: "overlay",
                    opacity: overlay_opacity / 100,
                  }}
                />
              )}

              <div className="pointer-events-none absolute z-[2] flex h-full w-full flex-col items-start justify-end p-3 text-white transition">
                <div className="absolute top-4 left-0 flex w-full justify-between px-3">
                  <div className="rounded-full bg-white/30 p-1 px-2 font-serif text-xl font-light text-white/70 backdrop-blur-md">
                    <Image
                      src="/images/logos/text_w_logo_white.webp"
                      alt="GAIA Logo"
                      width={100}
                      height={30}
                      className="object-contain"
                    />
                  </div>
                  {house && (
                    <div className="rounded-full bg-white/20 p-1 px-4 font-serif text-xl font-light text-white/70 backdrop-blur-md">
                      {house}
                    </div>
                  )}
                </div>
                <Image
                  src="/images/logos/experience_logo.svg"
                  alt="Experience Logo"
                  className="scale-125 opacity-10"
                  fill
                />

                <div className="relative flex w-full flex-col gap-1 overflow-hidden rounded-2xl bg-black/20 p-3 backdrop-blur-md">
                  <div className="font-serif text-4xl font-bold text-white">
                    {name}
                  </div>
                  <div className="mb-10 font-light text-white italic">
                    {personality_phrase}
                  </div>

                  <div className="flex w-full items-center justify-between">
                    <div className="flex flex-col items-start gap-1">
                      <span className="text-sm text-white/80">User {account_number}</span>
                      <span className="text-xs text-white/50">{member_since}</span>
                    </div>

                    <div className="flex gap-2">
                      <Image
                        src="/images/logos/experience_logo.svg"
                        alt="Experience Logo"
                        width={30}
                        height={30}
                      />
                    </div>
                  </div>
                </div>
              </div>

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
            </div>
          ) : (
            <Tilt className="relative h-full w-full overflow-hidden rounded-2xl p-0! shadow-xl">
              {overlay_color && (
                <div
                  className="pointer-events-none absolute inset-0 z-[3]"
                  style={{
                    background: overlay_color,
                    mixBlendMode: "overlay",
                    opacity: overlay_opacity / 100,
                  }}
                />
              )}

              <div className="pointer-events-none absolute z-[2] flex h-full w-full flex-col items-start justify-end p-3 text-white transition">
                <div className="absolute top-4 left-0 flex w-full justify-between px-3">
                  <div className="rounded-full bg-white/30 p-1 px-2 font-serif text-xl font-light text-white/70 backdrop-blur-md">
                    <Image
                      src="/images/logos/text_w_logo_white.webp"
                      alt="GAIA Logo"
                      width={100}
                      height={30}
                      className="object-contain"
                    />
                  </div>
                  {house && (
                    <div className="rounded-full bg-white/20 p-1 px-4 font-serif text-xl font-light text-white/70 backdrop-blur-md">
                      {house}
                    </div>
                  )}
                </div>
                <Image
                  src="/images/logos/experience_logo.svg"
                  alt="Experience Logo"
                  className="scale-125 opacity-10"
                  fill
                />

                <div className="relative flex w-full flex-col gap-1 overflow-hidden rounded-2xl bg-black/20 p-3 backdrop-blur-md">
                  <div className="font-serif text-4xl font-bold text-white">
                    {name}
                  </div>
                  <div className="mb-10 font-light text-white italic">
                    {personality_phrase}
                  </div>

                  <div className="flex w-full items-center justify-between">
                    <div className="flex flex-col items-start gap-1">
                      <span className="text-sm text-white/80">User {account_number}</span>
                      <span className="text-xs text-white/50">{member_since}</span>
                    </div>

                    <div className="flex gap-2">
                      <Image
                        src="/images/logos/experience_logo.svg"
                        alt="Experience Logo"
                        width={30}
                        height={30}
                      />
                    </div>
                  </div>
                </div>
              </div>

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
            </Tilt>
          )}
        </div>

        {/* Back Side */}
        <div style={backStyle}>
          {forceSide ? (
            <div className="relative h-full w-full overflow-hidden rounded-2xl shadow-xl">
              {overlay_color && (
                <div
                  className="pointer-events-none absolute inset-0 z-[3]"
                  style={{
                    background: overlay_color,
                    mixBlendMode: "overlay",
                    opacity: overlay_opacity / 100,
                  }}
                />
              )}

              <div className="pointer-events-none absolute z-[2] flex h-full w-full flex-col items-start justify-between p-3 text-white">
                <div className="flex w-full flex-col gap-4">
                  <div className="flex items-center justify-between">
                    <div className="rounded-full bg-white/30 p-1 px-2 backdrop-blur-md">
                      <Image
                        src="/images/logos/text_w_logo_white.webp"
                        alt="GAIA Logo"
                        width={80}
                        height={24}
                        className="object-contain"
                      />
                    </div>
                    {house && (
                      <div className="rounded-full bg-white/20 p-1 px-3 font-serif text-xl font-light text-white/70 backdrop-blur-md">
                        {house}
                      </div>
                    )}
                  </div>

                  <div className="relative overflow-hidden rounded-2xl bg-black/20 p-4 backdrop-blur-md">
                    <div className="mb-2 font-serif text-2xl font-bold text-white">
                      {name}
                    </div>
                    <div className="mb-4 text-sm font-light text-white/80 italic">
                      {personality_phrase}
                    </div>
                    <p className="text-sm text-white/80">{user_bio}</p>
                  </div>
                </div>

                <div className="flex w-full items-center justify-between rounded-xl bg-black/20 p-3 backdrop-blur-md">
                  <div className="flex flex-col gap-1">
                    <span className="text-xs text-white/50">Member Since</span>
                    <span className="text-sm font-medium text-white/80">
                      {member_since}
                    </span>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-xs text-white/50">User ID</span>
                    <span className="text-sm font-medium text-white/80">
                      {account_number}
                    </span>
                  </div>
                </div>
              </div>

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
            </div>
          ) : (
            <Tilt className="relative h-full w-full overflow-hidden rounded-2xl p-0! shadow-xl">
              {overlay_color && (
                <div
                  className="pointer-events-none absolute inset-0 z-[3]"
                  style={{
                    background: overlay_color,
                    mixBlendMode: "overlay",
                    opacity: overlay_opacity / 100,
                  }}
                />
              )}

              <div className="pointer-events-none absolute z-[2] flex h-full w-full flex-col items-start justify-between p-3 text-white">
                <div className="flex w-full flex-col gap-4">
                  <div className="flex items-center justify-between">
                    <div className="rounded-full bg-white/30 p-1 px-2 backdrop-blur-md">
                      <Image
                        src="/images/logos/text_w_logo_white.webp"
                        alt="GAIA Logo"
                        width={80}
                        height={24}
                        className="object-contain"
                      />
                    </div>
                    {house && (
                      <div className="rounded-full bg-white/20 p-1 px-3 font-serif text-xl font-light text-white/70 backdrop-blur-md">
                        {house}
                      </div>
                    )}
                  </div>

                  <div className="relative overflow-hidden rounded-2xl bg-black/20 p-4 backdrop-blur-md">
                    <div className="mb-2 font-serif text-2xl font-bold text-white">
                      {name}
                    </div>
                    <div className="mb-4 text-sm font-light text-white/80 italic">
                      {personality_phrase}
                    </div>
                    <p className="text-sm text-white/80">{user_bio}</p>
                  </div>
                </div>

                <div className="flex w-full items-center justify-between rounded-xl bg-black/20 p-3 backdrop-blur-md">
                  <div className="flex flex-col gap-1">
                    <span className="text-xs text-white/50">Member Since</span>
                    <span className="text-sm font-medium text-white/80">
                      {member_since}
                    </span>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-xs text-white/50">User ID</span>
                    <span className="text-sm font-medium text-white/80">
                      {account_number}
                    </span>
                  </div>
                </div>
              </div>

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
            </Tilt>
          )}
        </div>
      </div>
    </div>
  );
};
