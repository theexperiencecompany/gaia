export const OPEN_SOURCE_FAQS = [
  {
    question: "Is GAIA an open source AI assistant?",
    answer:
      "Not in the strict OSI sense. GAIA is source-available: the complete code is public on GitHub under the PolyForm Noncommercial license. You can read it, modify it and self-host it for personal and other noncommercial use. Commercial use needs a separate license, which is the main difference from an MIT or Apache project.",
  },
  {
    question: "Is GAIA really free to self-host?",
    answer:
      "Yes, for personal and other noncommercial use. You can clone the repository, deploy it on your own infrastructure and use it indefinitely with no per-seat charge and no expiring trial. Your costs are the server you run it on and the usage on your own LLM provider account.",
  },
  {
    question: "Can I host an AI assistant on my own server?",
    answer:
      "Yes. Install the GAIA CLI, run `gaia init`, choose Self-Host (Docker) and then `gaia start`. The CLI starts the web app, the API and every database in Docker on your machine or VPS. Open http://localhost:3000 (or your server's address) and sign in.",
  },
  {
    question:
      "What data does self-hosted GAIA store, and what leaves my server?",
    answer:
      "Conversations, memories, todos, workflows and files live in your own PostgreSQL, MongoDB, Redis and ChromaDB, and memory embeddings are computed locally. Three things do leave the server: prompts go to the LLM provider whose API key you configure, connected apps like Gmail are reached through Composio with your Composio key, and analytics or error reports go out only if you add your own PostHog or Sentry keys.",
  },
  {
    question: "Can self-hosted GAIA run a local LLM?",
    answer:
      "No. GAIA calls a hosted model through your own API key (OpenAI or Google Gemini), so it needs an internet connection and a provider account. If your requirement is a fully offline assistant on local models, GAIA is not the right fit today.",
  },
  {
    question: "Can I audit GAIA's code?",
    answer:
      "Yes. The full source is on GitHub at github.com/theexperiencecompany/gaia. The backend, frontend and agent logic are all publicly readable, so you can inspect exactly how your data is processed, stored and sent to the providers you configure.",
  },
  {
    question: "What are the system requirements to self-host GAIA?",
    answer:
      "Docker Engine 20.10+ with Compose v2, Node.js 20+ for the CLI, at least 2 CPU cores, 4GB of RAM (8GB recommended) and 10GB of disk. Linux, macOS and Windows all work through Docker. You also need an API key for OpenAI or Google Gemini.",
  },
];

export const SELF_HOST_STEPS = [
  {
    name: "Install the GAIA CLI",
    text: "Run `npm install -g @heygaia/cli` (or the pnpm or bun equivalent). The CLI needs Node.js 20+ and Docker with Compose v2.",
  },
  {
    name: "Initialize self-host mode",
    text: "Run `gaia init` and choose Self-Host (Docker) in the setup wizard. It scaffolds your environment and asks for your LLM API key and the integrations you want.",
  },
  {
    name: "Start GAIA",
    text: "Run `gaia start` to bring up the web app, API, worker, PostgreSQL, MongoDB, Redis, ChromaDB and RabbitMQ in Docker. Check them with `gaia status` and `gaia logs`, then open http://localhost:3000.",
  },
];
