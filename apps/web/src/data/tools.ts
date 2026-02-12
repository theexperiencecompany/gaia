/**
 * Tools and technologies that power GAIA
 * These are the open-source projects and amazing tools we love and want to celebrate
 */

export interface Tool {
  name: string;
  url: string;
  description: string;
  category: ToolCategory;
}

export type ToolCategory =
  | "Build & Development"
  | "AI & Machine Learning"
  | "Frontend"
  | "Backend & Infrastructure"
  | "Database & Storage"
  | "Monitoring & Analytics"
  | "DevOps & Deployment"
  | "Payments & Business"
  | "Security & Auth"
  | "Community & Feedback";

export const tools: Tool[] = [
  // Build & Development
  {
    name: "Nx",
    url: "https://nx.dev",
    description:
      "Smart monorepo build system with powerful caching, task orchestration, and extensible plugin ecosystem.",
    category: "Build & Development",
  },
  {
    name: "mise",
    url: "https://mise.jdx.dev",
    description:
      "Polyglot runtime manager for managing multiple language versions and project-specific tool configurations.",
    category: "Build & Development",
  },
  {
    name: "Biome",
    url: "https://biomejs.dev",
    description:
      "Fast, modern toolchain for web projects providing formatting, linting, and more in one unified tool.",
    category: "Build & Development",
  },
  {
    name: "pnpm",
    url: "https://pnpm.io",
    description:
      "Fast, disk space efficient package manager with strict dependency resolution and monorepo support.",
    category: "Build & Development",
  },
  {
    name: "uv",
    url: "https://astral.sh/uv",
    description:
      "Blazingly fast Python package installer and resolver written in Rust by the Astral team.",
    category: "Build & Development",
  },
  {
    name: "Ruff",
    url: "https://astral.sh/ruff",
    description:
      "An extremely fast Python linter and formatter, written in Rust. By the creators of uv.",
    category: "Build & Development",
  },
  // AI & Machine Learning
  {
    name: "LangChain",
    url: "https://langchain.com",
    description:
      "Framework for building applications powered by language models with composable components.",
    category: "AI & Machine Learning",
  },
  {
    name: "LangGraph",
    url: "https://docs.langchain.com/oss/python/langgraph/overview",
    description:
      "Library for building stateful, multi-actor AI applications with cycles and persistence.",
    category: "AI & Machine Learning",
  },
  {
    name: "LangSmith",
    url: "https://smith.langchain.com",
    description:
      "Developer platform for debugging, testing, evaluating, and monitoring LLM applications.",
    category: "AI & Machine Learning",
  },
  {
    name: "Mem0",
    url: "https://mem0.ai",
    description:
      "Memory layer for AI applications enabling personalized, context-aware interactions.",
    category: "AI & Machine Learning",
  },
  {
    name: "Opik",
    url: "https://comet.com/opik",
    description:
      "Open-source platform for evaluating, testing, and monitoring LLM applications.",
    category: "AI & Machine Learning",
  },
  {
    name: "Composio",
    url: "https://composio.dev",
    description:
      "Platform for integrating AI agents with 100+ tools and apps through a unified interface.",
    category: "AI & Machine Learning",
  },
  {
    name: "Firecrawl",
    url: "https://firecrawl.dev",
    description:
      "Turn websites into clean, LLM-ready markdown or structured data with a single API call.",
    category: "AI & Machine Learning",
  },
  {
    name: "Tavily",
    url: "https://tavily.com",
    description:
      "AI-native search API designed for LLMs to retrieve accurate, real-time information.",
    category: "AI & Machine Learning",
  },
  {
    name: "E2B",
    url: "https://e2b.dev",
    description:
      "Secure cloud sandboxes for AI agents to execute code and run tools safely.",
    category: "AI & Machine Learning",
  },
  {
    name: "OpenAI",
    url: "https://openai.com",
    description:
      "Leading AI research lab providing powerful language models like GPT-4 and embeddings.",
    category: "AI & Machine Learning",
  },
  {
    name: "Groq",
    url: "https://groq.com",
    description:
      "Ultra-fast AI inference platform with custom LPU chips for lightning-speed responses.",
    category: "AI & Machine Learning",
  },
  {
    name: "Cerebras",
    url: "https://cerebras.ai",
    description:
      "AI computing company with the world's largest chips for ultra-fast model inference.",
    category: "AI & Machine Learning",
  },
  {
    name: "LlamaIndex",
    url: "https://llamaindex.ai",
    description:
      "Data framework for LLM applications to ingest, structure, and access private data.",
    category: "AI & Machine Learning",
  },
  {
    name: "DeepWiki",
    url: "https://deepwiki.com",
    description:
      "AI-powered documentation and knowledge base for understanding codebases instantly.",
    category: "AI & Machine Learning",
  },
  {
    name: "Livekit",
    url: "https://livekit.io",
    description:
      "Open-source platform for building real-time voice and video AI applications.",
    category: "AI & Machine Learning",
  },
  {
    name: "ElevenLabs",
    url: "https://elevenlabs.io",
    description:
      "AI voice technology platform for creating natural-sounding speech synthesis.",
    category: "AI & Machine Learning",
  },
  {
    name: "AssemblyAI",
    url: "https://assemblyai.com",
    description:
      "AI models for speech-to-text, speaker detection, and audio intelligence.",
    category: "AI & Machine Learning",
  },
  {
    name: "Deepgram",
    url: "https://deepgram.com",
    description:
      "Speech AI platform with real-time transcription and voice understanding.",
    category: "AI & Machine Learning",
  },

  // Frontend
  {
    name: "Next.js",
    url: "https://nextjs.org",
    description:
      "The React framework for production with hybrid static & server rendering and route handlers.",
    category: "Frontend",
  },
  {
    name: "React",
    url: "https://react.dev",
    description:
      "The library for building user interfaces with a component-based architecture.",
    category: "Frontend",
  },
  {
    name: "TailwindCSS",
    url: "https://tailwindcss.com",
    description:
      "Utility-first CSS framework for rapidly building custom designs without leaving HTML.",
    category: "Frontend",
  },
  {
    name: "Framer Motion",
    url: "https://motion.dev",
    description:
      "Production-ready motion library for React with declarative animations and gestures.",
    category: "Frontend",
  },
  {
    name: "Radix UI",
    url: "https://radix-ui.com",
    description:
      "Unstyled, accessible UI component primitives for building high-quality design systems.",
    category: "Frontend",
  },
  {
    name: "shadcn/ui",
    url: "https://ui.shadcn.com",
    description:
      "Beautifully designed, accessible components you can copy and paste into your apps.",
    category: "Frontend",
  },
  {
    name: "HeroUI",
    url: "https://heroui.com",
    description:
      "Modern React UI library with beautiful default styles and excellent accessibility.",
    category: "Frontend",
  },
  {
    name: "TanStack Query",
    url: "https://tanstack.com/query",
    description:
      "Powerful asynchronous state management with auto-caching, refetching, and more.",
    category: "Frontend",
  },
  {
    name: "Zustand",
    url: "https://zustand.docs.pmnd.rs",
    description:
      "Small, fast, and scalable bearbones state management solution for React.",
    category: "Frontend",
  },
  {
    name: "React Hook Form",
    url: "https://react-hook-form.com",
    description:
      "Performant, flexible, and extensible forms with easy-to-use validation.",
    category: "Frontend",
  },
  {
    name: "Zod",
    url: "https://zod.dev",
    description:
      "TypeScript-first schema declaration and validation library with static type inference.",
    category: "Frontend",
  },
  {
    name: "TipTap",
    url: "https://tiptap.dev",
    description:
      "Headless, framework-agnostic rich text editor with real-time collaboration support.",
    category: "Frontend",
  },
  {
    name: "Recharts",
    url: "https://recharts.org",
    description:
      "Composable charting library built on React components for data visualization.",
    category: "Frontend",
  },
  {
    name: "XYFlow",
    url: "https://xyflow.com",
    description:
      "Library for building node-based editors and interactive diagrams in React.",
    category: "Frontend",
  },
  {
    name: "Three.js",
    url: "https://threejs.org",
    description:
      "JavaScript 3D library for creating and displaying animated 3D graphics in the browser.",
    category: "Frontend",
  },
  {
    name: "React Three Fiber",
    url: "https://r3f.docs.pmnd.rs",
    description:
      "React renderer for Three.js enabling declarative 3D scene creation.",
    category: "Frontend",
  },
  {
    name: "Mermaid",
    url: "https://mermaid.js.org",
    description:
      "Diagramming and charting tool that renders Markdown-inspired text definitions.",
    category: "Frontend",
  },
  {
    name: "Expo",
    url: "https://expo.dev",
    description:
      "Platform for building universal native apps for Android, iOS, and web with React.",
    category: "Frontend",
  },
  {
    name: "Electron",
    url: "https://electronjs.org",
    description:
      "Build cross-platform desktop apps with JavaScript, HTML, and CSS.",
    category: "Frontend",
  },

  // Backend & Infrastructure
  {
    name: "FastAPI",
    url: "https://fastapi.tiangolo.com",
    description:
      "Modern, fast web framework for building APIs with Python based on type hints.",
    category: "Backend & Infrastructure",
  },
  {
    name: "Pydantic",
    url: "https://pydantic.dev",
    description:
      "Data validation library for Python using type annotations with excellent performance.",
    category: "Backend & Infrastructure",
  },
  {
    name: "Uvicorn",
    url: "https://uvicorn.dev",
    description:
      "Lightning-fast ASGI server implementation using uvloop and httptools.",
    category: "Backend & Infrastructure",
  },
  {
    name: "Arq",
    url: "https://arq-docs.helpmanual.io",
    description:
      "Fast job queuing and RPC in Python with asyncio and Redis as the backend.",
    category: "Backend & Infrastructure",
  },
  {
    name: "Docker",
    url: "https://docker.com",
    description:
      "Platform for developing, shipping, and running applications in containers.",
    category: "Backend & Infrastructure",
  },
  {
    name: "Loguru",
    url: "https://loguru.readthedocs.io",
    description:
      "Python logging made simple and enjoyable with pre-configured formatting.",
    category: "Backend & Infrastructure",
  },
  {
    name: "Resend",
    url: "https://resend.com",
    description:
      "Email API for developers with beautiful templates and reliable delivery.",
    category: "Backend & Infrastructure",
  },
  {
    name: "Cloudinary",
    url: "https://cloudinary.com",
    description:
      "Cloud-based image and video management with on-the-fly transformations.",
    category: "Backend & Infrastructure",
  },
  {
    name: "RabbitMQ",
    url: "https://rabbitmq.com",
    description:
      "Open-source message broker supporting multiple messaging protocols.",
    category: "Backend & Infrastructure",
  },

  // Database & Storage
  {
    name: "ChromaDB",
    url: "https://trychroma.com",
    description:
      "Open-source embedding database for AI applications with simple API and fast queries.",
    category: "Database & Storage",
  },
  {
    name: "PostgreSQL",
    url: "https://postgresql.org",
    description:
      "Powerful, open-source relational database with extensibility and SQL compliance.",
    category: "Database & Storage",
  },
  {
    name: "MongoDB",
    url: "https://mongodb.com",
    description:
      "Document-oriented NoSQL database for flexible, scalable data storage.",
    category: "Database & Storage",
  },
  {
    name: "Redis",
    url: "https://redis.io",
    description:
      "In-memory data structure store used as database, cache, and message broker.",
    category: "Database & Storage",
  },
  {
    name: "Dexie.js",
    url: "https://dexie.org",
    description:
      "Minimalistic wrapper for IndexedDB with intuitive API for browser storage.",
    category: "Database & Storage",
  },

  // Monitoring & Analytics
  {
    name: "PostHog",
    url: "https://posthog.com",
    description:
      "Open-source product analytics with session recordings, feature flags, and A/B testing.",
    category: "Monitoring & Analytics",
  },
  {
    name: "Sentry",
    url: "https://sentry.io",
    description:
      "Application monitoring and error tracking with real-time insights and debugging.",
    category: "Monitoring & Analytics",
  },
  {
    name: "Better Stack",
    url: "https://betterstack.com",
    description:
      "Observability platform combining uptime monitoring, incident management, and logs.",
    category: "Monitoring & Analytics",
  },

  // DevOps & Deployment
  {
    name: "Vercel",
    url: "https://vercel.com",
    description:
      "Platform for frontend developers with instant deployments and edge functions.",
    category: "DevOps & Deployment",
  },
  {
    name: "GitHub",
    url: "https://github.com",
    description:
      "Development platform for version control, collaboration, and CI/CD workflows.",
    category: "DevOps & Deployment",
  },
  {
    name: "GitHub Actions",
    url: "https://github.com/features/actions",
    description:
      "Automate workflows with CI/CD pipelines directly in your GitHub repository.",
    category: "DevOps & Deployment",
  },
  {
    name: "CodeRabbit",
    url: "https://coderabbit.ai",
    description:
      "AI-powered code review tool that provides instant, context-aware feedback on PRs.",
    category: "DevOps & Deployment",
  },
  {
    name: "Release Please",
    url: "https://github.com/googleapis/release-please",
    description:
      "Automate releases based on conventional commits with changelog generation.",
    category: "DevOps & Deployment",
  },
  {
    name: "Mintlify",
    url: "https://mintlify.com",
    description:
      "Beautiful documentation that converts with AI-powered search and analytics.",
    category: "DevOps & Deployment",
  },

  // Payments & Business
  {
    name: "Dodo Payments",
    url: "https://dodopayments.com",
    description:
      "Global payment infrastructure for digital products with instant payouts.",
    category: "Payments & Business",
  },
  {
    name: "Porkbun",
    url: "https://porkbun.com",
    description:
      "Domain registrar with seriously low prices and excellent customer service.",
    category: "Payments & Business",
  },

  // Security & Auth
  {
    name: "WorkOS",
    url: "https://workos.com",
    description:
      "Enterprise-ready authentication with SSO, SCIM, and directory sync for B2B SaaS.",
    category: "Security & Auth",
  },
  {
    name: "Infisical",
    url: "https://infisical.com",
    description:
      "Open-source secret management platform for teams with E2E encryption.",
    category: "Security & Auth",
  },

  // Community & Feedback
  {
    name: "Featurebase",
    url: "https://featurebase.app",
    description:
      "Product feedback and roadmap tool for collecting and prioritizing user requests.",
    category: "Community & Feedback",
  },
  {
    name: "Discord",
    url: "https://discord.com",
    description:
      "Communication platform for communities with voice, video, and text channels.",
    category: "Community & Feedback",
  },
];

export const toolCategories: ToolCategory[] = [
  "Build & Development",
  "AI & Machine Learning",
  "Frontend",
  "Backend & Infrastructure",
  "Database & Storage",
  "Monitoring & Analytics",
  "DevOps & Deployment",
  "Payments & Business",
  "Security & Auth",
  "Community & Feedback",
];
