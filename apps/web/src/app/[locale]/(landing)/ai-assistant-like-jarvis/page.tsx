import type { Metadata } from "next";

import GuideLanding from "@/components/seo/GuideLanding";
import {
  type GuideLandingConfig,
  generateGuideMetadata,
} from "@/components/seo/guideLandingConfig";

const CONFIG: GuideLandingConfig = {
  path: "/ai-assistant-like-jarvis",
  title: "AI Assistant Like Jarvis: What Is Real Today",
  description:
    "The parts of Jarvis you can actually have: an assistant that acts on its own, talks back, lives on your PC and works across your tools. And what it can't do.",
  keywords: [
    "ai assistant like jarvis",
    "ai assistant like jarvis for pc",
    "ai assistant like jarvis reddit",
    "free ai assistant like jarvis",
    "jarvis ai assistant",
    "real life jarvis",
    "jarvis for windows",
    "voice ai assistant for pc",
  ],
  breadcrumbName: "AI Assistant Like Jarvis",
  heading: "An AI assistant like Jarvis, minus the movie magic",
  answer:
    "The closest thing to Jarvis you can use today is an assistant that does four things: acts before you ask, talks with you out loud, lives on your computer, and works inside your real tools. GAIA does all four. It runs workflows on a schedule or when an email arrives, holds voice conversations, sits on your desktop behind a hotkey or a 'Hey GAIA' wake word, and handles email, calendar and tasks across the apps you connect. It will not fly a suit or run your house, and this page is clear about the rest of what it can't do.",
  sections: [
    {
      heading: "What made Jarvis feel real",
      paragraphs: [
        "Strip away the holograms and Jarvis is a short list of behaviours. It noticed things without being asked. It spoke and listened naturally. It remembered context. And it did the work instead of describing how to do it. Most AI assistants manage one of these. Chatbots answer well but wait for a prompt; voice assistants listen but can only set timers and play music.",
        "GAIA is built around that list, which is why people looking for a real-life Jarvis end up comparing it with ChatGPT, Siri and Google Assistant.",
      ],
    },
    {
      heading: "It acts before you ask",
      paragraphs: [
        "GAIA's workflows run on their own: on a schedule, or when something happens in a connected tool such as a new Gmail message, a calendar event, a GitHub issue, a Slack message or a Linear ticket. A workflow can triage overnight email into a summary waiting for you at 8am, or turn every email that asks you for something into a todo. Results land in the app or in your chat app of choice, so GAIA reaches you first.",
      ],
    },
    {
      heading: "You can talk to it",
      paragraphs: [
        "Voice mode in the web and desktop app is a real spoken conversation, not dictation. Your speech is transcribed by Deepgram and GAIA answers out loud with an ElevenLabs voice, with the same tools and memory as text chat. On WhatsApp and Telegram you can send a voice note instead, and GAIA turns it into text and acts on it.",
      ],
    },
    {
      heading: "An AI assistant like Jarvis for PC",
      paragraphs: [
        "GAIA's desktop app runs on Windows, macOS and Linux. Press Cmd or Ctrl+Shift+G anywhere to open the assistant popup, or say 'Hey GAIA'. The wake word is detected on your device, so no audio leaves the machine until you start talking to GAIA.",
        "From a desktop conversation GAIA can also use your computer in small, concrete ways:",
      ],
      bullets: [
        "Take a screenshot of the screen you are on and tell you what it sees",
        "Read and write your clipboard",
        "Open a link in your default browser",
        "Open an app by name and list your open windows (macOS only, for now)",
        "Run a browser task in a cloud browser to fill in a form or look something up",
      ],
    },
    {
      heading: "It works across your tools and remembers you",
      paragraphs: [
        "Connect Gmail or Outlook, Google Calendar, Slack, Notion, GitHub, Linear, Todoist and more, and GAIA works inside them: drafting and sending replies, creating and moving events, filing tasks. Its long-term memory keeps your preferences and the people around you, so the context builds up the way it did for Tony Stark.",
      ],
    },
    {
      heading: "Is there a free AI assistant like Jarvis?",
      paragraphs: [
        "Not from GAIA's hosted service, which is a paid subscription. The code is source-available under the PolyForm Noncommercial license, so you can self-host GAIA for personal, noncommercial use on your own hardware and pay only for the server and the AI model you plug in.",
      ],
    },
  ],
  limits: {
    heading: "Where GAIA is not Jarvis",
    items: [
      "It does not control smart-home devices, cars or anything physical.",
      "It cannot drive arbitrary desktop apps with your mouse and keyboard; its computer actions are the specific ones listed above.",
      "It does not make or take phone calls, and it does not control your phone.",
      "It needs an internet connection. There is no offline mode.",
      "It does not watch your screen continuously. It takes a screenshot when a conversation needs one.",
    ],
  },
  faqs: [
    {
      question: "What is the closest real AI assistant to Jarvis?",
      answer:
        "Look for one that is proactive, conversational, on your computer and connected to your tools. GAIA covers all four: scheduled and triggered workflows, voice conversations, a desktop app with a hotkey and wake word, and actions across email, calendar and task apps.",
    },
    {
      question: "Is there an AI assistant like Jarvis for Windows?",
      answer:
        "Yes. GAIA's desktop app runs on Windows, with the same assistant popup, wake word and voice mode as on macOS. Opening apps by name and listing windows are macOS-only for now; screenshots, clipboard and links work on every platform.",
    },
    {
      question: "Can I talk to GAIA like Jarvis?",
      answer:
        "Yes. Voice mode is a back-and-forth spoken conversation in the web and desktop apps, and on the desktop you can start it hands-free with 'Hey GAIA'.",
    },
    {
      question: "Can GAIA control my whole computer?",
      answer:
        "No. It can take screenshots, use the clipboard, open links, open apps and list windows, and it can run tasks in a cloud browser. It does not move your mouse or type into other apps for you.",
    },
  ],
  related: [
    {
      href: "/ai-assistant-that-uses-your-computer",
      label: "An AI assistant that uses your computer",
      description:
        "Exactly which desktop and browser actions GAIA can take, and which it can't.",
    },
    {
      href: "/learn/proactive-ai",
      label: "What is proactive AI?",
      description: "Why assistants that act first beat ones that wait.",
    },
    {
      href: "/compare/siri",
      label: "GAIA vs Siri",
      description:
        "A voice assistant on your phone versus one that runs your work.",
    },
    {
      href: "/best-ai-assistant",
      label: "Best AI assistant",
      description:
        "How GAIA ranks against ChatGPT, Claude, Gemini and the rest.",
    },
  ],
};

export function generateMetadata(): Metadata {
  return generateGuideMetadata(CONFIG);
}

export default function AiAssistantLikeJarvisPage() {
  return <GuideLanding config={CONFIG} />;
}
