import type { Metadata } from "next";
import Link from "next/link";

import BestAssistantHub from "@/components/seo/BestAssistantHub";
import {
  type BestHubConfig,
  generateBestHubMetadata,
} from "@/components/seo/bestAssistantHubConfig";
import { CURRENT_YEAR_TOKEN } from "@/lib/feature-data";

// GAIA excluded (it is row #1, "our pick"). Every slug must exist in
// public/data/comparisons/{slug}.json. Missing slugs throw at render.
// Hoisted so the "Top N" copy below always equals GAIA + ranked runners-up.
const RANKED_SLUGS = [
  "chatgpt",
  "claude",
  "gemini",
  "copilot",
  "perplexity",
  "grok",
  "deepseek",
  "google-assistant",
  "lindy-ai",
  "cursor-ai",
  "notion-ai",
] as const;

const PICK_COUNT = RANKED_SLUGS.length + 1;

const LINK_CLASS =
  "text-zinc-200 underline underline-offset-2 hover:text-white";

const CONFIG: BestHubConfig = {
  pagePath: "/best-ai-assistant",
  pageTitle: `Best AI Assistant for Personal Use and Work in ${CURRENT_YEAR_TOKEN}`,
  pageDescription: `${PICK_COUNT} AI assistants ranked by how much real work they take off your plate, for personal use and work, with honest picks for iPhone and Android.`,
  keywords: [
    "best AI assistant",
    "best ai assistant for personal use",
    "best ai assistant for work",
    "best ai assistant for iphone",
    "best ai assistant for android",
    "best ChatGPT alternative",
    "ChatGPT alternative",
    "Claude alternative",
    "Gemini alternative",
    "AI assistant comparison",
    `best AI assistant ${CURRENT_YEAR_TOKEN}`,
    "proactive AI assistant",
  ],
  breadcrumbName: "Best AI Assistant",
  heading: `Best AI Assistant: Our Top ${PICK_COUNT} for ${CURRENT_YEAR_TOKEN}`,
  subheading:
    "Ranked by how much real work each assistant takes off your plate, not by hype. GAIA is our pick. The rest are described fairly, with links to our full comparisons so you can check our work.",
  intro: (
    <>
      <p>
        We built GAIA because chatbots wait. You prompt, they answer, and the
        work of your day still sits in your inbox. A great assistant should do
        the opposite: notice what needs doing and handle it before you ask.
      </p>
      <p>
        That is the test behind this ranking. We looked at the AI assistants
        people actually use, from ChatGPT and Claude to Gemini, Copilot, and
        Perplexity, and asked one question: how much of your real work does it
        take off your plate? Tools that only answer rank below tools that act.
      </p>
      <p>
        GAIA is our pick, and yes, we make it. It sits at number one for one
        reason: it works inside your email, calendar, and tasks across your
        tools and acts on its own, where most of this list waits for a prompt.
        Every competitor below is described in its own words from our published
        comparisons, each linked so you can verify every claim.
      </p>
    </>
  ),
  tableAriaLabel: `Top ${PICK_COUNT} AI assistants ranked`,
  tableTitle: `The top ${PICK_COUNT} at a glance`,
  gaiaBestFor: "Proactive daily work",
  gaiaTake:
    "Monitors email, calendar, and tasks across your tools and acts before you ask.",
  pickBody:
    "GAIA is a proactive personal AI assistant. It runs workflows on a schedule or when something happens in your tools, and works inside Gmail, Outlook, Google Calendar, Slack, Notion, GitHub, Todoist, Linear and more. It remembers your preferences across every conversation, and you can reach it from the web, the desktop app or WhatsApp, Telegram and iMessage. Its code is source-available under the PolyForm Noncommercial license, so you can read exactly how your data is handled.",
  pickCompareHref: "/compare/chatgpt",
  pickCompareLabel: "See GAIA vs ChatGPT head-to-head",
  pickAlternativeHref: "/alternative-to/chatgpt",
  pickAlternativeLabel: "Best ChatGPT alternative guide",
  rankedSlugs: RANKED_SLUGS,
  bestFor: {
    chatgpt: "On-demand answers, drafts, and code",
    claude: "Reasoning and long-form writing",
    gemini: "Work inside Google Workspace",
    copilot: "Work inside Microsoft 365",
    perplexity: "Research with citations",
    grok: "Real-time answers with X data",
    deepseek: "Low-cost coding model",
    "google-assistant": "Voice commands and smart home",
    "lindy-ai": "Small agents for specific tasks",
    "cursor-ai": "AI-assisted code editing",
    "notion-ai": "Writing inside Notion",
  },
  shortVersion: {
    chatgpt: "The most recognized chatbot. Reactive: it waits for your prompt.",
    claude: "Excels at reasoning and conversation inside a chat window.",
    gemini: "Makes Gmail, Docs, and Sheets smarter. Stays inside Google.",
    copilot: "AI across Word, Excel, Teams, and Outlook.",
    perplexity: "AI-powered search and research. Does not run your workflow.",
    grok: "Conversational AI with live social and news intelligence.",
    deepseek: "Open-weight LLM with strong coding and free API access.",
    "google-assistant":
      "Voice-first help and quick answers, not deep productivity work.",
    "lindy-ai": "Focused AI agents for specific tasks, not one unified system.",
    "cursor-ai":
      "An AI-first editor for code. GAIA covers everything outside it.",
    "notion-ai": "Writes and summarizes within your Notion workspace.",
  },
  faqs: [
    {
      question: "What is the best AI assistant right now?",
      answer:
        "There is no single best for everyone. Chatbots such as ChatGPT and Claude wait for your prompts and answer inside a conversation window, while GAIA monitors your email, calendar, and tasks and acts before you ask. If most of your day is email, meetings, and follow-ups, a proactive assistant takes more off your plate than a reactive chatbot.",
    },
    {
      question: "What is the best ChatGPT alternative for productivity?",
      answer:
        "GAIA is our pick. ChatGPT answers questions, drafts text and writes code on demand, but it waits for your prompt. GAIA works inside your email, calendar and task tools and runs workflows on its own, on a schedule or when a new email arrives.",
    },
    {
      question: "What are the top rated AI personal assistants right now?",
      answer:
        "The table above is our comparison of current AI personal assistants, ranked by how much real work each one takes off your plate. GAIA is our pick because it acts across email, calendar and tasks without waiting for a prompt; ChatGPT, Claude and Gemini lead for answers and writing. Every entry links to a full head-to-head comparison.",
    },
    {
      question: "Is GAIA open source?",
      answer:
        "GAIA is source-available, not open source: the full code is public under the PolyForm Noncommercial license, which lets you read it and self-host it for personal, noncommercial use. The hosted service at heygaia.io is a paid subscription.",
    },
    {
      question: "Can I use GAIA alongside ChatGPT or Claude?",
      answer:
        "Yes. They solve different problems and work well together. Use ChatGPT or Claude for deep reasoning, content creation, and analytical tasks inside conversations, and use GAIA to run your actual workflow: triaging email, managing your calendar, keeping tasks current, and automating work across your tools.",
    },
    {
      question:
        "Which AI assistant should teams on Google Workspace or Microsoft 365 pick?",
      answer:
        "Choose Gemini if your work lives primarily in Google Workspace and you want AI inside Gmail, Docs, and Sheets. Choose Microsoft Copilot if your organization is standardized on Microsoft 365 with Word, Excel, and Teams. Choose GAIA if your tools span beyond one suite and you want one proactive assistant orchestrating email, calendar, tasks, and workflows across all of them.",
    },
  ],
  useCaseSections: [
    {
      heading: "Best AI assistant for personal use",
      body: (
        <>
          <p>
            For personal use, the best assistant is the one that handles life
            admin without you opening another app: the dentist reminder, the
            email from the landlord, the dinner you need to book. GAIA does that
            from the chat apps you already use. You can text it on{" "}
            <Link
              href="/ai-assistant-whatsapp-telegram-imessage"
              className={LINK_CLASS}
            >
              WhatsApp, Telegram or iMessage
            </Link>
            , send voice notes on WhatsApp and Telegram, and it{" "}
            <Link href="/ai-assistant-with-memory" className={LINK_CLASS}>
              remembers your preferences
            </Link>{" "}
            between conversations.
          </p>
          <p>
            If you mostly want answers, explanations and writing help, ChatGPT,
            Claude and Gemini are excellent and you do not need an assistant
            connected to your accounts. New to this? Our guide to{" "}
            <Link
              href="/how-to-use-ai-as-a-personal-assistant"
              className={LINK_CLASS}
            >
              using AI as a personal assistant
            </Link>{" "}
            walks through the setup.
          </p>
        </>
      ),
    },
    {
      heading: "Best AI assistant for work",
      body: (
        <>
          <p>
            At work the question is reach. Copilot is strongest inside Microsoft
            365 and Gemini inside Google Workspace. If your day spans Gmail or
            Outlook, Slack, Notion, GitHub and Linear, GAIA works across all of
            them and runs the recurring work, such as a morning summary,
            follow-up tracking or triaging new issues, on its own.
          </p>
          <p>
            For inbox and calendar specifically, see our ranking of{" "}
            <Link href="/best-ai-executive-assistant" className={LINK_CLASS}>
              AI executive assistant apps
            </Link>
            . On the desktop, GAIA can{" "}
            <Link
              href="/ai-assistant-that-can-see-your-screen"
              className={LINK_CLASS}
            >
              look at your screen
            </Link>{" "}
            and{" "}
            <Link
              href="/ai-assistant-that-uses-your-computer"
              className={LINK_CLASS}
            >
              take actions on your computer and in a browser
            </Link>
            .
          </p>
        </>
      ),
    },
    {
      heading: "Best AI assistant for iPhone",
      body: (
        <p>
          GAIA does not have an iPhone app yet; it is in development. On an
          iPhone you use GAIA by texting it in iMessage, Telegram or WhatsApp,
          or through the web app in Safari, and it can message you first when a
          workflow finishes. If you want an assistant built into iOS for timers,
          calls and device settings, that is still{" "}
          <Link
            href="/compare/siri"
            aria-label="Siri comparison"
            className={LINK_CLASS}
          >
            Siri
          </Link>
          ; GAIA is for the work Siri does not do.
        </p>
      ),
    },
    {
      heading: "Best AI assistant for Android",
      body: (
        <p>
          There is no GAIA Android app yet either. On Android, GAIA works
          through Telegram and WhatsApp, including voice notes, and through the
          web app in your browser. For phone control and on-device actions,{" "}
          <Link href="/compare/gemini-assistant" className={LINK_CLASS}>
            Gemini
          </Link>{" "}
          and{" "}
          <Link
            href="/compare/google-assistant"
            aria-label="Google Assistant comparison"
            className={LINK_CLASS}
          >
            Google Assistant
          </Link>{" "}
          are built in. GAIA handles your email, calendar and tasks from the
          chat. Want something closer to a{" "}
          <Link href="/ai-assistant-like-jarvis" className={LINK_CLASS}>
            Jarvis on your PC
          </Link>
          ? That is the desktop app.
        </p>
      ),
    },
  ],
  comparisonsTitle: "Compare GAIA with each assistant",
  alternativesTitle: "Alternative guides for each assistant",
};

export function generateMetadata(): Metadata {
  return generateBestHubMetadata(CONFIG);
}

export default function BestAiAssistantPage() {
  return <BestAssistantHub config={CONFIG} />;
}
