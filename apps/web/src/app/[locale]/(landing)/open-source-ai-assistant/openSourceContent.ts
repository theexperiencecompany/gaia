export const OPEN_SOURCE_FAQS = [
  {
    question: "Is GAIA an open source AI assistant?",
    answer:
      "Not in the strict OSI sense. GAIA is source-available: the complete code is public on GitHub under the PolyForm Noncommercial license. You can read it, modify it and self-host it for personal and other noncommercial use. Commercial use needs a separate license, which is the main difference from an MIT or Apache project.",
  },
  {
    question: "Is GAIA really free to self-host?",
    answer:
      "Yes, for personal and other noncommercial use. You can deploy it on your own infrastructure with one command and use it indefinitely with no per-seat charge and no expiring trial. Your costs are the server you run it on and the usage on your own LLM provider account.",
  },
  {
    question: "Can I host an AI assistant on my own server?",
    answer:
      "Yes. Run `curl -fsSL https://heygaia.io/install.sh | sh` to install the GAIA CLI, then `gaia up`. It installs Docker if it is missing and starts the web app, the API and every database in Docker on your machine or VPS. Open the address it prints, create the admin account and paste your AI provider key.",
  },
  {
    question:
      "Is there an open source alternative to ChatGPT that manages email and calendar?",
    answer:
      "GAIA is the closest fit, with one caveat: it is source-available under the PolyForm Noncommercial license rather than OSI open source. You can read all of its code and self-host it for personal, noncommercial use, and it connects to Gmail, Outlook and Google Calendar to triage email, draft replies and manage your schedule. For-profit self-hosting needs an enterprise licence.",
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
      "A Linux server, macOS or Windows machine with at least 2 CPU cores, 8 GB of RAM and 10 GB of disk, plus Docker with Compose v2 (the installer sets Docker up for you on Ubuntu and Debian). You also need an API key for your LLM provider.",
  },
];

export const SELF_HOST_STEPS = [
  {
    name: "Install the GAIA CLI",
    text: "Run `curl -fsSL https://heygaia.io/install.sh | sh`. It sets up Node.js if needed and installs the `gaia` command.",
  },
  {
    name: "Run gaia up",
    text: "Run `gaia up`. It installs Docker if it is missing, downloads GAIA's setup files and images, writes the configuration, and starts every service: the API, worker, databases, and message broker. No Git needed.",
  },
  {
    name: "Finish setup in the browser",
    text: "Open the address `gaia up` prints, create the admin account, and paste your AI provider key. GAIA is running on your server.",
  },
];
