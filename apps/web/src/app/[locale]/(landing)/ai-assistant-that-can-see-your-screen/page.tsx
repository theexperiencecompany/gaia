import type { Metadata } from "next";

import GuideLanding from "@/components/seo/GuideLanding";
import {
  type GuideLandingConfig,
  generateGuideMetadata,
} from "@/components/seo/guideLandingConfig";

const CONFIG: GuideLandingConfig = {
  path: "/ai-assistant-that-can-see-your-screen",
  title: "AI Assistant That Can See Your Screen",
  description:
    "Ask GAIA's desktop app about what is on your screen: it takes a screenshot, reads it and acts on it. Exactly what it captures, where it goes, and its limits.",
  keywords: [
    "ai assistant that can see your screen",
    "ai that can see my screen",
    "ai assistant screen reading",
    "ai screenshot assistant",
    "desktop ai assistant",
    "ai that looks at your screen",
    "ai assistant for mac and windows",
  ],
  breadcrumbName: "AI Assistant That Can See Your Screen",
  heading: "An AI assistant that can see your screen when you ask",
  answer:
    "GAIA's desktop app can look at your screen. In a desktop conversation, ask something like 'what does this error mean?' or 'turn this into a todo' and GAIA takes a screenshot of the display you are working on, reads it with an AI vision model, and answers or acts on what it sees. It is a single still image taken when the conversation needs it, not a live feed, and a thumbnail of every capture appears in the chat so you always know what was seen.",
  sections: [
    {
      heading: "What happens when GAIA looks at your screen",
      paragraphs: [
        "GAIA captures the whole display under your mouse cursor, which on a multi-monitor setup is the screen you are actually using, not always the primary one. It captures at native resolution, then sends the model a copy scaled to a size vision models read reliably.",
        "The chat shows a small thumbnail card of the capture, and the full image is saved to that conversation's workspace, so GAIA can refer back to it later in the same task.",
      ],
    },
    {
      heading: "Things people ask it to look at",
      paragraphs: [
        "Because GAIA is connected to your other tools, seeing the screen is usually the first step rather than the whole job:",
      ],
      bullets: [
        "Explain an error message or stack trace, then draft the bug report",
        "Summarize a long document or dashboard you have open",
        "Pull the date, time and attendees out of an invite and put it on your calendar",
        "Turn a to-do list in a screenshot, a whiteboard photo or a slide into tasks",
        "Read a chart and tell you what changed since last week",
      ],
    },
    {
      heading: "Mac, Windows and Linux",
      paragraphs: [
        "Screen capture works in the desktop app on macOS, Windows and Linux. On a Mac, the first capture needs Screen Recording permission in System Settings; if it is missing, GAIA tells you what to enable instead of guessing at an empty image.",
        "Open the assistant from anywhere with Cmd or Ctrl+Shift+G, or say 'Hey GAIA', and ask about what is in front of you without switching windows.",
      ],
    },
    {
      heading: "Privacy, plainly",
      paragraphs: [
        "GAIA only captures your screen inside a desktop-app conversation, and the web app and chat apps cannot trigger it. A capture is sent to the AI model provider to be read, the same way a message is. If you would rather keep everything on your own infrastructure, GAIA is source-available and can be self-hosted for personal, noncommercial use.",
      ],
    },
  ],
  limits: {
    heading: "What it can't do",
    items: [
      "It does not watch your screen continuously or record video. Each look is one screenshot.",
      "It cannot capture a single window on its own; it captures the whole display you are on.",
      "Seeing is not clicking. It cannot move your mouse or type into the app on screen.",
      "It is not available from the browser version of GAIA or from WhatsApp, Telegram and other chat apps.",
    ],
  },
  faqs: [
    {
      question: "Is there an AI assistant that can see my screen?",
      answer:
        "Yes. GAIA's desktop app takes a screenshot when you ask about something on screen, reads it with a vision model and answers or acts on it, such as drafting a reply or creating a calendar event from what it saw.",
    },
    {
      question: "Does GAIA record my screen all the time?",
      answer:
        "No. It takes one screenshot at a time, only inside a desktop conversation, and shows you a thumbnail of each one in the chat.",
    },
    {
      question: "Can it see my screen on Windows?",
      answer:
        "Yes. Screen capture works in the GAIA desktop app on Windows, macOS and Linux. macOS asks you to grant Screen Recording permission the first time.",
    },
    {
      question: "Can GAIA click on things it sees?",
      answer:
        "No. It can read what is on screen and act through your connected tools, open links and apps, and use the clipboard, but it does not control your mouse or keyboard.",
    },
  ],
  related: [
    {
      href: "/ai-assistant-that-uses-your-computer",
      label: "An AI assistant that uses your computer",
      description:
        "Clipboard, apps, links and browser tasks: everything else the desktop app can do.",
    },
    {
      href: "/learn/multimodal-ai",
      label: "What is multimodal AI?",
      description: "How models read images and text together.",
    },
    {
      href: "/ai-assistant-like-jarvis",
      label: "An AI assistant like Jarvis",
      description: "Voice, wake word and proactive workflows on your PC.",
    },
    {
      href: "/learn/screen-sharing",
      label: "Screen sharing",
      description:
        "How sharing your screen with people differs from showing it to AI.",
    },
  ],
};

export function generateMetadata(): Metadata {
  return generateGuideMetadata(CONFIG);
}

export default function AiAssistantSeeScreenPage() {
  return <GuideLanding config={CONFIG} />;
}
