"use client";

import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { RaisedButton } from "@/components/ui/raised-button";
import { ArrowRight02Icon } from "@/icons";
import LargeHeader from "../shared/LargeHeader";

const TOOL_ICONS = [
  // Ring 1 — core tools, close to center, larger, sharp (no blur)
  {
    src: "/images/icons/macos/mail.png",
    alt: "Mail",
    size: 66,
    top: "27%",
    left: "76%",
    rotate: -6,
    opacity: 0.92,
    blur: 0,
    delay: 0,
  },
  {
    src: "/images/icons/macos/calendar.webp",
    alt: "Calendar",
    size: 64,
    top: "33%",
    left: "21%",
    rotate: 8,
    opacity: 0.92,
    blur: 0,
    delay: 0.5,
  },
  {
    src: "/images/icons/macos/slack.webp",
    alt: "Slack",
    size: 60,
    top: "69%",
    left: "73%",
    rotate: -10,
    opacity: 0.88,
    blur: 0,
    delay: 1.0,
  },
  {
    src: "/images/icons/macos/notion.webp",
    alt: "Notion",
    size: 62,
    top: "71%",
    left: "23%",
    rotate: 12,
    opacity: 0.88,
    blur: 0,
    delay: 1.5,
  },
  {
    src: "/images/icons/macos/drive.webp",
    alt: "Google Drive",
    size: 58,
    top: "24%",
    left: "41%",
    rotate: 5,
    opacity: 0.88,
    blur: 0,
    delay: 0.3,
  },
  {
    src: "/images/icons/macos/github.webp",
    alt: "GitHub",
    size: 60,
    top: "70%",
    left: "41%",
    rotate: -8,
    opacity: 0.88,
    blur: 0,
    delay: 0.8,
  },
  {
    src: "/images/icons/macos/macos_weather.png",
    alt: "Weather",
    size: 62,
    top: "31%",
    left: "62%",
    rotate: 4,
    opacity: 0.9,
    blur: 0,
    delay: 0.2,
  },

  // Ring 2 — secondary tools, slight blur (0.4–0.6px)
  {
    src: "/images/icons/macos/figma.webp",
    alt: "Figma",
    size: 42,
    top: "10%",
    left: "53%",
    rotate: 15,
    opacity: 0.72,
    blur: 0.4,
    delay: 1.8,
  },
  {
    src: "/images/icons/macos/zoom.webp",
    alt: "Zoom",
    size: 40,
    top: "88%",
    left: "57%",
    rotate: -12,
    opacity: 0.72,
    blur: 0.5,
    delay: 2.3,
  },
  {
    src: "/images/icons/macos/linear.webp",
    alt: "Linear",
    size: 42,
    top: "41%",
    left: "89%",
    rotate: 8,
    opacity: 0.72,
    blur: 0.5,
    delay: 1.3,
  },
  {
    src: "/images/icons/macos/trello.webp",
    alt: "Trello",
    size: 40,
    top: "53%",
    left: "5%",
    rotate: -15,
    opacity: 0.72,
    blur: 0.5,
    delay: 1.6,
  },
  {
    src: "/images/icons/googledocs.webp",
    alt: "Google Docs",
    size: 42,
    top: "14%",
    left: "83%",
    rotate: -5,
    opacity: 0.75,
    blur: 0.4,
    delay: 0.6,
  },
  {
    src: "/images/icons/macos/todoist.webp",
    alt: "Todoist",
    size: 38,
    top: "83%",
    left: "14%",
    rotate: 10,
    opacity: 0.72,
    blur: 0.5,
    delay: 2.0,
  },
  {
    src: "/images/icons/macos/whatsapp.webp",
    alt: "WhatsApp",
    size: 42,
    top: "79%",
    left: "82%",
    rotate: -8,
    opacity: 0.72,
    blur: 0.4,
    delay: 1.4,
  },
  {
    src: "/images/icons/macos/notion_calendar.webp",
    alt: "Notion Calendar",
    size: 40,
    top: "17%",
    left: "12%",
    rotate: 12,
    opacity: 0.72,
    blur: 0.4,
    delay: 0.9,
  },
  {
    src: "/images/icons/macos/discord.webp",
    alt: "Discord",
    size: 40,
    top: "55%",
    left: "81%",
    rotate: 6,
    opacity: 0.7,
    blur: 0.3,
    delay: 1.1,
  },

  // Ring 3 — outer tools, more blur (0.8–1px)
  {
    src: "/images/icons/macos/asana.webp",
    alt: "Asana",
    size: 34,
    top: "2%",
    left: "19%",
    rotate: -18,
    opacity: 0.52,
    blur: 0.8,
    delay: 2.8,
    hideMobile: true,
  },
  {
    src: "/images/icons/macos/clickup.webp",
    alt: "ClickUp",
    size: 32,
    top: "3%",
    left: "77%",
    rotate: 12,
    opacity: 0.52,
    blur: 0.9,
    delay: 3.2,
    hideMobile: true,
  },
  {
    src: "/images/icons/linkedin.svg",
    alt: "LinkedIn",
    size: 34,
    top: "95%",
    left: "31%",
    rotate: -10,
    opacity: 0.52,
    blur: 0.8,
    delay: 2.6,
    hideMobile: true,
  },
  {
    src: "/images/icons/macos/instagram.webp",
    alt: "Instagram",
    size: 32,
    top: "93%",
    left: "75%",
    rotate: 15,
    opacity: 0.48,
    blur: 0.9,
    delay: 3.0,
    hideMobile: true,
  },
  {
    src: "/images/icons/googlesheets.webp",
    alt: "Google Sheets",
    size: 36,
    top: "55%",
    left: "96%",
    rotate: -6,
    opacity: 0.55,
    blur: 0.8,
    delay: 2.2,
    hideMobile: true,
  },
  {
    src: "/images/icons/macos/airtable.webp",
    alt: "Airtable",
    size: 32,
    top: "71%",
    left: "0%",
    rotate: 8,
    opacity: 0.52,
    blur: 0.9,
    delay: 2.4,
    hideMobile: true,
  },
  {
    src: "/images/icons/macos/youtube.webp",
    alt: "YouTube",
    size: 34,
    top: "7%",
    left: "93%",
    rotate: -12,
    opacity: 0.52,
    blur: 0.8,
    delay: 3.4,
    hideMobile: true,
  },
  {
    src: "/images/icons/macos/teams.webp",
    alt: "Microsoft Teams",
    size: 36,
    top: "92%",
    left: "4%",
    rotate: 10,
    opacity: 0.52,
    blur: 0.8,
    delay: 3.1,
    hideMobile: true,
  },

  // Outermost — decorative, most blur (1.5px)
  {
    src: "/images/icons/macos/hubspot.webp",
    alt: "HubSpot",
    size: 28,
    top: "2%",
    left: "49%",
    rotate: -8,
    opacity: 0.38,
    blur: 1.5,
    delay: 3.8,
    hideMobile: true,
  },
];

export default function Tired() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hasAnimated, setHasAnimated] = useState(false);
  const [isLeaving, setIsLeaving] = useState(false);

  // Use refs so observers don't re-create on state changes
  const hasAnimatedRef = useRef(false);
  const isLeavingRef = useRef(false);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 640);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  useEffect(() => {
    hasAnimatedRef.current = hasAnimated;
    isLeavingRef.current = isLeaving;
  }, [hasAnimated, isLeaving]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Scatter-in observer
    const enterObserver = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !hasAnimatedRef.current) {
          setHasAnimated(true);
          setIsLeaving(false);
        }
      },
      { threshold: 0.5 },
    );

    // Gather-back observer — triggers when section is mostly out of view
    const leaveObserver = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting && hasAnimatedRef.current) {
          setIsLeaving(true);
          // Reset so scatter plays again on re-entry
          setTimeout(() => {
            setHasAnimated(false);
          }, 800);
        }
        if (entry.isIntersecting && isLeavingRef.current) {
          setIsLeaving(false);
          setHasAnimated(true);
        }
      },
      { threshold: 0.5 },
    );

    enterObserver.observe(el);
    leaveObserver.observe(el);
    return () => {
      enterObserver.disconnect();
      leaveObserver.disconnect();
    };
  }, []);

  return (
    <section className="relative flex flex-col items-center justify-center px-4 sm:px-6 py-20 sm:py-32">
      <style>{`
        @keyframes tool-float {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-10px); }
        }
        @keyframes logo-pulse {
          0%, 100% { box-shadow: 0px 0px 120px 50px rgba(0, 187, 255, 0.2); }
          50% { box-shadow: 0px 0px 140px 60px rgba(0, 187, 255, 0.35); }
        }
        @keyframes tool-scatter {
          0% {
            top: 50%;
            left: 50%;
            opacity: 0;
            transform: translate(-50%, -50%) scale(0.3);
          }
          60% {
            opacity: 1;
            transform: translate(0, 0) scale(1.05);
          }
          100% {
            top: var(--end-top);
            left: var(--end-left);
            opacity: var(--end-opacity);
            transform: translate(0, 0) scale(1);
          }
        }
        @keyframes tool-gather {
          0% {
            top: var(--end-top);
            left: var(--end-left);
            opacity: var(--end-opacity);
            transform: translate(0, 0) scale(1);
          }
          100% {
            top: 50%;
            left: 50%;
            opacity: 0;
            transform: translate(-50%, -50%) scale(0.3);
          }
        }
        .tool-icon-btn {
          cursor: pointer;
          transition: transform 0.15s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .tool-icon-btn:hover {
          transform: scale(1.12);
        }
        .tool-icon-btn:active {
          transform: scale(0.88);
        }
      `}</style>

      <LargeHeader
        chipText="Stop context-switching"
        headingText="Every tool. One assistant."
        subHeadingText="Plug in your stack once. GAIA takes action across Gmail, Slack, Notion, Calendar and 100+ more."
        centered
      />

      {/* Icon constellation */}
      <div
        ref={containerRef}
        className="relative mt-12 aspect-square w-full max-w-2xl sm:mt-20 overflow-hidden sm:overflow-visible"
        style={{
          background:
            "radial-gradient(circle at center, rgba(0, 187, 255, 0.05) 0%, transparent 60%)",
        }}
      >
        {/* GAIA Logo — center */}
        <div className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2">
          <Image
            src="/images/logos/macos.png"
            alt="GAIA Logo"
            width={120}
            height={120}
            loading="lazy"
            className="rounded-[31px]"
            style={{
              animation: hasAnimated
                ? "logo-pulse 4s ease-in-out infinite"
                : "none",
              boxShadow: "0px 0px 120px 50px rgba(0, 187, 255, 0.2)",
            }}
          />
        </div>

        {/* Tool icons — outside the bg container, positioned in the same relative space */}
        {TOOL_ICONS.map((icon) => {
          if (isMobile && (icon as { hideMobile?: boolean }).hideMobile)
            return null;
          const displaySize = isMobile
            ? Math.round(icon.size * 0.7)
            : icon.size;
          const scatterDuration = 0.8 + icon.delay * 0.15;
          const scatterDelay = icon.delay * 0.12;
          const floatDelay = scatterDuration + scatterDelay;
          // Reverse stagger for gather — outer icons collapse first
          const maxDelay = 3.8 * 0.12;
          const gatherDelay = maxDelay - scatterDelay;

          return (
            <div
              key={icon.alt}
              className="absolute"
              style={
                isLeaving
                  ? ({
                      "--end-top": icon.top,
                      "--end-left": icon.left,
                      "--end-opacity": String(icon.opacity),
                      top: "50%",
                      left: "50%",
                      opacity: 0,
                      transform: "translate(-50%, -50%) scale(0.3)",
                      animation: `tool-gather 0.6s cubic-bezier(0.55, 0, 1, 0.45) ${gatherDelay}s both`,
                    } as React.CSSProperties)
                  : hasAnimated
                    ? ({
                        "--end-top": icon.top,
                        "--end-left": icon.left,
                        "--end-opacity": String(icon.opacity),
                        top: icon.top,
                        left: icon.left,
                        opacity: icon.opacity,
                        filter:
                          icon.blur > 0 ? `blur(${icon.blur}px)` : undefined,
                        animation: `tool-scatter ${scatterDuration}s cubic-bezier(0.34, 1.56, 0.64, 1) ${scatterDelay}s backwards, tool-float 5s ease-in-out ${floatDelay}s infinite`,
                      } as React.CSSProperties)
                    : {
                        top: "50%",
                        left: "50%",
                        opacity: 0,
                        transform: "translate(-50%, -50%) scale(0.3)",
                      }
              }
            >
              <Tooltip
                content={icon.alt}
                placement="top"
                delay={200}
                closeDelay={0}
                classNames={{
                  content:
                    "bg-zinc-900 text-white text-xs px-2.5 py-1 rounded-lg",
                }}
              >
                <div className="tool-icon-btn">
                  <Image
                    src={icon.src}
                    alt={icon.alt}
                    width={displaySize}
                    height={displaySize}
                    loading="lazy"
                    className="rounded-xl object-contain"
                    style={{
                      width: displaySize,
                      height: displaySize,
                      transform: `rotate(${icon.rotate}deg)`,
                    }}
                  />
                </div>
              </Tooltip>
            </div>
          );
        })}
      </div>

      {/* CTA */}
      <Link href="/integrations" className="mt-8 sm:mt-12">
        <RaisedButton color="#00bbff" className="text-black!">
          See All Integrations
          <ArrowRight02Icon width={20} height={20} />
        </RaisedButton>
      </Link>
    </section>
  );
}
