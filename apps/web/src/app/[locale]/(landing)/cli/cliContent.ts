/** What a self-host needs, from docs/self-hosting/overview.mdx ("What you need"). */
export const SELFHOST_REQUIREMENTS = [
  {
    label: "Docker",
    detail: "If it's missing, gaia up offers to install it.",
  },
  {
    label: "8 GB RAM, 2+ CPU cores, 20 GB free disk",
    detail: "The images alone take about 13 GB.",
  },
  {
    label: "One AI provider",
    detail:
      "A key from OpenAI, OpenRouter or Google Gemini, any OpenAI-compatible gateway, or Ollama running locally with no key.",
  },
] as const;

export const SELFHOST_DOCS_URL =
  "https://docs.heygaia.io/self-hosting/walkthrough";
export const CLI_REFERENCE_URL =
  "https://docs.heygaia.io/self-hosting/cli-reference";

export const CLI_FAQS = [
  {
    question: "Is self-hosting GAIA free?",
    answer:
      "For personal and non-profit use, yes. GAIA charges nothing of its own; you pay your AI provider for model usage. GAIA is licensed PolyForm Noncommercial, so running it inside a business needs an enterprise licence.",
  },
  {
    question: "Do I need an API key?",
    answer:
      "You need one AI provider: a key from OpenAI, OpenRouter or Google Gemini, any OpenAI-compatible gateway, or Ollama running locally with no key. You add it in the browser during setup.",
  },
  {
    question: "Who can sign in?",
    answer:
      "Self-hosted GAIA uses email and password. The first account is the admin, and others join by invite link from Settings > Members.",
  },
  {
    question: "How is it different from GAIA Cloud?",
    answer:
      "It runs the same code. There is no billing, so everyone gets every feature, and you bring your own AI keys. Voice and browser automation are not available on self-host, and you run updates and backups yourself.",
  },
  {
    question: "Where does my data live, and how do I update?",
    answer:
      "Everything lives in Docker volumes on your machine. gaia update moves to the release your CLI ships without touching your chats or settings, and gaia backup saves your data so gaia restore can bring it back.",
  },
];
