import { StyledHoloCard } from "@/app/styles/holo-card.styles";
import { Calendar03Icon } from "@/components/shared";
import Image from "next/image";
import React, { useRef, useState } from "react";
import Tilt from "react-parallax-tilt";

interface Props {
  children?: React.ReactNode;
  url: string;
  height?: number;
  width?: number;
  showSparkles?: boolean;
  overlayColor?: string;
  overlayOpacity?: number;
  houseName?: string;
  userName?: string;
  userTagline?: string;
  userId?: string;
  joinDate?: string;
  userBio?: string;
  userSkills?: string[];
  userRole?: string;
}

export const HoloCard = ({
  children,
  url,
  height,
  width,
  showSparkles,
  overlayColor,
  overlayOpacity = 40,
  houseName,
  userName = "Aryan Randeriya",
  userTagline = "Curious Adventurer",
  userId = "#11231",
  joinDate = "Nov 20, 2024",
  userBio = "A passionate developer exploring the intersection of AI and human experience. Building the future, one line of code at a time.",
  userSkills = ["Full-Stack Development", "AI/ML", "Product Design", "DevOps"],
  userRole = "Senior Developer",
}: Props) => {
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

  const handleCardClick = () => {
    setIsFlipped(!isFlipped);
  };

  const handleOnMouseOver = (event: any) => {
    setAnimated(false);
    setHover(true);

    const card = ref.current;

    const l =
      event.type === "touchmove"
        ? event.touches[0].clientX
        : event.nativeEvent.offsetX;

    const t =
      event.type === "touchmove"
        ? event.touches[0].clientY
        : event.nativeEvent.offsetY;

    const h = card ? card.clientHeight : 0;
    const w = card ? card.clientWidth : 0;

    var px = Math.abs(Math.floor((100 / w) * l) - 100);
    var py = Math.abs(Math.floor((100 / h) * t) - 100);

    var lp = 50 + (px - 50) / 1.5;
    var tp = 50 + (py - 50) / 1.5;

    setActiveBackgroundPosition({ lp, tp });
  };

  const handleOnMouseOut = () => {
    setHover(false);
    setAnimated(true);
    setActiveRotation({ x: 0, y: 0 });
  };

  return (
    <div
      className="perspective-1000 cursor-pointer!"
      onClick={handleCardClick}
      style={{ perspective: "1000px" }}
    >
      <div
        className="relative transition-transform duration-700"
        style={{
          transformStyle: "preserve-3d",
          transform: isFlipped ? "rotateY(180deg)" : "rotateY(0deg)",
          height: `${height ?? 446}px`,
          width: `${width ?? 320}px`,
        }}
      >
        {/* Front Side */}
        <div
          className="absolute inset-0"
          style={{
            backfaceVisibility: "hidden",
            WebkitBackfaceVisibility: "hidden",
          }}
        >
          <Tilt className="relative h-full w-full overflow-hidden rounded-2xl p-0! shadow-xl">
            {overlayColor && (
              <div
                className="pointer-events-none absolute inset-0 z-[1]"
                style={{
                  background: overlayColor,
                  mixBlendMode: "overlay",
                  opacity: overlayOpacity / 100,
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
                {houseName && (
                  <div className="rounded-full bg-white/20 p-1 px-4 font-serif text-xl font-light text-white/70 backdrop-blur-md">
                    {houseName}
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
                  {userName}
                </div>
                <div className="mb-10 font-light text-white italic">
                  {userTagline}
                </div>

                <div className="flex w-full items-center justify-between">
                  <div className="flex flex-col items-start gap-1">
                    <span className="text-sm text-white/80">User {userId}</span>
                    <span className="text-xs text-white/50">{joinDate}</span>
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
              url={url}
              ref={ref}
              active={hover}
              animated={animated}
              activeRotation={activeRotation}
              activeBackgroundPosition={activeBackgroundPosition}
              onMouseMove={handleOnMouseOver}
              onTouchMove={handleOnMouseOver}
              onMouseOut={handleOnMouseOut}
              height={height ?? 446}
              width={width ?? 320}
              showSparkles={showSparkles ?? true}
            >
              {children}
            </StyledHoloCard>
          </Tilt>
        </div>

        {/* Back Side */}
        <div
          className="absolute inset-0"
          style={{
            backfaceVisibility: "hidden",
            WebkitBackfaceVisibility: "hidden",
            transform: "rotateY(180deg)",
          }}
        >
          <Tilt className="relative h-full w-full overflow-hidden rounded-2xl p-0! shadow-xl">
            {overlayColor && (
              <div
                className="pointer-events-none absolute inset-0 z-[1]"
                style={{
                  background: overlayColor,
                  mixBlendMode: "overlay",
                  opacity: overlayOpacity / 100,
                }}
              />
            )}

            <div className="pointer-events-none absolute z-[2] flex h-full w-full flex-col items-start justify-between p-6 text-white">
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
                  {houseName && (
                    <div className="rounded-full bg-white/20 p-1 px-3 text-sm font-light text-white/70 backdrop-blur-md">
                      {houseName}
                    </div>
                  )}
                </div>

                <div className="relative overflow-hidden rounded-2xl bg-black/20 p-4 backdrop-blur-md">
                  <div className="mb-2 font-serif text-2xl font-bold text-white">
                    {userName}
                  </div>
                  <div className="mb-4 text-sm font-light text-white/80 italic">
                    {userTagline}
                  </div>
                  <p className="text-sm leading-relaxed text-white/70">
                    {userBio}
                  </p>
                </div>
              </div>

              <div className="flex w-full items-center justify-between rounded-xl bg-black/20 p-3 backdrop-blur-md">
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-white/50">Member Since</span>
                  <span className="text-sm font-medium text-white/80">
                    {joinDate}
                  </span>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="text-xs text-white/50">User ID</span>
                  <span className="text-sm font-medium text-white/80">
                    {userId}
                  </span>
                </div>
              </div>
            </div>

            <StyledHoloCard
              url={url}
              ref={ref}
              active={hover}
              animated={animated}
              activeRotation={activeRotation}
              activeBackgroundPosition={activeBackgroundPosition}
              onMouseMove={handleOnMouseOver}
              onTouchMove={handleOnMouseOver}
              onMouseOut={handleOnMouseOut}
              height={height ?? 446}
              width={width ?? 320}
              showSparkles={showSparkles ?? true}
            >
              {children}
            </StyledHoloCard>
          </Tilt>
        </div>
      </div>
    </div>
  );
};
