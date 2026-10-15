import type { Metadata } from "next";

import BestAssistantHub, {
  type BestHubConfig,
  generateBestHubMetadata,
} from "@/components/seo/BestAssistantHub";

const CONFIG: BestHubConfig = {
  pagePath: "/best-ai-assistant",
  pageTitle: "Best AI Assistant: 12 Top Picks for 2026",
  pageDescription:
    "We ranked 12 AI assistants by how much real work they take off your plate. GAIA is our pick for email, calendar, and tasks. Compare all 12.",
  keywords: [
    "best AI assistant",
    "best ChatGPT alternative",
    "ChatGPT alternative",
    "Claude alternative",
    "Gemini alternative",
    "AI assistant comparison",
    "best AI assistant 2026",
    "proactive AI assistant",
  ],
  breadcrumbName: "Best AI Assistant",
  heading: "Best AI Assistant: Our Top 12 for 2026",
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
        reason: it is the only assistant on this list that monitors your email,
        calendar, and tasks across more than 50 tools and acts on its own. Every
        competitor below is described in its own words from our published
        comparisons, each linked so you can verify every claim.
      </p>
    </>
  ),
  tableAriaLabel: "Top 12 AI assistants ranked",
  tableTitle: "The top 12 at a glance",
  gaiaBestFor: "Proactive daily work",
  gaiaTake:
    "Monitors email, calendar, and tasks across 50+ tools and acts before you ask.",
  gaiaItemDescription:
    "Proactive productivity OS that monitors email, calendar, and tasks across 50+ tools and acts before you ask.",
  pickBody:
    "GAIA is a proactive productivity OS that manages your digital life autonomously. It monitors email, calendar, and tools around the clock and takes action before you ask, with more than 50 native integrations including Gmail, Slack, Notion, GitHub, Calendar, Todoist, and Linear. It is open source, so you can inspect exactly how your data is handled.",
  pickCompareHref: "/compare/chatgpt",
  pickCompareLabel: "See GAIA vs ChatGPT head-to-head",
  pickAlternativeHref: "/alternative-to/chatgpt",
  pickAlternativeLabel: "Best ChatGPT alternative guide",
  // GAIA excluded (it is row #1, "our pick"). Every slug must exist in
  // public/data/comparisons/{slug}.json. Missing slugs throw at render.
  rankedSlugs: [
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
  ],
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
        "GAIA is our pick for an open-source ChatGPT alternative. ChatGPT answers questions, drafts text, and writes code on demand, but it will not proactively manage your inbox or automate workflows. GAIA monitors your email, calendar, and tasks and acts before you ask, with a free tier available.",
    },
    {
      question: "Is GAIA really open source?",
      answer:
        "Yes. GAIA is an open-source AI assistant that works across Gmail, Slack, Notion, GitHub, Calendar, Todoist, Linear, and more than 50 tools in total. Unlike assistants tied to one suite, it connects your whole stack and manages email, calendar, tasks, and multi-step workflows on your behalf.",
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
  comparisonsTitle: "Every GAIA comparison",
  alternativesTitle: "Every alternative guide",
  listAll: true,
};

export function generateMetadata(): Metadata {
  return generateBestHubMetadata(CONFIG);
}

export default function BestAiAssistantPage() {
  return <BestAssistantHub config={CONFIG} />;
}
