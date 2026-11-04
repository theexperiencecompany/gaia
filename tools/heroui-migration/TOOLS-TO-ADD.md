# Tools We Love — candidate additions

Research notes for `/thanks` (`apps/web/src/features/thanks/components/Thanks.tsx`,
data in `apps/web/src/data/tools.ts`). **Nothing here has been added to the page** —
`/thanks` is curated by hand.

Compiled 2026-11-02. Existing page has 71 tools across 10 categories.

## How the page is curated

Reading the page copy and the existing 71 entries, the bar is:

- **Real substance, not marketing.** Every entry is something GAIA is genuinely
  built on (Nx, uv, FastAPI, Pydantic, Postgres, Redis…) or something the team
  reaches for daily (CodeRabbit, Mintlify, Featurebase, Porkbun).
- **Developer-first.** Open source is heavily favoured; the few closed-source
  entries are developer infrastructure with a public API.
- **A one-line, concrete pitch.** No "empower your workflow" copy — the existing
  descriptions say what the thing *does* ("Blazingly fast Python package
  installer and resolver written in Rust").
- **Grouped by layer,** not by popularity: build → AI/ML → frontend → backend →
  database → monitoring → devops → payments → security → community.
- **No vanity entries.** Nothing that is only interesting because it is trendy.

The gap worth filling: GAIA's integrations and agent loop are MCP-shaped
(Composio + custom MCP servers), but the page has no card for the protocol
itself, no model-routing layer, and no productivity apps — the bucket GAIA
actually *talks to* on a user's behalf.

Nothing below duplicates an existing entry (checked against `tools.ts`).

## Recommended additions (12)

### AI & Machine Learning

**1. Model Context Protocol**
- Pitch: Open standard for connecting AI models to tools, data, and prompts —
  one protocol instead of one bespoke integration per service.
- Site: https://modelcontextprotocol.io
- Why it belongs: GAIA's tool layer is MCP — the API runs `mcp-use`, integrations
  come through Composio and custom MCP servers. The protocol is the reason a user
  can plug their own tools into GAIA at all, and it is the single most
  load-bearing open standard in the stack right now.

**2. OpenRouter**
- Pitch: One OpenAI-compatible API in front of 600+ models across 80+ providers,
  with automatic fallback when a provider fails.
- Site: https://openrouter.ai
- Why it belongs: GAIA already ships multiple model providers; OpenRouter is the
  natural routing layer for "pick the cheapest model that can do this task" and
  failover, and it exposes a models API that makes capability/pricing data
  queryable at runtime.

**3. Ollama**
- Pitch: Run open models locally or in the cloud, behind OpenAI- and
  Anthropic-compatible endpoints.
- Site: https://ollama.com
- Why it belongs: Gives GAIA a local-first inference path — the privacy story for
  a personal assistant that reads your mail and calendar. The OpenAI-compatible
  `localhost:11434/v1` endpoint means zero new client code.

**4. Vercel AI SDK**
- Pitch: TypeScript toolkit for streaming AI UIs and agents, with a first-class
  MCP client (`@ai-sdk/mcp`), tool approval, and DevTools.
- Site: https://ai-sdk.dev
- Why it belongs: The TypeScript counterpart to GAIA's Python agent stack. If any
  GAIA surface grows its own agent loop in `apps/web` (the desktop/web chat
  shells), this is what it should be built on — and its MCP client matches the
  protocol card above.

### Build & Development

**5. Playwright**
- Pitch: Cross-browser end-to-end testing and automation, with an official MCP
  server that drives a real browser from accessibility snapshots.
- Site: https://playwright.dev
- Why it belongs: GAIA does browser tasks for users; `@playwright/mcp` is the
  cleanest way to give an agent deterministic browser control, and the same
  runner covers web E2E for `apps/web`. Apache-2.0, Microsoft-maintained.

### Database & Storage

**6. Drizzle ORM**
- Pitch: TypeScript-first SQL ORM with typed schema, typed migrations, and
  zero-runtime-overhead queries.
- Site: https://orm.drizzle.team
- Why it belongs: The page lists Postgres, Mongo, and Redis but nothing for the
  TypeScript data layer. Drizzle is the schema-as-code layer most new TS services
  (and the Postgres-backed parts of the product surface) reach for.

**7. Qdrant**
- Pitch: Open-source vector database in Rust, with filtering, hybrid search, and
  an official MCP memory server.
- Site: https://qdrant.tech
- Why it belongs: ChromaDB is the only vector store on the page. Qdrant is the
  production-grade alternative — self-hostable, fast, and its MCP server
  (`qdrant/mcp-server-qdrant`) is a drop-in long-term memory backend for agents.

### DevOps & Deployment

**8. Trigger.dev**
- Pitch: Open-source platform for durable, long-running TypeScript tasks —
  retries, queues, waits, and full tracing with no execution timeout.
- Site: https://trigger.dev
- Why it belongs: Agent work is long-running and failure-prone. GAIA already
  needs background jobs (Arq on the Python side); Trigger.dev is the TypeScript
  equivalent, Apache-2.0 and self-hostable, with an official MCP server for
  triggering and inspecting runs.

### Monitoring & Analytics

**9. OpenTelemetry**
- Pitch: Vendor-neutral standard for traces, metrics, and logs, with SDKs for
  every language GAIA ships.
- Site: https://opentelemetry.io
- Why it belongs: PostHog, Sentry, and Better Stack are all on the page, but the
  thing that keeps them swappable — and the reason agent runs can be traced end
  to end — is OTel. It is infrastructure the whole observability section depends
  on.

### Productivity (suggested new category)

The page has no home for the apps GAIA acts *on*. These three fit the existing
"public API + credible + developer-loved" bar and are all MCP-native. If you'd
rather not add an 11th category, they can sit under "Community & Feedback" — but
"Productivity" reads better next to a section that already has 6–19 entries each.

**10. Cal.com**
- Pitch: Open-source scheduling infrastructure with a full API v2 and a hosted
  MCP server (`mcp.cal.com`) exposing bookings, event types, and availability.
- Site: https://cal.com
- Why it belongs: GAIA is a calendar assistant. Cal.com is the open, self-hostable
  scheduling layer a user can actually own, and its hosted MCP server means
  "book me 30 minutes with X" is a tool call, not a scraper.

**11. Linear**
- Pitch: Fast issue tracking and project planning for software teams, with a
  GraphQL API and an official remote MCP server (`mcp.linear.app/mcp`).
- Site: https://linear.app
- Why it belongs: The developer-tool counterpart to the GitHub card already on the
  page, and one of the cleanest reference implementations of a hosted, OAuth'd
  MCP server — a good pattern for GAIA's own integration docs.

**12. Raycast**
- Pitch: Keyboard-first launcher with a real extension API (React + TypeScript)
  and native MCP support for installing servers and exposing extension tools.
- Site: https://raycast.com
- Why it belongs: It is the tool the "Tools We Love" audience actually lives in,
  it has a public extension API GAIA could target for a quick-capture surface,
  and since 2.5 extensions can even bundle their own MCP server — the same
  distribution idea as GAIA's integration marketplace.

## Copy-paste entries

Matches the `Tool` interface in `apps/web/src/data/tools.ts`. Descriptions follow
the existing one-sentence, concrete style.

```ts
  // AI & Machine Learning
  {
    name: "Model Context Protocol",
    url: "https://modelcontextprotocol.io",
    description:
      "Open standard for connecting AI models to tools, data, and prompts through one interface.",
    category: "AI & Machine Learning",
  },
  {
    name: "OpenRouter",
    url: "https://openrouter.ai",
    description:
      "One OpenAI-compatible API in front of hundreds of models with automatic provider fallback.",
    category: "AI & Machine Learning",
  },
  {
    name: "Ollama",
    url: "https://ollama.com",
    description:
      "Run open models locally or in the cloud behind OpenAI-compatible endpoints.",
    category: "AI & Machine Learning",
  },
  {
    name: "Vercel AI SDK",
    url: "https://ai-sdk.dev",
    description:
      "TypeScript toolkit for streaming AI interfaces and agents, with a first-class MCP client.",
    category: "AI & Machine Learning",
  },

  // Build & Development
  {
    name: "Playwright",
    url: "https://playwright.dev",
    description:
      "Cross-browser end-to-end testing and automation with an official MCP server for agents.",
    category: "Build & Development",
  },

  // Database & Storage
  {
    name: "Drizzle ORM",
    url: "https://orm.drizzle.team",
    description:
      "TypeScript-first SQL ORM with typed schemas, typed migrations, and no runtime overhead.",
    category: "Database & Storage",
  },
  {
    name: "Qdrant",
    url: "https://qdrant.tech",
    description:
      "Open-source vector database in Rust with filtering, hybrid search, and an MCP memory server.",
    category: "Database & Storage",
  },

  // DevOps & Deployment
  {
    name: "Trigger.dev",
    url: "https://trigger.dev",
    description:
      "Open-source platform for durable, long-running TypeScript tasks with retries and tracing.",
    category: "DevOps & Deployment",
  },

  // Monitoring & Analytics
  {
    name: "OpenTelemetry",
    url: "https://opentelemetry.io",
    description:
      "Vendor-neutral standard for traces, metrics, and logs with SDKs for every language.",
    category: "Monitoring & Analytics",
  },

  // Productivity
  {
    name: "Cal.com",
    url: "https://cal.com",
    description:
      "Open-source scheduling infrastructure with a full API and a hosted MCP server.",
    category: "Productivity",
  },
  {
    name: "Linear",
    url: "https://linear.app",
    description:
      "Fast issue tracking and project planning with a GraphQL API and a hosted MCP server.",
    category: "Productivity",
  },
  {
    name: "Raycast",
    url: "https://raycast.com",
    description:
      "Keyboard-first launcher with a TypeScript extension API and native MCP support.",
    category: "Productivity",
  },
```

If the "Productivity" category is added, append it to `ToolCategory` and
`toolCategories` (order determines section order on the page):

```ts
  "Productivity",
```

Without the new category, put Cal.com, Linear, and Raycast under
`"Community & Feedback"`.

## Deliberately left out

- **Hugging Face, Together, Mistral** — provider cards, and the page already has
  OpenAI / Groq / Cerebras. Adding more model vendors would dilute it.
- **Langfuse, Arize Phoenix, Braintrust** — real tools, but LangSmith and Opik
  already cover tracing and evals. Three cards for one job is noise.
- **Supabase, Neon, Turso** — good products, but "another hosted Postgres" is not
  what this page is for.
- **Notion, Slack, Gmail, Google Calendar** — GAIA integrations, not tools GAIA is
  *built on*. They belong in the marketplace, not the thank-you list.
- **Stripe, Clerk, Auth0** — already represented by Dodo Payments and WorkOS.
