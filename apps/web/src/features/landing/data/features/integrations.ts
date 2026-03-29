import type { FeatureData } from "../featuresData";

export const INTEGRATIONS_FEATURES: FeatureData[] = [
  {
    slug: "integrations",
    category: "Integrations",
    icon: "ConnectIcon",
    title: "50+ Integrations",
    tagline: "Connect Gmail, Slack, GitHub, Notion, and 47 more",
    headline: "All your tools. One assistant.",
    subheadline:
      "GAIA connects to Gmail, Slack, GitHub, Notion, Linear, HubSpot, Google Workspace, and 44+ more — with OAuth in one click, no API keys required.",
    benefits: [
      {
        icon: "LinkSquare02Icon",
        title: "One-click OAuth",
        description:
          "Connect any service with a single auth flow, no manual configuration.",
      },
      {
        icon: "WorkflowSquare10Icon",
        title: "Unified tool access",
        description:
          "Every connected service's actions available to GAIA automatically.",
      },
      {
        icon: "ShieldIcon",
        title: "Secure by design",
        description:
          "OAuth tokens scoped to minimum permissions, stored securely per user.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Pick a service to connect",
        description:
          "Browse the integrations list and click Connect next to Gmail, Slack, GitHub, Notion, or any of 47 other services.",
      },
      {
        number: "02",
        title: "Complete the OAuth flow",
        description:
          "Authorize GAIA with the minimum required permissions in the service's own auth screen.",
      },
      {
        number: "03",
        title: "All that service's tools are live",
        description:
          "GAIA immediately has access to every action for that integration — no further configuration required.",
      },
    ],
    faqs: [
      {
        question: "Do I need to manage API keys?",
        answer:
          "No. All integrations use OAuth — GAIA handles token storage and refresh automatically.",
      },
      {
        question: "Can I connect multiple accounts for the same service?",
        answer:
          "Yes. Add multiple Gmail or Google Calendar accounts and GAIA treats each as a separate inbox or calendar, acting from the correct account.",
      },
      {
        question: "What permissions does GAIA request?",
        answer:
          "Permissions are scoped to the minimum needed for each action. For Gmail that means read, compose, and send — not full account access. Permission scopes are listed on each integration's detail page.",
      },
      {
        question: "Can I revoke access to a connected service?",
        answer:
          "Yes. Disconnect any integration from the Integrations settings page. GAIA immediately loses access and stored tokens are deleted.",
      },
    ],
    useCases: [
      {
        title: "Single command across Gmail and Calendar",
        description:
          "A founder connects Gmail and Google Calendar, then asks GAIA to check for meeting requests in the inbox and block the times on the calendar — one prompt, two integrations.",
      },
      {
        title: "GitHub and Linear in one workflow",
        description:
          "An engineering lead connects GitHub and Linear, then builds a workflow that creates a Linear issue automatically whenever a PR is opened without a linked issue.",
      },
      {
        title: "HubSpot and Slack briefing",
        description:
          "A sales manager connects HubSpot and Slack, then asks GAIA for a daily briefing of deals updated yesterday — delivered to a Slack channel every morning.",
      },
    ],
    relatedSlugs: ["marketplace", "mcp-support", "custom-integrations"],
    demoComponent: "integrations",
  },
  {
    slug: "marketplace",
    category: "Integrations",
    icon: "Store01Icon",
    title: "Integration Marketplace",
    tagline: "Discover and install community-built integrations",
    headline: "Thousands of integrations, not just fifty.",
    subheadline:
      "Browse and install community-built integrations from the GAIA marketplace — or publish your own for others to use.",
    benefits: [
      {
        icon: "UserGroupIcon",
        title: "Community integrations",
        description:
          "Browse integrations built and published by other GAIA users.",
      },
      {
        icon: "GitForkIcon",
        title: "Clone and customize",
        description:
          "Install a community integration as-is, or fork and modify it for your setup.",
      },
      {
        icon: "Upload01Icon",
        title: "Publish your own",
        description:
          "Build a custom integration and share it publicly with clone count tracking and creator attribution.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Browse the integration marketplace",
        description:
          "Search by name, category, or use case to find community-built integrations that extend GAIA's capabilities.",
      },
      {
        number: "02",
        title: "Install in one click",
        description:
          "Click Install and the integration's tools are added to GAIA immediately — no configuration needed for most integrations.",
      },
      {
        number: "03",
        title: "Clone, modify, or publish your own",
        description:
          "Fork any community integration to customize it, or publish your own custom integration to the marketplace with one toggle.",
      },
    ],
    faqs: [
      {
        question: "Are community integrations reviewed before publishing?",
        answer:
          "Community integrations are not currently reviewed before listing, but each integration page shows install count, creator, and creation date so you can evaluate trustworthiness.",
      },
      {
        question: "Can I fork a community integration and keep it private?",
        answer:
          "Yes. Cloning an integration creates a private copy in your account. You can modify it without affecting the original or publishing it.",
      },
      {
        question: "How do I publish my own integration?",
        answer:
          "Build a custom integration in the Custom Integrations section, then toggle 'Publish to marketplace' on the integration's settings page. It becomes searchable immediately.",
      },
      {
        question: "Do I need to host anything to publish an integration?",
        answer:
          "No. GAIA hosts the integration manifest. The integration just needs to point to a reachable HTTP endpoint or MCP server.",
      },
    ],
    useCases: [
      {
        title: "Install a Notion-to-Linear sync",
        description:
          "A product team finds a community integration that syncs Notion database updates to Linear issues and installs it in under a minute, without writing any code.",
      },
      {
        title: "Publish an internal tool integration",
        description:
          "An engineering team wraps their internal deployment dashboard API as a GAIA integration and publishes it to their company's private marketplace instance.",
      },
      {
        title: "Fork and localize a community integration",
        description:
          "A developer clones a popular Shopify integration from the marketplace, adds support for a regional payment provider, and saves it as a private custom version.",
      },
    ],
    relatedSlugs: ["integrations", "custom-integrations", "mcp-support"],
    demoComponent: "marketplace",
  },
  {
    slug: "mcp-support",
    category: "Integrations",
    icon: "ServerIcon",
    title: "MCP Support",
    tagline: "Connect any Model Context Protocol server",
    headline: "Connect any AI tool, not just GAIA's list.",
    subheadline:
      "GAIA supports the Model Context Protocol — connect any MCP-compatible server and its tools become immediately available to every GAIA agent.",
    benefits: [
      {
        icon: "ServerIcon",
        title: "Any MCP server",
        description:
          "Point GAIA at any HTTP MCP endpoint and its tools are auto-discovered and indexed.",
      },
      {
        icon: "PasswordValidationIcon",
        title: "Auth-aware",
        description:
          "MCP servers requiring OAuth are handled automatically via spec discovery.",
      },
      {
        icon: "BrainIcon",
        title: "Extends subagents",
        description:
          "MCP tools are available to the main agent and specialized subagents alike.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Paste the MCP server URL",
        description:
          "Enter the HTTP endpoint of any MCP-compatible server in the MCP settings panel.",
      },
      {
        number: "02",
        title: "Tools are auto-discovered and indexed",
        description:
          "GAIA reads the server's manifest, discovers all available tools, and adds them to its toolkit.",
      },
      {
        number: "03",
        title: "Use tools in chat or workflows",
        description:
          "All MCP tools are available immediately in every conversation and workflow, alongside GAIA's native tools.",
      },
    ],
    faqs: [
      {
        question: "What is MCP?",
        answer:
          "Model Context Protocol is an open standard for connecting AI agents to external tools. Any service that implements MCP can expose its capabilities to GAIA.",
      },
      {
        question: "Do MCP servers need to be publicly accessible?",
        answer:
          "Yes. The MCP server must be reachable over HTTP from GAIA's servers. Local development servers are not directly supported unless exposed via a tunnel like ngrok.",
      },
      {
        question: "How does GAIA handle authentication for MCP servers?",
        answer:
          "Servers requiring bearer tokens accept a token added during setup. OAuth-based servers are handled via spec discovery — GAIA follows the server's auth flow automatically.",
      },
      {
        question: "Are MCP tools available to subagents?",
        answer:
          "Yes. All connected MCP tools are shared across the main agent and every specialized subagent.",
      },
    ],
    useCases: [
      {
        title: "Internal search tool via MCP",
        description:
          "An engineering team wraps their internal documentation search as an MCP server and connects it to GAIA, making internal docs searchable from any conversation.",
      },
      {
        title: "Proprietary database query tool",
        description:
          "A data team exposes a read-only SQL query endpoint as an MCP server, giving GAIA the ability to fetch live production metrics directly in workflows.",
      },
      {
        title: "Third-party AI tool integration",
        description:
          "A developer connects a third-party vector search service that supports MCP, making semantic search across their knowledge base available to every GAIA workflow.",
      },
    ],
    relatedSlugs: ["integrations", "custom-integrations", "subagents"],
    demoComponent: "mcp-support",
  },
  {
    slug: "custom-integrations",
    category: "Integrations",
    icon: "PlusSignIcon",
    title: "Custom Integrations",
    tagline: "Build, publish, and share your own integrations",
    headline: "Build the integration that doesn't exist yet.",
    subheadline:
      "Create a custom integration with any URL, add a bearer token, publish it to the marketplace — and GAIA's agents use it immediately across all your automations.",
    benefits: [
      {
        icon: "LinkSquare02Icon",
        title: "Any HTTP endpoint",
        description:
          "Point to any REST API or MCP server; tools are discovered automatically.",
      },
      {
        icon: "Upload01Icon",
        title: "Publish to marketplace",
        description:
          "Share your integration with the community with one toggle.",
      },
      {
        icon: "PasswordValidationIcon",
        title: "Bearer token or OAuth",
        description:
          "Both authentication methods supported without writing code.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Enter the endpoint URL and auth",
        description:
          "Paste the URL of any REST API or MCP server and add a bearer token or configure OAuth.",
      },
      {
        number: "02",
        title: "GAIA discovers the available tools",
        description:
          "The integration is crawled and its endpoints are auto-indexed as callable tools for GAIA's agents.",
      },
      {
        number: "03",
        title: "Use in chat, workflows, or publish",
        description:
          "Tools are live immediately in conversations and workflows. Toggle public to share on the marketplace.",
      },
    ],
    faqs: [
      {
        question: "Do I need to write code to create a custom integration?",
        answer:
          "No. Point GAIA at any reachable HTTP endpoint, add authentication, and tools are discovered automatically. No SDK or code required.",
      },
      {
        question: "What API formats are supported?",
        answer:
          "REST APIs with a discoverable schema (OpenAPI/Swagger) and MCP-compatible servers are both supported. Plain REST endpoints without a schema require manual tool definition.",
      },
      {
        question: "Can I limit who can use a custom integration?",
        answer:
          "Private integrations are only accessible to your account. Published integrations are visible to all GAIA users on the marketplace.",
      },
      {
        question: "How many custom integrations can I create?",
        answer:
          "There is no hard limit on the number of custom integrations per account. Each integration's tools count toward the total tool limit available to GAIA in a single conversation.",
      },
    ],
    useCases: [
      {
        title: "Internal ticket system integration",
        description:
          "An ops team points GAIA at their Zendesk-alternative's REST API, adds a bearer token, and immediately gains the ability to query and create tickets from chat.",
      },
      {
        title: "Proprietary analytics API in workflows",
        description:
          "A data analyst connects an internal analytics API to GAIA and builds a weekly workflow that fetches KPIs and formats them into a Slack summary automatically.",
      },
      {
        title: "Shared integration across a team",
        description:
          "A developer builds a custom integration for a niche project management tool, publishes it to the marketplace, and lets the whole team install it with one click.",
      },
    ],
    relatedSlugs: ["integrations", "marketplace", "mcp-support"],
    demoComponent: "custom-integrations",
  },
  {
    slug: "contacts",
    category: "Integrations",
    icon: "UserCircleIcon",
    title: "Contacts",
    tagline: "Unified contact lookup across Gmail, HubSpot, and more",
    headline: "Find anyone, across every tool.",
    subheadline:
      "GAIA searches contacts across Gmail, Google Contacts, and HubSpot CRM in one query — with name, email, phone, and company context returned instantly.",
    benefits: [
      {
        icon: "Search01Icon",
        title: "Cross-service search",
        description:
          "Query across Gmail history, Google Contacts, and HubSpot simultaneously.",
      },
      {
        icon: "UserIcon",
        title: "Rich contact cards",
        description:
          "Name, email, phone, and source badge rendered directly in conversation.",
      },
      {
        icon: "BarChart01Icon",
        title: "CRM context",
        description:
          "For HubSpot contacts, see lead status, deal stage, and recent activity alongside contact info.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Ask for a contact by name or email",
        description:
          "Search for any person by name, email domain, company, or partial match in natural language.",
      },
      {
        number: "02",
        title: "GAIA searches all connected sources",
        description:
          "Gmail history, Google Contacts, and HubSpot CRM are queried simultaneously in one request.",
      },
      {
        number: "03",
        title: "Contact card appears inline in chat",
        description:
          "Results render as rich cards with name, email, phone, source badge, and CRM deal context.",
      },
    ],
    faqs: [
      {
        question: "Which contact sources does GAIA search?",
        answer:
          "Gmail email history, Google Contacts, and HubSpot CRM are supported. Adding more services is possible by connecting the relevant integration.",
      },
      {
        question: "Can GAIA search by company name?",
        answer:
          "Yes. Searching by company name returns all contacts at that company across every connected source.",
      },
      {
        question: "Can I ask GAIA to email a contact it finds?",
        answer:
          "Yes. After finding a contact, follow up with 'email them' and GAIA will draft and send the message using the email address from the contact card.",
      },
      {
        question: "Does GAIA write back to HubSpot?",
        answer:
          "Yes. Ask GAIA to update a contact's note, add a tag, or log an activity and it will write back to HubSpot via the connected integration.",
      },
    ],
    useCases: [
      {
        title: "Pre-call contact briefing in seconds",
        description:
          "Before a sales call, ask GAIA for everything on a contact — their last email thread, HubSpot deal stage, and phone number — returned as a single card in under 5 seconds.",
      },
      {
        title: "Find and email a contact from memory",
        description:
          "Ask GAIA to find the account manager at Acme Corp and send them a follow-up email. GAIA locates the contact in HubSpot and drafts the email in one step.",
      },
      {
        title: "Build a contact list for outreach",
        description:
          "Ask GAIA to list all contacts at companies in the fintech industry from HubSpot who haven't been emailed in 30 days, and create a follow-up task for each.",
      },
    ],
    relatedSlugs: ["email", "integrations", "memory"],
    demoComponent: "contacts",
  },
  {
    slug: "subagents",
    category: "Integrations",
    icon: "BotIcon",
    title: "Specialized Agents",
    tagline: "37 purpose-built agents — one for every integration",
    headline: "A specialist for every integration.",
    subheadline:
      "GAIA has 37 purpose-built subagents — one for each integration — each with scoped tools, specialized instructions, and deep knowledge of that platform's API.",
    benefits: [
      {
        icon: "RouteIcon",
        title: "Automatic routing",
        description:
          "GAIA detects which integration a task involves and routes to the right specialist agent automatically.",
      },
      {
        icon: "BrainIcon",
        title: "Platform expertise",
        description:
          "Each subagent carries specialized prompts and workflows for its service.",
      },
      {
        icon: "Layers01Icon",
        title: "Parallel execution",
        description:
          "Multiple subagents can run simultaneously for complex multi-platform tasks.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Make a request involving any integration",
        description:
          "Ask GAIA to do something in GitHub, Slack, Notion, or any connected service.",
      },
      {
        number: "02",
        title: "GAIA routes to the right specialist",
        description:
          "The main agent detects which integration is needed and hands off to the dedicated subagent for that platform.",
      },
      {
        number: "03",
        title: "Specialist executes with deep platform knowledge",
        description:
          "The subagent uses scoped tools and platform-specific instructions to complete the task and return the result.",
      },
    ],
    faqs: [
      {
        question: "How many subagents are there?",
        answer:
          "There are 37 specialized subagents, one for each supported integration including Gmail, Slack, GitHub, Notion, Linear, HubSpot, Google Calendar, and more.",
      },
      {
        question: "Can multiple subagents run at the same time?",
        answer:
          "Yes. For tasks spanning multiple integrations, GAIA can run subagents in parallel — for example fetching from GitHub and Slack simultaneously — and merge the results.",
      },
      {
        question: "Can I customize a subagent's behavior?",
        answer:
          "Subagent instructions are fixed per integration to ensure reliability. Custom behaviors are handled through custom skills or workflow steps built on top of subagent outputs.",
      },
      {
        question:
          "Do subagents have access to the same memory as the main agent?",
        answer:
          "Yes. Subagents inherit the current conversation context and long-term memory from the main agent, so they know who you are and what you've asked before.",
      },
    ],
    useCases: [
      {
        title: "Cross-platform task in one message",
        description:
          "Ask GAIA to create a GitHub issue from a Slack message thread — the Slack subagent reads the thread, the GitHub subagent creates the issue, both in the same conversation.",
      },
      {
        title: "Parallel multi-source research",
        description:
          "A product manager asks for a competitive analysis. GAIA spawns Notion, Gmail, and web research subagents in parallel and combines the results into a single summary.",
      },
      {
        title: "Deep HubSpot CRM update",
        description:
          "After a sales call, ask GAIA to log the call outcome in HubSpot — the HubSpot subagent finds the contact, updates the deal stage, and adds a note, all from one instruction.",
      },
    ],
    relatedSlugs: ["integrations", "workflows", "mcp-support"],
    demoComponent: "subagents",
  },
];
