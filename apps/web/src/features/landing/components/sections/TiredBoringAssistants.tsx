import Image from "next/image";

import LargeHeader from "../shared/LargeHeader";

const TOOL_ICONS = [
  // Ring 1 — close to center, larger, brighter
  {
    src: "/images/icons/gmail.svg",
    alt: "Gmail",
    size: 52,
    top: "30%",
    left: "63%",
    rotate: -6,
    opacity: 0.9,
    delay: 0,
  },
  {
    src: "/images/icons/googlecalendar.webp",
    alt: "Google Calendar",
    size: 50,
    top: "34%",
    left: "33%",
    rotate: 8,
    opacity: 0.9,
    delay: 0.6,
  },
  {
    src: "/images/icons/slack.svg",
    alt: "Slack",
    size: 48,
    top: "64%",
    left: "66%",
    rotate: -10,
    opacity: 0.85,
    delay: 1.2,
  },
  {
    src: "/images/icons/notion.webp",
    alt: "Notion",
    size: 50,
    top: "66%",
    left: "34%",
    rotate: 12,
    opacity: 0.85,
    delay: 1.8,
  },
  {
    src: "/images/icons/drive.webp",
    alt: "Google Drive",
    size: 46,
    top: "26%",
    left: "56%",
    rotate: 5,
    opacity: 0.85,
    delay: 0.3,
  },
  {
    src: "/images/icons/github.svg",
    alt: "GitHub",
    size: 48,
    top: "56%",
    left: "30%",
    rotate: -8,
    opacity: 0.85,
    delay: 0.9,
  },

  // Ring 2 — medium distance, medium size
  {
    src: "/images/icons/figma.svg",
    alt: "Figma",
    size: 42,
    top: "16%",
    left: "48%",
    rotate: 15,
    opacity: 0.7,
    delay: 2.0,
  },
  {
    src: "/images/icons/zoom.svg",
    alt: "Zoom",
    size: 38,
    top: "80%",
    left: "54%",
    rotate: -12,
    opacity: 0.7,
    delay: 2.5,
  },
  {
    src: "/images/icons/linear.svg",
    alt: "Linear",
    size: 40,
    top: "46%",
    left: "78%",
    rotate: 8,
    opacity: 0.7,
    delay: 1.4,
  },
  {
    src: "/images/icons/trello.svg",
    alt: "Trello",
    size: 38,
    top: "52%",
    left: "18%",
    rotate: -15,
    opacity: 0.7,
    delay: 1.7,
  },
  {
    src: "/images/icons/googledocs.webp",
    alt: "Google Docs",
    size: 42,
    top: "28%",
    left: "74%",
    rotate: -5,
    opacity: 0.75,
    delay: 0.7,
  },
  {
    src: "/images/icons/todoist.svg",
    alt: "Todoist",
    size: 36,
    top: "72%",
    left: "24%",
    rotate: 10,
    opacity: 0.7,
    delay: 2.2,
  },
  {
    src: "/images/icons/whatsapp.webp",
    alt: "WhatsApp",
    size: 40,
    top: "74%",
    left: "72%",
    rotate: -8,
    opacity: 0.7,
    delay: 1.6,
  },
  {
    src: "/images/icons/googlemeet.svg",
    alt: "Google Meet",
    size: 38,
    top: "30%",
    left: "22%",
    rotate: 12,
    opacity: 0.7,
    delay: 1.0,
  },

  // Ring 3 — far, smaller, more faded
  {
    src: "/images/icons/asana.svg",
    alt: "Asana",
    size: 32,
    top: "10%",
    left: "30%",
    rotate: -18,
    opacity: 0.5,
    delay: 3.0,
  },
  {
    src: "/images/icons/clickup.svg",
    alt: "ClickUp",
    size: 30,
    top: "12%",
    left: "70%",
    rotate: 12,
    opacity: 0.5,
    delay: 3.4,
  },
  {
    src: "/images/icons/linkedin.svg",
    alt: "LinkedIn",
    size: 32,
    top: "88%",
    left: "42%",
    rotate: -10,
    opacity: 0.5,
    delay: 2.8,
  },
  {
    src: "/images/icons/instagram.svg",
    alt: "Instagram",
    size: 30,
    top: "86%",
    left: "66%",
    rotate: 15,
    opacity: 0.45,
    delay: 3.2,
  },
  {
    src: "/images/icons/googlesheets.webp",
    alt: "Google Sheets",
    size: 34,
    top: "60%",
    left: "86%",
    rotate: -6,
    opacity: 0.55,
    delay: 2.4,
  },
  {
    src: "/images/icons/airtable.svg",
    alt: "Airtable",
    size: 30,
    top: "58%",
    left: "10%",
    rotate: 8,
    opacity: 0.5,
    delay: 2.6,
  },
  {
    src: "/images/icons/youtube.svg",
    alt: "YouTube",
    size: 32,
    top: "20%",
    left: "84%",
    rotate: -12,
    opacity: 0.5,
    delay: 3.6,
  },
  {
    src: "/images/icons/microsoft_teams.svg",
    alt: "Microsoft Teams",
    size: 34,
    top: "78%",
    left: "14%",
    rotate: 10,
    opacity: 0.5,
    delay: 3.3,
  },

  // Outermost — decorative whispers
  {
    src: "/images/icons/hubspot.svg",
    alt: "HubSpot",
    size: 26,
    top: "4%",
    left: "52%",
    rotate: -8,
    opacity: 0.35,
    delay: 4.0,
  },
  {
    src: "/images/icons/vercel.svg",
    alt: "Vercel",
    size: 26,
    top: "94%",
    left: "48%",
    rotate: 6,
    opacity: 0.35,
    delay: 4.2,
  },
];

export default function Tired() {
  return (
    <section className="relative flex flex-col items-center justify-center px-4 py-20 sm:py-32">
      <style>{`
        @keyframes tool-float {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-10px); }
        }
      `}</style>

      <LargeHeader
        chipText="Your tools, unified"
        headingText="One Assistant. All Your Tools."
        subHeadingText="Connected to everything you use, so it can act on your behalf."
        centered
      />

      {/* Icon constellation */}
      <div
        className="relative mt-12 aspect-square w-full max-w-2xl sm:mt-20"
        style={{
          background:
            "radial-gradient(circle at center, rgba(0, 187, 255, 0.05) 0%, transparent 60%)",
        }}
      >
        {/* GAIA Logo — center */}
        <div className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2">
          <Image
            src="/images/logos/logo.webp"
            alt="GAIA Logo"
            width={120}
            height={120}
            className="h-[90px] w-[90px] rounded-2xl bg-gradient-to-b from-zinc-800 to-zinc-950 p-3 shadow-[0px_0px_120px_50px_rgba(0,_187,_255,_0.2)] outline-1 outline-zinc-800 sm:h-[110px] sm:w-[110px] sm:rounded-3xl sm:p-4 lg:h-[120px] lg:w-[120px]"
          />
        </div>

        {/* Tool icons */}
        {TOOL_ICONS.map((icon) => (
          <div
            key={icon.alt}
            className="absolute"
            style={{
              top: icon.top,
              left: icon.left,
              opacity: icon.opacity,
              animation: `tool-float 5s ease-in-out ${icon.delay}s infinite`,
            }}
          >
            <Image
              src={icon.src}
              alt={icon.alt}
              width={icon.size}
              height={icon.size}
              className="rounded-xl"
              style={{
                width: icon.size,
                height: icon.size,
                transform: `rotate(${icon.rotate}deg)`,
              }}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
