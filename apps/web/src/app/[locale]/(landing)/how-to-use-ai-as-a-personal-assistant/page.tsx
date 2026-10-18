import type { Metadata } from "next";

import GuideLanding from "@/components/seo/GuideLanding";
import {
  type GuideLandingConfig,
  generateGuideMetadata,
} from "@/components/seo/guideLandingConfig";

const CONFIG: GuideLandingConfig = {
  path: "/how-to-use-ai-as-a-personal-assistant",
  title: "How to Use AI as a Personal Assistant: Setup Guide",
  description:
    "Yes, AI can be your personal assistant once it can reach your email, calendar and tasks. A step-by-step setup in GAIA, and what to hand over first.",
  keywords: [
    "how to use ai as a personal assistant",
    "how to set up ai as a personal assistant",
    "can ai be my personal assistant",
    "ai as a personal assistant",
    "use chatgpt as a personal assistant",
    "set up an ai assistant",
    "ai personal assistant setup",
  ],
  breadcrumbName: "How to Use AI as a Personal Assistant",
  heading: "How to use AI as a personal assistant",
  answer:
    "AI can be your personal assistant once it can reach the places your work lives and is allowed to act there. A chatbot that only sees what you paste in is a writing tool; an assistant connected to your email, calendar and task list can triage, schedule and follow up for you. The setup below takes you from a new GAIA account to an assistant that handles recurring work on its own: connect your tools, let it learn about you, delegate a few real tasks, then turn the repeats into workflows.",
  sections: [
    {
      heading: "Can AI really be your personal assistant?",
      paragraphs: [
        "For the administrative half of the job, yes. An AI assistant is good at the work that is tedious rather than hard: reading every email so you only see the ones that matter, finding a time that suits four calendars, drafting the polite reply, remembering to chase the invoice. It is fast, it does not get bored, and it never forgets to check.",
        "What it needs from you is access and context. Access means connecting your accounts so it can read and act. Context means telling it what matters, which a good assistant then remembers so you do not have to repeat yourself.",
      ],
    },
    {
      heading: "What to hand over first",
      paragraphs: [
        "Start with the jobs where a mistake is cheap and the time saved is obvious. These four cover most people's week:",
      ],
      bullets: [
        "Email triage: a summary of what came in and which threads need you",
        "Scheduling: find a slot, send the invite, move a meeting when plans change",
        "Follow-ups: turn 'I'll get back to you' in an email into a todo with a date",
        "Daily planning: a morning rundown of meetings, deadlines and open todos",
      ],
    },
    {
      heading: "What to keep for yourself",
      paragraphs: [
        "Keep the judgement calls: difficult conversations, decisions with real money or reputation attached, anything where the tone has to be exactly yours. Let GAIA draft those, then send them yourself. As trust builds, widen what it does on its own.",
      ],
    },
  ],
  steps: {
    heading: "Set up GAIA as your personal assistant",
    items: [
      {
        name: "Create an account and tell GAIA about your work",
        text: "Sign up at heygaia.io. Onboarding asks what you do and what you want off your plate first, with up to three picks, so the first suggestions fit your job.",
      },
      {
        name: "Choose a chat app to reach it from your phone",
        text: "After you subscribe, pick Telegram, WhatsApp or iMessage and the first message you send links your account. You can skip this and use the web or desktop app instead.",
      },
      {
        name: "Connect your email, calendar and task app",
        text: "Open Integrations and connect Gmail or Outlook, Google Calendar and the tool you keep todos in, such as Todoist, Linear or Asana. GAIA can only act where it is connected.",
      },
      {
        name: "Tell it the things a new assistant would ask",
        text: "Mention your working hours, who your key people are and how you like replies written. GAIA keeps these as memories, which you can review and edit under Settings, then Memory.",
      },
      {
        name: "Delegate three real tasks",
        text: "Ask in plain language: summarize what came in overnight, find 30 minutes with Sam next week and send the invite, add a todo to renew the domain on Friday.",
      },
      {
        name: "Turn the repeats into workflows",
        text: "When you ask for the same thing twice, make it a workflow. Workflows run on a schedule, such as every weekday at 8am, or when something happens, such as a new email or calendar event.",
      },
      {
        name: "Decide how much it may do without asking",
        text: "In settings, choose an approval mode: Allow always, Always ask, which checks before GAIA sends, deletes or posts, or Auto, which runs what you clearly asked for and checks when it is unclear.",
      },
      {
        name: "Put it one keystroke away",
        text: "Install the desktop app for Windows, macOS or Linux. Cmd or Ctrl+Shift+G, or saying 'Hey GAIA', opens the assistant over whatever you are doing.",
      },
    ],
  },
  faqs: [
    {
      question: "Can I use ChatGPT as a personal assistant?",
      answer:
        "For writing and answering questions, yes. As a personal assistant it is limited by what it can reach: unless it is connected to your email, calendar and task tools and allowed to act, you still do the doing. GAIA is built around those connections, and runs workflows on its own instead of waiting for a prompt.",
    },
    {
      question: "How long does it take to set up an AI personal assistant?",
      answer:
        "Signing up and connecting your email and calendar is a matter of minutes. The assistant gets more useful over the first weeks as it learns your preferences and you turn repeated requests into workflows.",
    },
    {
      question: "Is it safe to give an AI assistant access to my email?",
      answer:
        "Look for clear controls. In GAIA you choose what to connect, you can make it ask before it sends, deletes or posts anything, and you can see and delete everything it remembers. Content from your accounts is processed by AI model providers to generate replies, as described in the privacy policy.",
    },
    {
      question: "Do I need to be technical?",
      answer:
        "No. Everything above is done in plain language and settings screens. Self-hosting GAIA on your own server is the only part that needs technical skill, and it is optional.",
    },
  ],
  related: [
    {
      href: "/ai-assistant-whatsapp-telegram-imessage",
      label: "Use GAIA from WhatsApp, Telegram or iMessage",
      description: "Run your assistant from the chat app you already use.",
    },
    {
      href: "/learn/ai-assistant",
      label: "What is an AI assistant?",
      description: "The definition, and how assistants differ from chatbots.",
    },
    {
      href: "/learn/workflow-automation",
      label: "Workflow automation",
      description: "How recurring work becomes something that runs itself.",
    },
    {
      href: "/use-cases",
      label: "Workflow ideas",
      description: "Ready-made workflows you can copy into your account.",
    },
  ],
};

export function generateMetadata(): Metadata {
  return generateGuideMetadata(CONFIG);
}

export default function HowToUseAiAsPersonalAssistantPage() {
  return <GuideLanding config={CONFIG} />;
}
