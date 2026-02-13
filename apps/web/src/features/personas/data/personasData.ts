export interface PersonaFeature {
  title: string;
  description: string;
}

export interface PersonaData {
  slug: string;
  title: string;
  role: string;
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  intro: string;
  painPoints: string[];
  howGaiaHelps: PersonaFeature[];
  relevantIntegrations: string[];
  faqs: Array<{ question: string; answer: string }>;
}

export const personas: Record<string, PersonaData> = {
  "software-developers": {
    slug: "software-developers",
    title: "AI Assistant for Software Developers",
    role: "Software Developers",
    metaTitle:
      "AI Assistant for Software Developers - Automate Your Dev Workflow",
    metaDescription:
      "GAIA helps software developers automate code reviews, manage GitHub issues, track Linear tickets, and streamline daily standups. Save 10+ hours per week on busywork.",
    keywords: [
      "AI assistant for developers",
      "developer productivity tool",
      "GitHub automation",
      "Linear AI integration",
      "coding workflow automation",
    ],
    intro:
      "Software developers spend an estimated 58% of their time on non-coding tasks according to GitHub's 2024 Octoverse report. Context-switching between Slack threads, GitHub notifications, Linear tickets, and email drains the deep focus required for quality code. GAIA acts as a proactive AI assistant that manages your developer workflow end-to-end, from triaging GitHub notifications to preparing daily standup summaries, so you can spend more time in your editor and less time managing tools.",
    painPoints: [
      "Constant context-switching between GitHub, Linear, Slack, and email fragments deep work sessions",
      "Code review notifications pile up, causing merge bottlenecks and stale PRs",
      "Manual standup reporting and status updates consume 30+ minutes daily",
      "Tracking cross-repository dependencies and deployment statuses across tools is tedious",
    ],
    howGaiaHelps: [
      {
        title: "Automated GitHub & Linear Triage",
        description:
          "GAIA monitors your GitHub notifications and Linear inbox, prioritizes issues by urgency, and surfaces only what needs your attention. It drafts responses to routine issues and links related PRs to tickets automatically.",
      },
      {
        title: "Smart Standup Summaries",
        description:
          "Every morning, GAIA compiles your merged PRs, completed tickets, and in-progress work into a formatted standup update. Post it directly to Slack with one click.",
      },
      {
        title: "Proactive Calendar & Meeting Prep",
        description:
          "GAIA scans your Google Calendar for upcoming meetings, pulls relevant Linear tickets and GitHub discussions, and prepares briefing notes so you walk into every sprint planning and code review prepared.",
      },
    ],
    relevantIntegrations: [
      "github",
      "linear",
      "slack",
      "google-calendar",
      "gmail",
      "notion",
      "todoist",
      "perplexity",
      "deepwiki",
      "context7",
    ],
    faqs: [
      {
        question:
          "How does GAIA integrate with my existing developer workflow?",
        answer:
          "GAIA connects natively to GitHub, Linear, Slack, and Google Calendar through MCP integrations. It monitors these tools in the background, learns your patterns, and surfaces relevant information proactively without requiring you to change how you work.",
      },
      {
        question: "Can GAIA help with code reviews?",
        answer:
          "GAIA tracks open PRs across your repositories, alerts you to reviews that need attention, and summarizes code changes. It can draft initial review comments and ensure no PR goes stale in your queue.",
      },
      {
        question: "Is my code data safe with GAIA?",
        answer:
          "GAIA is fully open source and self-hostable. You can run it on your own infrastructure with complete data control. GAIA never trains on your data or shares it with third parties.",
      },
    ],
  },

  "product-managers": {
    slug: "product-managers",
    title: "AI Assistant for Product Managers",
    role: "Product Managers",
    metaTitle:
      "AI Assistant for Product Managers - Streamline Product Development",
    metaDescription:
      "GAIA helps product managers track feature requests, automate stakeholder updates, manage roadmaps across tools, and prepare for meetings with AI-powered briefings.",
    keywords: [
      "AI assistant for product managers",
      "product management automation",
      "roadmap management AI",
      "stakeholder update automation",
      "PM productivity tool",
    ],
    intro:
      "Product managers operate at the intersection of engineering, design, business, and customer success. A 2024 Productboard survey found that PMs spend over 40% of their week on status updates, meeting prep, and tool management rather than strategic product thinking. GAIA serves as your proactive AI copilot, synthesizing information across Linear, Slack, Gmail, and Notion so you can focus on building the right product instead of managing the process.",
    painPoints: [
      "Stakeholder updates require manually pulling data from Linear, GitHub, and Slack channels",
      "Feature requests scatter across email, Slack messages, and support tickets without a unified view",
      "Meeting overload leaves insufficient time for user research and strategic planning",
      "Keeping roadmap documentation current across Notion and Linear is a constant chore",
    ],
    howGaiaHelps: [
      {
        title: "Automated Stakeholder Reports",
        description:
          "GAIA pulls sprint progress from Linear, deployment updates from GitHub, and team discussions from Slack to generate weekly stakeholder reports. It drafts them in your preferred format and sends via Gmail or Slack.",
      },
      {
        title: "Feature Request Aggregation",
        description:
          "GAIA monitors Gmail, Slack, and support channels for feature requests, categorizes them by theme and urgency, and creates organized Linear tickets with full context attached.",
      },
      {
        title: "Meeting Intelligence",
        description:
          "Before every meeting, GAIA prepares briefing docs with relevant metrics, recent discussions, and open action items. After meetings, it captures decisions and creates follow-up tasks in Todoist or Linear.",
      },
      {
        title: "Roadmap Sync",
        description:
          "GAIA keeps your Notion roadmap documents aligned with Linear project statuses, flagging discrepancies and suggesting updates when milestones shift.",
      },
    ],
    relevantIntegrations: [
      "linear",
      "slack",
      "gmail",
      "notion",
      "google-calendar",
      "google-docs",
      "todoist",
      "google-meet",
      "github",
      "asana",
    ],
    faqs: [
      {
        question: "Can GAIA replace my project management tool?",
        answer:
          "GAIA complements your existing tools like Linear, Asana, or Notion rather than replacing them. It acts as an intelligent layer that connects these tools, automates data flow between them, and surfaces insights so you spend less time managing tools and more time on product strategy.",
      },
      {
        question: "How does GAIA help with stakeholder communication?",
        answer:
          "GAIA automatically compiles progress data from your engineering tools, drafts status updates in your preferred format, and can send them via email or Slack on a schedule. It ensures stakeholders stay informed without you manually building reports.",
      },
    ],
  },

  designers: {
    slug: "designers",
    title: "AI Assistant for Designers",
    role: "Designers",
    metaTitle: "AI Assistant for Designers - Streamline Design Operations",
    metaDescription:
      "GAIA helps designers manage feedback loops, track design requests, automate handoff documentation, and keep stakeholders aligned across Slack, Notion, and email.",
    keywords: [
      "AI assistant for designers",
      "design workflow automation",
      "design operations AI",
      "design feedback management",
      "creative productivity tool",
    ],
    intro:
      "Designers spend a disproportionate amount of time on operations rather than craft. Research from InVision found that designers dedicate roughly 35% of their time to non-design activities like managing feedback, writing documentation, and coordinating with stakeholders. GAIA automates the operational side of design work, managing feedback collection, scheduling reviews, and keeping handoff documentation current so you can focus on creating exceptional user experiences.",
    painPoints: [
      "Design feedback scatters across Slack threads, email chains, and meeting notes without a single source of truth",
      "Handoff documentation becomes outdated as designs iterate, causing engineering misalignment",
      "Scheduling design reviews and critiques across time zones consumes hours of coordination",
      "Tracking design request intake from product and engineering lacks structure",
    ],
    howGaiaHelps: [
      {
        title: "Centralized Feedback Collection",
        description:
          "GAIA monitors Slack channels and Gmail for design feedback, organizes comments by project and screen, and creates structured summaries in Notion so nothing falls through the cracks.",
      },
      {
        title: "Automated Design Review Scheduling",
        description:
          "GAIA coordinates design critique sessions by finding optimal times on Google Calendar, sending invites with context links, and preparing pre-review briefs with recent changes.",
      },
      {
        title: "Request Intake Management",
        description:
          "Design requests from Slack messages and emails are automatically captured, categorized, and added to your Todoist or Linear backlog with relevant context and priority levels.",
      },
    ],
    relevantIntegrations: [
      "slack",
      "gmail",
      "notion",
      "google-calendar",
      "todoist",
      "linear",
      "google-docs",
      "google-meet",
      "trello",
    ],
    faqs: [
      {
        question: "Can GAIA help manage design systems documentation?",
        answer:
          "GAIA helps keep your Notion or Google Docs documentation in sync with project updates. It can flag when documentation needs updating based on Linear ticket changes and draft update summaries for your review.",
      },
      {
        question:
          "How does GAIA handle design feedback from multiple channels?",
        answer:
          "GAIA monitors Slack, Gmail, and other connected channels for design-related discussions. It aggregates feedback by project, identifies action items, and creates organized summaries so you have a single view of all stakeholder input.",
      },
    ],
  },

  "startup-founders": {
    slug: "startup-founders",
    title: "AI Assistant for Startup Founders",
    role: "Startup Founders",
    metaTitle: "AI Assistant for Startup Founders - Scale Yourself with AI",
    metaDescription:
      "GAIA helps startup founders manage investor updates, automate hiring pipelines, track metrics across tools, and handle the operational chaos of building a company.",
    keywords: [
      "AI assistant for startup founders",
      "founder productivity tool",
      "startup automation",
      "investor update automation",
      "founder workflow AI",
    ],
    intro:
      "Startup founders wear every hat simultaneously. A First Round Capital survey revealed that 72% of founders cite time management as their biggest challenge, with the average founder context-switching between 12+ tools daily. GAIA acts as your AI chief of staff, proactively managing investor communications, hiring pipelines, team updates, and the operational overhead that scales with your company, freeing you to focus on the decisions that only you can make.",
    painPoints: [
      "Investor updates require manually gathering metrics from multiple dashboards and tools",
      "Email inbox overwhelm with hundreds of daily messages from candidates, investors, customers, and partners",
      "Hiring pipeline management across LinkedIn, email, and calendars is time-consuming and error-prone",
      "Team alignment suffers when updates and decisions scatter across Slack, email, and meetings",
    ],
    howGaiaHelps: [
      {
        title: "Automated Investor Updates",
        description:
          "GAIA compiles key metrics, milestones, and highlights from your tools into polished investor update drafts. Review, customize, and send directly through Gmail on your preferred schedule.",
      },
      {
        title: "Intelligent Email Triage",
        description:
          "GAIA reads every incoming email, categorizes by priority (investor, customer, hiring, operational), drafts responses for routine messages, and ensures high-priority items surface immediately.",
      },
      {
        title: "Hiring Pipeline Coordination",
        description:
          "GAIA tracks candidates across Gmail and Google Calendar, schedules interviews automatically, sends follow-up reminders, and keeps your hiring tracker in Notion or Google Sheets updated.",
      },
      {
        title: "Team Sync Automation",
        description:
          "Morning briefings with key updates from Slack channels, upcoming meetings, and pending decisions are delivered before you open your laptop. GAIA ensures nothing falls through the cracks.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "slack",
      "notion",
      "google-sheets",
      "google-docs",
      "google-meet",
      "todoist",
      "linkedin",
      "twitter",
    ],
    faqs: [
      {
        question:
          "How does GAIA help founders save time on investor relations?",
        answer:
          "GAIA automatically gathers data from your connected tools, drafts investor update emails in your voice, and can schedule them for delivery. What typically takes 2-3 hours per month becomes a quick review-and-send process.",
      },
      {
        question: "Is GAIA secure enough for sensitive startup data?",
        answer:
          "GAIA is fully open source and self-hostable. You can deploy it on your own infrastructure, ensuring complete data sovereignty. No data is ever shared with third parties or used for model training.",
      },
      {
        question: "Can GAIA manage my calendar as a founder?",
        answer:
          "Yes. GAIA integrates with Google Calendar to optimize your schedule, block focus time, prepare meeting briefs, and coordinate across multiple calendars. It proactively suggests schedule adjustments when conflicts arise.",
      },
    ],
  },

  students: {
    slug: "students",
    title: "AI Assistant for Students",
    role: "Students",
    metaTitle: "AI Assistant for Students - Organize Academics and Boost Focus",
    metaDescription:
      "GAIA helps students manage assignments, organize research, schedule study sessions, and stay on top of deadlines across all their academic tools.",
    keywords: [
      "AI assistant for students",
      "student productivity tool",
      "academic task management AI",
      "study planner AI",
      "assignment tracker automation",
    ],
    intro:
      "Students juggle coursework, research, extracurriculars, and social commitments with limited time and cognitive bandwidth. Studies from the National Survey of Student Engagement show that effective time management is the single strongest predictor of academic success. GAIA helps students organize their academic lives by managing assignments, scheduling study sessions, tracking deadlines, and surfacing relevant research, acting as a personal academic assistant that keeps everything on track.",
    painPoints: [
      "Assignment deadlines scatter across syllabi, emails, and learning management systems",
      "Research material accumulates without organization, making paper writing inefficient",
      "Study schedule planning is reactive rather than proactive, leading to last-minute cramming",
    ],
    howGaiaHelps: [
      {
        title: "Deadline Tracking & Reminders",
        description:
          "GAIA monitors your Gmail for assignment notifications, creates tasks in Todoist with deadlines, and sends proactive reminders with enough lead time for quality work.",
      },
      {
        title: "Research Organization",
        description:
          "GAIA uses Perplexity integration for research queries, organizes findings in Notion or Google Docs, and helps you build structured outlines for papers and projects.",
      },
      {
        title: "Smart Study Scheduling",
        description:
          "GAIA analyzes your Google Calendar for free blocks, schedules focused study sessions around your classes and commitments, and adjusts when deadlines shift.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "todoist",
      "notion",
      "google-docs",
      "google-sheets",
      "perplexity",
      "slack",
      "google-tasks",
    ],
    faqs: [
      {
        question: "Is GAIA free for students?",
        answer:
          "GAIA offers a free tier with core features that covers most student needs. You can also self-host GAIA entirely free for complete control over your data.",
      },
      {
        question: "Can GAIA help with research papers?",
        answer:
          "GAIA integrates with Perplexity for AI-powered research, organizes findings in Notion or Google Docs, and helps structure your work. It manages the logistics of research so you can focus on analysis and writing.",
      },
    ],
  },

  "remote-workers": {
    slug: "remote-workers",
    title: "AI Assistant for Remote Workers",
    role: "Remote Workers",
    metaTitle: "AI Assistant for Remote Workers - Master Async Communication",
    metaDescription:
      "GAIA helps remote workers manage async communication, organize scattered tools, automate status updates, and maintain work-life boundaries with intelligent automation.",
    keywords: [
      "AI assistant for remote workers",
      "remote work productivity",
      "async communication AI",
      "remote team collaboration tool",
      "work from home assistant",
    ],
    intro:
      "Remote workers face a unique paradox: more flexibility but more fragmentation. Buffer's 2024 State of Remote Work report found that 23% of remote workers struggle with loneliness and 21% cite communication challenges as their biggest obstacle. The average remote worker checks 8+ tools throughout the day. GAIA bridges the gaps by centralizing communication, automating status updates, and ensuring nothing gets lost across time zones and tool silos.",
    painPoints: [
      "Information silos across Slack, email, Notion, and project management tools make context-switching exhausting",
      "Async communication gaps lead to missed messages and delayed responses across time zones",
      "Maintaining visibility with distributed teams requires constant manual status updates",
      "Work-life boundaries blur when notifications arrive 24/7 from global team members",
    ],
    howGaiaHelps: [
      {
        title: "Unified Communication Hub",
        description:
          "GAIA monitors Slack, Gmail, and Microsoft Teams for important messages, consolidates them into priority-ordered summaries, and ensures you never miss critical async updates.",
      },
      {
        title: "Automated Status Updates",
        description:
          "GAIA tracks your completed work across tools and posts end-of-day summaries to Slack or sends them via email. Your team stays informed without you writing manual updates.",
      },
      {
        title: "Smart Notification Management",
        description:
          "GAIA learns your work schedule, batches non-urgent notifications, and only surfaces time-sensitive items during focus hours. It respects your boundaries while keeping you informed.",
      },
    ],
    relevantIntegrations: [
      "slack",
      "gmail",
      "google-calendar",
      "microsoft-teams",
      "notion",
      "todoist",
      "google-meet",
      "linear",
      "asana",
      "google-docs",
    ],
    faqs: [
      {
        question: "How does GAIA help with async communication?",
        answer:
          "GAIA monitors your Slack channels, email, and other communication tools continuously. It summarizes conversations you missed, highlights items that need your response, and can draft replies for routine messages so you stay current without constant monitoring.",
      },
      {
        question: "Can GAIA work across different time zones?",
        answer:
          "Yes. GAIA operates 24/7 and understands time zone contexts. It schedules meetings considering all participants' availability, batches notifications appropriately, and delivers morning briefings tailored to your local time.",
      },
    ],
  },

  freelancers: {
    slug: "freelancers",
    title: "AI Assistant for Freelancers",
    role: "Freelancers",
    metaTitle: "AI Assistant for Freelancers - Automate the Business Side",
    metaDescription:
      "GAIA helps freelancers manage client communication, track projects, automate invoicing follow-ups, and handle the administrative overhead of running a solo business.",
    keywords: [
      "AI assistant for freelancers",
      "freelancer productivity tool",
      "client management automation",
      "freelance workflow AI",
      "solo business automation",
    ],
    intro:
      "Freelancers are simultaneously the CEO, accountant, project manager, and individual contributor. Upwork's 2024 Freelance Forward study found that freelancers spend 33% of their working hours on non-billable administrative tasks including client communication, invoicing, and project management. GAIA handles the business side of freelancing so you can maximize billable hours and deliver exceptional work to clients.",
    painPoints: [
      "Client emails and Slack messages demand immediate responses across multiple projects simultaneously",
      "Invoice follow-ups and payment tracking are tedious but critical for cash flow",
      "Scheduling client meetings across multiple calendars and time zones is a constant juggle",
      "Project status tracking across clients lacks a unified view",
    ],
    howGaiaHelps: [
      {
        title: "Client Communication Management",
        description:
          "GAIA triages client emails by project and urgency, drafts professional responses for routine queries, and ensures no client message goes unanswered beyond your response SLA.",
      },
      {
        title: "Project & Task Orchestration",
        description:
          "GAIA creates and manages tasks across Todoist or Asana for each client project, tracks deadlines, and sends you proactive reminders before deliverables are due.",
      },
      {
        title: "Scheduling Automation",
        description:
          "GAIA manages your Google Calendar across all client engagements, automatically suggests meeting times, and blocks focus time for deep work on deliverables.",
      },
      {
        title: "Invoice & Follow-up Tracking",
        description:
          "GAIA tracks sent invoices via Gmail, reminds you of unpaid invoices, and drafts polite follow-up emails for overdue payments so you maintain cash flow without awkward conversations.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "slack",
      "todoist",
      "asana",
      "notion",
      "google-sheets",
      "google-docs",
      "google-meet",
      "trello",
    ],
    faqs: [
      {
        question: "Can GAIA manage multiple client projects simultaneously?",
        answer:
          "Yes. GAIA organizes work by client and project, tracks deadlines across all engagements, and ensures nothing falls through the cracks. It provides a unified view of all your active projects regardless of which tools each client uses.",
      },
      {
        question: "How does GAIA help freelancers get paid faster?",
        answer:
          "GAIA tracks invoice status through Gmail, identifies overdue payments, and drafts professional follow-up emails for your review. It automates the tedious payment tracking process so you can focus on client work.",
      },
    ],
  },

  entrepreneurs: {
    slug: "entrepreneurs",
    title: "AI Assistant for Entrepreneurs",
    role: "Entrepreneurs",
    metaTitle:
      "AI Assistant for Entrepreneurs - Build Faster with AI Automation",
    metaDescription:
      "GAIA helps entrepreneurs automate operations, manage customer relationships, coordinate teams, and make faster decisions with AI-powered workflow automation.",
    keywords: [
      "AI assistant for entrepreneurs",
      "business automation AI",
      "entrepreneur productivity",
      "small business AI tool",
      "business workflow automation",
    ],
    intro:
      "Entrepreneurs must move fast while managing an ever-growing list of operational responsibilities. Harvard Business Review research shows that entrepreneurs who effectively delegate and automate operational tasks are 3x more likely to scale successfully. GAIA serves as your AI operations manager, handling email triage, customer follow-ups, team coordination, and the daily administrative burden so you can focus on growth and strategy.",
    painPoints: [
      "Operational tasks expand faster than the team, creating bottlenecks at the founder level",
      "Customer relationships suffer when follow-ups slip through the cracks of a busy inbox",
      "Team coordination across Slack, email, and project tools requires constant attention",
      "Decision-making slows when information is scattered across a dozen different tools",
    ],
    howGaiaHelps: [
      {
        title: "Intelligent Email & CRM Management",
        description:
          "GAIA triages your inbox, identifies customer and partner emails, drafts responses, and ensures follow-ups happen on schedule. It connects with HubSpot to keep your CRM current automatically.",
      },
      {
        title: "Team Operations Automation",
        description:
          "GAIA monitors Slack channels and Linear boards, surfaces blockers, compiles team status reports, and ensures action items from meetings get tracked and completed.",
      },
      {
        title: "Decision Intelligence",
        description:
          "GAIA aggregates data from your connected tools into daily briefings, highlights anomalies, and surfaces the information you need to make fast, informed decisions.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "slack",
      "google-calendar",
      "hubspot",
      "notion",
      "linear",
      "google-sheets",
      "google-docs",
      "todoist",
      "twitter",
    ],
    faqs: [
      {
        question: "How is GAIA different from a virtual assistant?",
        answer:
          "Unlike human virtual assistants, GAIA operates 24/7 with zero wait time, integrates directly with your tools, and learns your preferences over time through graph-based memory. It handles tasks instantly and scales without hiring overhead.",
      },
      {
        question: "Can GAIA help manage customer relationships?",
        answer:
          "Yes. GAIA integrates with HubSpot and Gmail to track customer communications, ensure timely follow-ups, and flag important customer interactions. It helps you maintain strong relationships even as your customer base grows.",
      },
    ],
  },

  marketers: {
    slug: "marketers",
    title: "AI Assistant for Marketers",
    role: "Marketers",
    metaTitle: "AI Assistant for Marketers - Automate Marketing Operations",
    metaDescription:
      "GAIA helps marketers automate campaign tracking, manage social media workflows, coordinate content calendars, and streamline cross-channel reporting.",
    keywords: [
      "AI assistant for marketers",
      "marketing automation AI",
      "content marketing assistant",
      "social media automation",
      "marketing productivity tool",
    ],
    intro:
      "Modern marketers manage an average of 12 different tools according to ChiefMartec's Marketing Technology Landscape report, from email platforms and social media schedulers to analytics dashboards and CRMs. The operational overhead of managing cross-channel campaigns leaves little time for creative strategy. GAIA connects your marketing stack, automates reporting, and manages the tactical execution so you can focus on campaigns that drive growth.",
    painPoints: [
      "Cross-channel campaign reporting requires pulling data from multiple analytics platforms manually",
      "Social media management across Twitter, LinkedIn, Instagram, and Reddit fragments attention",
      "Content calendar coordination between writers, designers, and stakeholders is chaotic",
      "Lead follow-up timing is critical but often delayed by inbox overload",
    ],
    howGaiaHelps: [
      {
        title: "Automated Campaign Reporting",
        description:
          "GAIA pulls performance data from PostHog and connected tools, compiles weekly campaign reports, and distributes them via Slack or Gmail. Spend minutes reviewing instead of hours building reports.",
      },
      {
        title: "Social Media Monitoring",
        description:
          "GAIA monitors Twitter, LinkedIn, Reddit, and HackerNews for brand mentions, industry trends, and competitor activity. It surfaces actionable insights and drafts response suggestions.",
      },
      {
        title: "Content Workflow Management",
        description:
          "GAIA tracks content pipeline in Notion or Asana, sends reminders for upcoming deadlines, coordinates review cycles, and ensures your content calendar stays on track.",
      },
      {
        title: "Lead Nurture Automation",
        description:
          "GAIA monitors Gmail for inbound leads, categorizes them by source and intent, drafts personalized responses, and ensures follow-ups happen within your target response time via HubSpot.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "slack",
      "twitter",
      "linkedin",
      "instagram",
      "reddit",
      "hackernews",
      "hubspot",
      "notion",
      "posthog",
      "google-sheets",
      "asana",
    ],
    faqs: [
      {
        question: "Can GAIA replace my marketing automation platform?",
        answer:
          "GAIA complements your existing marketing stack rather than replacing it. It acts as an intelligent orchestration layer that connects your tools, automates data flow, and handles the operational overhead of managing multiple marketing channels.",
      },
      {
        question: "How does GAIA help with social media management?",
        answer:
          "GAIA monitors your social channels for mentions and trends, surfaces engagement opportunities, and drafts responses. It integrates with Twitter, LinkedIn, Instagram, and Reddit to give you a unified view of your social presence.",
      },
      {
        question: "Does GAIA support analytics tracking?",
        answer:
          "Yes. GAIA integrates with PostHog for product analytics and can pull data from connected tools to compile marketing reports. It automates the reporting process so you spend more time on strategy and less on data gathering.",
      },
    ],
  },

  "content-creators": {
    slug: "content-creators",
    title: "AI Assistant for Content Creators",
    role: "Content Creators",
    metaTitle:
      "AI Assistant for Content Creators - Streamline Your Creative Workflow",
    metaDescription:
      "GAIA helps content creators manage publishing schedules, track audience engagement, organize research, and automate the business side of content creation.",
    keywords: [
      "AI assistant for content creators",
      "content creation workflow",
      "creator economy AI",
      "publishing automation",
      "content calendar AI",
    ],
    intro:
      "Content creators are one-person media companies. Whether you publish newsletters, YouTube videos, podcasts, or social media content, the operational demands of scheduling, research, audience engagement, and cross-platform distribution consume time that should go toward creating. The creator economy now exceeds $250 billion globally, yet most creators lack the operational support that traditional media teams provide. GAIA fills that gap as your AI production assistant.",
    painPoints: [
      "Research and ideation consume hours before any content creation begins",
      "Cross-platform publishing and scheduling across social channels is repetitive and error-prone",
      "Audience engagement tracking across Twitter, LinkedIn, Instagram, and Reddit lacks a unified dashboard",
      "Business operations like sponsorship emails, invoicing, and collaboration requests pile up",
    ],
    howGaiaHelps: [
      {
        title: "Research & Ideation Pipeline",
        description:
          "GAIA uses Perplexity and HackerNews integrations to surface trending topics, compile research briefs, and organize ideas in Notion. Start every content session with a structured brief rather than a blank page.",
      },
      {
        title: "Cross-Platform Engagement Tracking",
        description:
          "GAIA monitors Twitter, LinkedIn, Reddit, and Instagram for comments, mentions, and engagement patterns. It surfaces the conversations worth joining and drafts response suggestions.",
      },
      {
        title: "Business Operations Automation",
        description:
          "GAIA triages your Gmail for sponsorship inquiries, collaboration requests, and business emails. It drafts professional responses, tracks negotiations, and ensures no opportunity slips through the cracks.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "twitter",
      "linkedin",
      "instagram",
      "reddit",
      "hackernews",
      "notion",
      "google-calendar",
      "google-docs",
      "todoist",
      "perplexity",
    ],
    faqs: [
      {
        question: "Can GAIA help me create content faster?",
        answer:
          "GAIA accelerates the content creation process by automating research, organizing ideas, and managing the operational overhead around publishing. It handles the logistics so you can focus on the creative work that only you can do.",
      },
      {
        question: "How does GAIA track engagement across platforms?",
        answer:
          "GAIA integrates with Twitter, LinkedIn, Instagram, and Reddit to monitor mentions, comments, and engagement metrics. It consolidates cross-platform data into unified summaries and surfaces the interactions that matter most.",
      },
    ],
  },

  "data-scientists": {
    slug: "data-scientists",
    title: "AI Assistant for Data Scientists",
    role: "Data Scientists",
    metaTitle:
      "AI Assistant for Data Scientists - Automate Data Workflow Operations",
    metaDescription:
      "GAIA helps data scientists manage experiment tracking, automate stakeholder reporting, organize documentation, and reduce operational overhead in data workflows.",
    keywords: [
      "AI assistant for data scientists",
      "data science productivity",
      "ML workflow automation",
      "data team collaboration",
      "data science operations",
    ],
    intro:
      "Data scientists spend an estimated 45% of their time on data preparation and operational tasks according to Anaconda's State of Data Science report, leaving insufficient time for modeling and analysis. Between managing stakeholder expectations, documenting experiments, coordinating with engineering teams, and presenting findings, the operational burden is substantial. GAIA automates the non-analytical aspects of data science work so you can focus on extracting insights.",
    painPoints: [
      "Stakeholder reporting requires translating technical results into business language repeatedly",
      "Experiment documentation falls behind as the pace of iteration increases",
      "Coordination with engineering teams on deployment and data pipeline issues creates bottlenecks",
      "Research paper tracking and literature reviews are time-intensive but essential",
    ],
    howGaiaHelps: [
      {
        title: "Automated Stakeholder Reports",
        description:
          "GAIA compiles experiment results from your documentation in Notion, translates technical findings into business-friendly summaries, and delivers them to stakeholders via Slack or Gmail on your schedule.",
      },
      {
        title: "Research Organization",
        description:
          "GAIA uses Perplexity and DeepWiki to track relevant papers and industry developments. It organizes findings in Notion and alerts you to new research in your focus areas.",
      },
      {
        title: "Cross-Team Coordination",
        description:
          "GAIA monitors Slack and Linear for data pipeline issues, engineering requests, and deployment updates. It ensures you stay connected with engineering teams without constant channel monitoring.",
      },
    ],
    relevantIntegrations: [
      "slack",
      "gmail",
      "notion",
      "google-sheets",
      "google-docs",
      "github",
      "linear",
      "google-calendar",
      "perplexity",
      "deepwiki",
    ],
    faqs: [
      {
        question:
          "Can GAIA integrate with data science tools like Jupyter or MLflow?",
        answer:
          "GAIA focuses on the operational layer around data science work: communication, documentation, reporting, and coordination. It integrates with GitHub for code management and Notion for documentation. Custom MCP integrations can extend GAIA to connect with specialized data science tools.",
      },
      {
        question: "How does GAIA help with research organization?",
        answer:
          "GAIA uses Perplexity for AI-powered research and DeepWiki for documentation discovery. It organizes findings in Notion, creates structured reading lists, and alerts you to new relevant publications in your research areas.",
      },
    ],
  },

  "project-managers": {
    slug: "project-managers",
    title: "AI Assistant for Project Managers",
    role: "Project Managers",
    metaTitle:
      "AI Assistant for Project Managers - Automate Project Operations",
    metaDescription:
      "GAIA helps project managers track deliverables, automate status reports, manage stakeholder communications, and keep distributed teams aligned across all tools.",
    keywords: [
      "AI assistant for project managers",
      "project management automation",
      "status report automation",
      "team coordination AI",
      "project tracking automation",
    ],
    intro:
      "Project managers are the glue that holds teams together, but the PMI Pulse of the Profession report consistently shows that PMs spend over 50% of their time on communication and administrative tasks rather than strategic project oversight. Tracking deliverables across Asana, Linear, or ClickUp while managing stakeholder emails and scheduling meetings creates a coordination tax that scales with every new project. GAIA automates the operational layer of project management.",
    painPoints: [
      "Status report generation requires pulling data from multiple project tools every week",
      "Stakeholder communication across email and Slack channels demands constant attention",
      "Risk identification depends on manually monitoring project boards for blockers and delays",
      "Meeting scheduling and follow-up tracking across distributed teams is time-consuming",
    ],
    howGaiaHelps: [
      {
        title: "Automated Status Reports",
        description:
          "GAIA pulls task completion data from Asana, Linear, or ClickUp, compiles project health summaries, and distributes them via Slack or email. Weekly reports that took hours now take minutes to review.",
      },
      {
        title: "Proactive Risk Monitoring",
        description:
          "GAIA monitors your project boards for overdue tasks, blocked items, and scope changes. It alerts you to potential risks before they escalate and suggests mitigation actions.",
      },
      {
        title: "Meeting & Action Item Management",
        description:
          "GAIA prepares meeting agendas from open items, tracks action items captured during meetings, and follows up with assignees to ensure commitments are kept.",
      },
      {
        title: "Stakeholder Communication",
        description:
          "GAIA drafts stakeholder updates, routes information to the right channels, and ensures decision-makers have the context they need without you manually crafting every message.",
      },
    ],
    relevantIntegrations: [
      "asana",
      "linear",
      "clickup",
      "slack",
      "gmail",
      "google-calendar",
      "google-meet",
      "notion",
      "todoist",
      "trello",
      "microsoft-teams",
    ],
    faqs: [
      {
        question: "Does GAIA replace Asana, Linear, or ClickUp?",
        answer:
          "No. GAIA works alongside your existing project management tools as an intelligent automation layer. It pulls data from these tools, automates reporting, monitors for risks, and handles communication so you can focus on strategic project decisions.",
      },
      {
        question: "How does GAIA handle projects across multiple tools?",
        answer:
          "GAIA integrates with Asana, Linear, ClickUp, Trello, and other project tools simultaneously. It provides a unified view of project health across tools and automates cross-tool workflows like creating tasks from email or Slack messages.",
      },
      {
        question: "Can GAIA help with distributed team coordination?",
        answer:
          "Yes. GAIA understands time zones, monitors async communication channels, ensures handoffs between team members are smooth, and compiles updates that keep distributed teams aligned regardless of geography.",
      },
    ],
  },

  "engineering-managers": {
    slug: "engineering-managers",
    title: "AI Assistant for Engineering Managers",
    role: "Engineering Managers",
    metaTitle: "AI Assistant for Engineering Managers - Scale Your Leadership",
    metaDescription:
      "GAIA helps engineering managers automate sprint reporting, track team velocity, manage 1:1 prep, and stay connected to technical work without micromanaging.",
    keywords: [
      "AI assistant for engineering managers",
      "engineering management automation",
      "sprint reporting AI",
      "team velocity tracking",
      "engineering leadership tool",
    ],
    intro:
      "Engineering managers balance technical leadership with people management, and the split rarely favors deep work. A Jellyfish State of Engineering Management report found that EMs spend an average of 22 hours per week in meetings and communications. Keeping pulse on team health, sprint velocity, PR review times, and cross-team dependencies while preparing for 1:1s and stakeholder meetings creates a constant operational burden. GAIA automates the data gathering and reporting so you can focus on unblocking your team.",
    painPoints: [
      "Sprint retrospective and velocity reporting requires manually aggregating data from Linear and GitHub",
      "Preparing for 1:1s means reviewing each report's recent PRs, tickets, and Slack activity",
      "Cross-team dependency tracking and escalation management consume hours of coordination",
      "Balancing technical context with management responsibilities leads to shallow engagement with both",
    ],
    howGaiaHelps: [
      {
        title: "Sprint Analytics & Reporting",
        description:
          "GAIA aggregates sprint data from Linear and GitHub, including velocity trends, PR cycle times, and completion rates. It generates formatted reports for stakeholders and identifies patterns worth discussing in retros.",
      },
      {
        title: "1:1 Preparation",
        description:
          "Before each 1:1, GAIA compiles a briefing with the team member's recent PRs, completed tickets, open blockers, and any Slack discussions where they were mentioned. Walk into every 1:1 prepared.",
      },
      {
        title: "Dependency & Escalation Tracking",
        description:
          "GAIA monitors Linear and Slack for cross-team blockers, flags dependencies at risk, and helps you escalate issues before they impact delivery timelines.",
      },
    ],
    relevantIntegrations: [
      "github",
      "linear",
      "slack",
      "google-calendar",
      "gmail",
      "notion",
      "google-meet",
      "todoist",
      "google-docs",
    ],
    faqs: [
      {
        question: "How does GAIA help with engineering team metrics?",
        answer:
          "GAIA integrates with GitHub and Linear to track PR cycle times, sprint velocity, ticket completion rates, and deployment frequency. It compiles these metrics into regular reports and highlights trends that need attention.",
      },
      {
        question: "Can GAIA help me stay technical while managing?",
        answer:
          "Yes. GAIA summarizes key technical discussions from Slack and GitHub, surfaces important architectural decisions, and helps you maintain technical context without reading every thread. It keeps you informed without requiring constant channel monitoring.",
      },
    ],
  },

  "sales-professionals": {
    slug: "sales-professionals",
    title: "AI Assistant for Sales Professionals",
    role: "Sales Professionals",
    metaTitle:
      "AI Assistant for Sales Professionals - Close More Deals with AI",
    metaDescription:
      "GAIA helps sales professionals automate CRM updates, manage follow-ups, prepare for calls, and keep pipelines moving with proactive AI assistance.",
    keywords: [
      "AI assistant for sales",
      "sales automation AI",
      "CRM automation tool",
      "sales productivity AI",
      "deal management automation",
    ],
    intro:
      "Sales professionals spend only 28% of their time actually selling according to Salesforce's State of Sales report. The rest goes to CRM data entry, email follow-ups, meeting prep, and administrative tasks. Every minute spent on busywork is a minute not spent building relationships and closing deals. GAIA automates the operational side of sales so you can focus on what generates revenue: meaningful conversations with prospects and customers.",
    painPoints: [
      "CRM data entry and pipeline updates consume hours that should be spent selling",
      "Follow-up timing is critical but easy to miss when managing 50+ active opportunities",
      "Meeting preparation requires manually researching prospects across LinkedIn and company websites",
      "End-of-day and end-of-week reporting takes time away from pipeline building",
    ],
    howGaiaHelps: [
      {
        title: "Automated CRM & Pipeline Updates",
        description:
          "GAIA monitors your Gmail for deal-related conversations and automatically logs interactions to HubSpot. It updates deal stages based on email signals and ensures your pipeline is always current.",
      },
      {
        title: "Intelligent Follow-Up Management",
        description:
          "GAIA tracks every prospect interaction, identifies optimal follow-up timing, drafts personalized follow-up emails, and ensures no deal goes cold due to missed touchpoints.",
      },
      {
        title: "Meeting Preparation Briefs",
        description:
          "Before every sales call, GAIA compiles prospect research from LinkedIn and Perplexity, recent email history, deal context from HubSpot, and talking points tailored to the opportunity stage.",
      },
      {
        title: "Activity Reporting",
        description:
          "GAIA automatically compiles your daily and weekly activity metrics from email, calendar, and CRM into formatted reports for managers, eliminating manual reporting overhead.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "hubspot",
      "google-calendar",
      "slack",
      "linkedin",
      "google-meet",
      "perplexity",
      "google-docs",
      "todoist",
      "google-sheets",
    ],
    faqs: [
      {
        question: "Does GAIA integrate with my CRM?",
        answer:
          "GAIA integrates with HubSpot for CRM management, including logging interactions, updating deal stages, and tracking pipeline metrics. It also connects with Gmail and Google Calendar to capture sales activity automatically.",
      },
      {
        question: "How does GAIA help with follow-up management?",
        answer:
          "GAIA tracks all prospect communications, identifies when follow-ups are due based on your sales cadence, drafts personalized emails, and sends you reminders. It ensures consistent outreach without manual tracking.",
      },
      {
        question: "Can GAIA prepare me for sales calls?",
        answer:
          "Yes. Before every meeting, GAIA compiles a briefing document with prospect background research, recent interaction history, deal stage context, and suggested talking points. You walk into every call prepared and confident.",
      },
    ],
  },

  "customer-success": {
    slug: "customer-success",
    title: "AI Assistant for Customer Success Managers",
    role: "Customer Success Managers",
    metaTitle:
      "AI Assistant for Customer Success - Proactive Account Management",
    metaDescription:
      "GAIA helps customer success managers monitor account health, automate check-in scheduling, track renewal timelines, and deliver proactive support across all channels.",
    keywords: [
      "AI assistant for customer success",
      "customer success automation",
      "account management AI",
      "renewal management tool",
      "CS operations automation",
    ],
    intro:
      "Customer success managers own the critical post-sale relationship that determines retention and expansion. Gainsight's 2024 CS report found that CSMs managing 40+ accounts spend more time on operational tasks than strategic conversations. Tracking account health signals across email, support channels, and usage data while managing QBRs and renewals creates a constant juggling act. GAIA proactively monitors your accounts and surfaces the signals that matter before churn risks materialize.",
    painPoints: [
      "Account health monitoring across email, Slack, and support channels is manually intensive",
      "Renewal timelines sneak up when managing 40+ accounts with different contract dates",
      "QBR preparation requires gathering usage data, support history, and success metrics from multiple sources",
      "Proactive outreach often becomes reactive when operational overhead delays engagement",
    ],
    howGaiaHelps: [
      {
        title: "Account Health Monitoring",
        description:
          "GAIA monitors Gmail and Slack for sentiment signals, tracks engagement patterns, and flags at-risk accounts before they escalate. It creates early warning summaries so you can intervene proactively.",
      },
      {
        title: "Renewal & QBR Preparation",
        description:
          "GAIA tracks renewal dates, compiles account performance data, and prepares QBR presentation materials. It gathers data from HubSpot, Gmail, and Notion to build comprehensive account reviews.",
      },
      {
        title: "Proactive Check-In Scheduling",
        description:
          "GAIA schedules regular check-ins on Google Calendar, prepares agendas based on recent account activity, and drafts personalized outreach emails to maintain consistent customer engagement.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "hubspot",
      "slack",
      "google-calendar",
      "notion",
      "google-meet",
      "google-sheets",
      "google-docs",
      "todoist",
    ],
    faqs: [
      {
        question: "How does GAIA identify at-risk accounts?",
        answer:
          "GAIA monitors email sentiment, response times, support ticket patterns, and engagement frequency across your connected tools. It flags accounts showing early warning signs like decreased communication, negative sentiment, or missed check-ins so you can intervene before churn risks grow.",
      },
      {
        question: "Can GAIA help with QBR preparation?",
        answer:
          "Yes. GAIA compiles usage metrics, support history, communication logs, and success milestones from your connected tools into structured QBR documents. It reduces prep time from hours to minutes.",
      },
    ],
  },

  researchers: {
    slug: "researchers",
    title: "AI Assistant for Researchers",
    role: "Researchers",
    metaTitle: "AI Assistant for Researchers - Accelerate Academic Workflows",
    metaDescription:
      "GAIA helps researchers organize literature, manage citations, coordinate collaborations, and automate the administrative burden of academic research.",
    keywords: [
      "AI assistant for researchers",
      "research workflow automation",
      "academic productivity AI",
      "literature review automation",
      "research collaboration tool",
    ],
    intro:
      "Researchers face mounting pressure to publish, secure funding, and teach simultaneously. A Nature survey found that 84% of researchers feel the administrative burden of academia has increased over the past decade. Between grant applications, literature tracking, peer review management, and collaboration coordination, the operational load can overshadow the intellectual work that drives discovery. GAIA helps researchers reclaim time for what matters: advancing knowledge.",
    painPoints: [
      "Literature tracking across journals, preprint servers, and conferences requires constant vigilance",
      "Collaboration coordination across institutions and time zones relies on email chains",
      "Grant application deadlines and reporting requirements demand meticulous tracking",
      "Peer review requests and editorial correspondence compete for limited attention",
    ],
    howGaiaHelps: [
      {
        title: "Literature Monitoring & Organization",
        description:
          "GAIA uses Perplexity and DeepWiki to track new publications in your research areas, organizes papers in Notion, and creates structured reading lists with summaries of key findings.",
      },
      {
        title: "Collaboration & Communication Management",
        description:
          "GAIA triages research-related emails, schedules co-author meetings across time zones via Google Calendar, and maintains shared documentation in Google Docs with the latest project updates.",
      },
      {
        title: "Grant & Deadline Tracking",
        description:
          "GAIA tracks grant deadlines in Todoist, monitors email for submission confirmations and review notifications, and ensures you never miss a critical academic deadline.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "notion",
      "google-docs",
      "perplexity",
      "deepwiki",
      "todoist",
      "slack",
      "google-sheets",
      "google-meet",
    ],
    faqs: [
      {
        question: "Can GAIA help with literature reviews?",
        answer:
          "GAIA uses Perplexity for AI-powered research and DeepWiki for technical documentation. It tracks new publications in your field, organizes papers in Notion, creates structured summaries, and helps you maintain a comprehensive and current understanding of your research landscape.",
      },
      {
        question: "How does GAIA handle academic collaboration?",
        answer:
          "GAIA coordinates multi-institution collaborations by managing email communications, scheduling meetings across time zones, maintaining shared documents, and tracking action items from research meetings. It ensures smooth collaboration without constant manual coordination.",
      },
    ],
  },

  consultants: {
    slug: "consultants",
    title: "AI Assistant for Consultants",
    role: "Consultants",
    metaTitle: "AI Assistant for Consultants - Maximize Billable Utilization",
    metaDescription:
      "GAIA helps consultants manage client engagements, automate deliverable tracking, prepare for meetings, and reduce non-billable administrative overhead.",
    keywords: [
      "AI assistant for consultants",
      "consulting productivity tool",
      "client engagement automation",
      "consulting workflow AI",
      "billable utilization tool",
    ],
    intro:
      "Consultants sell their expertise by the hour, making non-billable time directly expensive. McKinsey research suggests that management consultants spend up to 40% of their time on internal operations, client communication management, and deliverable coordination rather than strategic advisory work. GAIA maximizes your billable utilization by automating the operational overhead of consulting engagements.",
    painPoints: [
      "Client communication across email and Slack for multiple simultaneous engagements is overwhelming",
      "Deliverable tracking and milestone management require constant manual updates",
      "Meeting preparation demands researching client context across scattered notes and documents",
      "Proposal and report writing involves repetitive formatting and data compilation tasks",
    ],
    howGaiaHelps: [
      {
        title: "Multi-Client Communication Management",
        description:
          "GAIA organizes email and Slack messages by client and engagement, drafts responses for routine communications, and ensures no client message exceeds your target response time.",
      },
      {
        title: "Engagement & Deliverable Tracking",
        description:
          "GAIA tracks deliverable milestones in Todoist or Asana, monitors deadlines, and sends proactive alerts when deliverables are approaching. It keeps engagement timelines visible and manageable.",
      },
      {
        title: "Client Meeting Intelligence",
        description:
          "Before every client meeting, GAIA compiles a briefing with recent communications, open action items, deliverable status, and relevant research from Perplexity. You arrive prepared for every conversation.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "slack",
      "todoist",
      "asana",
      "notion",
      "google-docs",
      "google-sheets",
      "google-meet",
      "perplexity",
    ],
    faqs: [
      {
        question: "How does GAIA help consultants manage multiple clients?",
        answer:
          "GAIA organizes all communications and tasks by client engagement, provides per-client dashboards of activity and deliverable status, and ensures you maintain high responsiveness across all engagements without dropping any balls.",
      },
      {
        question: "Can GAIA track billable vs non-billable time?",
        answer:
          "GAIA monitors your calendar and task completions to help categorize time spent. While it is not a time-tracking tool, it automates the administrative tasks that typically consume non-billable hours, effectively increasing your utilization rate.",
      },
    ],
  },

  "agency-owners": {
    slug: "agency-owners",
    title: "AI Assistant for Agency Owners",
    role: "Agency Owners",
    metaTitle: "AI Assistant for Agency Owners - Scale Operations Efficiently",
    metaDescription:
      "GAIA helps agency owners manage client portfolios, automate project reporting, coordinate distributed teams, and streamline new business development.",
    keywords: [
      "AI assistant for agency owners",
      "agency management automation",
      "client portfolio management AI",
      "agency operations tool",
      "digital agency productivity",
    ],
    intro:
      "Agency owners manage the complexity of multiple client relationships, team coordination, business development, and financial oversight simultaneously. Agency Management Institute data shows that most agency owners spend less than 20% of their time on growth-driving activities because operational demands consume the majority of their week. GAIA acts as your AI operations manager, automating client reporting, team coordination, and administrative tasks so you can focus on growing your agency.",
    painPoints: [
      "Client reporting across a portfolio of accounts requires compiling data from diverse tools weekly",
      "Team utilization tracking and resource allocation across projects is a manual spreadsheet exercise",
      "New business development suffers when operational firefighting consumes available time",
      "Cross-client communication management across email and Slack creates constant context-switching",
    ],
    howGaiaHelps: [
      {
        title: "Portfolio-Wide Client Reporting",
        description:
          "GAIA aggregates project data from ClickUp, Asana, or Trello across all client accounts and generates formatted status reports. Distribute them via Gmail or Slack on a consistent schedule.",
      },
      {
        title: "Team Coordination & Communication",
        description:
          "GAIA monitors Slack channels and project boards for blockers, compiles daily team summaries, and ensures project managers have the context they need to keep engagements on track.",
      },
      {
        title: "Business Development Support",
        description:
          "GAIA triages inbound leads via Gmail, researches prospects using Perplexity and LinkedIn, and drafts initial outreach responses. It ensures your pipeline stays active even during busy delivery periods.",
      },
      {
        title: "Operational Intelligence",
        description:
          "GAIA provides daily briefings across all active engagements, flags at-risk projects, and surfaces the information you need to make resource allocation decisions quickly.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "slack",
      "clickup",
      "asana",
      "trello",
      "google-calendar",
      "notion",
      "google-sheets",
      "linkedin",
      "perplexity",
      "hubspot",
      "google-meet",
    ],
    faqs: [
      {
        question: "Can GAIA handle reporting for multiple clients?",
        answer:
          "Yes. GAIA organizes projects by client and generates individual client reports pulling data from your project management tools. It scales to any number of client accounts and maintains separate context for each engagement.",
      },
      {
        question: "How does GAIA help with new business development?",
        answer:
          "GAIA triages inbound leads, researches prospects, drafts initial outreach emails, and tracks the sales pipeline via HubSpot. It ensures business development activities continue consistently even during heavy delivery periods.",
      },
    ],
  },

  "indie-hackers": {
    slug: "indie-hackers",
    title: "AI Assistant for Indie Hackers",
    role: "Indie Hackers",
    metaTitle:
      "AI Assistant for Indie Hackers - Ship Faster, Automate Operations",
    metaDescription:
      "GAIA helps indie hackers automate customer support, monitor product metrics, manage launches, and handle the operational overhead of building products solo.",
    keywords: [
      "AI assistant for indie hackers",
      "solo developer productivity",
      "indie hacker automation",
      "bootstrapped startup AI",
      "build in public AI tool",
    ],
    intro:
      "Indie hackers build, launch, market, support, and grow products single-handedly. Every operational task you handle manually is time not spent shipping features or talking to users. The most successful indie hackers automate relentlessly. GAIA acts as your AI co-founder, handling customer emails, monitoring product metrics, managing your social presence, and keeping the operational side of your business running while you focus on building.",
    painPoints: [
      "Customer support emails compete with development time, and both suffer",
      "Launch coordination across Product Hunt, Twitter, HackerNews, and Reddit requires simultaneous attention",
      "Product analytics monitoring and metric tracking happen sporadically instead of systematically",
      "Marketing and community engagement feel like separate full-time jobs on top of building",
    ],
    howGaiaHelps: [
      {
        title: "Customer Support Automation",
        description:
          "GAIA triages support emails, drafts responses for common questions, flags urgent issues, and ensures every customer gets a timely response without you monitoring Gmail constantly.",
      },
      {
        title: "Launch & Marketing Coordination",
        description:
          "GAIA monitors Twitter, HackerNews, and Reddit for mentions of your product, alerts you to conversations worth joining, and helps coordinate launch activities across platforms.",
      },
      {
        title: "Metrics & Health Monitoring",
        description:
          "GAIA integrates with PostHog for product analytics, compiles daily metric summaries, and alerts you to significant changes in user behavior or conversion rates.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "github",
      "twitter",
      "hackernews",
      "reddit",
      "posthog",
      "todoist",
      "notion",
      "google-calendar",
      "slack",
      "google-sheets",
    ],
    faqs: [
      {
        question: "Is GAIA affordable for bootstrapped indie hackers?",
        answer:
          "GAIA offers a free tier with core features, and you can self-host GAIA entirely free on your own infrastructure. For bootstrapped builders, the self-hosting option provides full functionality at zero cost beyond hosting.",
      },
      {
        question: "How does GAIA help with build-in-public workflows?",
        answer:
          "GAIA monitors your GitHub activity, product metrics, and social channels. It can help you compile weekly progress updates, track public milestones, and engage with your community across Twitter, HackerNews, and Reddit.",
      },
    ],
  },

  solopreneurs: {
    slug: "solopreneurs",
    title: "AI Assistant for Solopreneurs",
    role: "Solopreneurs",
    metaTitle: "AI Assistant for Solopreneurs - Run Your Business on Autopilot",
    metaDescription:
      "GAIA helps solopreneurs manage email, automate client workflows, handle scheduling, and run business operations with AI-powered efficiency as a team of one.",
    keywords: [
      "AI assistant for solopreneurs",
      "solopreneur automation",
      "one-person business AI",
      "solo business productivity",
      "solopreneur workflow tool",
    ],
    intro:
      "Solopreneurs generate revenue that rivals small teams, but they do it alone. A Hiscox survey found that the average solopreneur works 52 hours per week, with nearly half that time spent on business operations rather than revenue-generating work. GAIA functions as your AI team, handling email management, client scheduling, task coordination, and administrative overhead so your solo operation runs with the efficiency of a fully-staffed business.",
    painPoints: [
      "Every operational task falls on you, from invoicing to customer support to marketing",
      "Email inbox becomes a bottleneck when client communications, vendor emails, and admin pile up",
      "Scheduling conflicts and double-bookings happen without a dedicated operations person",
      "Business growth stalls when you cannot free enough time from operations for strategy and sales",
    ],
    howGaiaHelps: [
      {
        title: "Comprehensive Email Management",
        description:
          "GAIA reads, categorizes, and prioritizes every email. It drafts responses for routine messages, flags urgent items, and ensures your inbox never becomes a bottleneck for your business.",
      },
      {
        title: "Client Scheduling & Follow-ups",
        description:
          "GAIA manages your Google Calendar, handles client scheduling requests, sends appointment reminders, and drafts follow-up emails after meetings to maintain professional client relationships.",
      },
      {
        title: "Task & Workflow Automation",
        description:
          "GAIA creates recurring tasks in Todoist, automates multi-step business workflows, and proactively manages your to-do list so nothing slips through the cracks of your one-person operation.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "todoist",
      "notion",
      "google-sheets",
      "google-docs",
      "slack",
      "google-meet",
      "hubspot",
      "google-tasks",
    ],
    faqs: [
      {
        question: "Can GAIA really replace a virtual assistant?",
        answer:
          "For many operational tasks, yes. GAIA handles email triage, scheduling, task management, and follow-ups 24/7 without breaks. It learns your preferences through graph-based memory and improves over time. For tasks requiring human judgment or creativity, GAIA drafts and you approve.",
      },
      {
        question: "How quickly can a solopreneur set up GAIA?",
        answer:
          "GAIA can be set up in minutes. Connect your Gmail, Google Calendar, and task management tools, and GAIA begins learning your patterns immediately. Most solopreneurs see productivity gains within the first week.",
      },
    ],
  },

  "operations-managers": {
    slug: "operations-managers",
    title: "AI Assistant for Operations Managers",
    role: "Operations Managers",
    metaTitle:
      "AI Assistant for Operations Managers - Streamline Operational Workflows",
    metaDescription:
      "GAIA helps operations managers automate process monitoring, streamline vendor communications, track KPIs, and reduce manual operational overhead across teams.",
    keywords: [
      "AI assistant for operations managers",
      "operations automation AI",
      "process management tool",
      "operational efficiency AI",
      "ops workflow automation",
    ],
    intro:
      "Operations managers ensure the machinery of business runs smoothly, but the role is inherently reactive. McKinsey research on operational excellence shows that companies with automated operations workflows achieve 25% higher efficiency than those relying on manual processes. GAIA brings AI-powered automation to your operational workflows, proactively monitoring processes, managing vendor communications, and surfacing the data you need to keep operations running at peak efficiency.",
    painPoints: [
      "Process monitoring across systems requires manual checks and spreadsheet-based tracking",
      "Vendor communication management across dozens of email threads is time-consuming",
      "KPI tracking and operational reporting demand weekly data compilation from multiple sources",
      "Cross-departmental coordination on operational initiatives relies heavily on email and meetings",
    ],
    howGaiaHelps: [
      {
        title: "Automated Process Monitoring",
        description:
          "GAIA monitors your connected tools for process anomalies, tracks operational metrics via Google Sheets and Airtable, and sends proactive alerts when KPIs deviate from targets.",
      },
      {
        title: "Vendor Communication Management",
        description:
          "GAIA organizes vendor emails by relationship and priority, drafts routine responses, tracks order statuses, and ensures timely follow-ups on outstanding requests.",
      },
      {
        title: "Operational Reporting Automation",
        description:
          "GAIA compiles operational data from your connected tools into formatted reports, distributes them to stakeholders via Slack or email, and maintains historical tracking in Google Sheets.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "slack",
      "google-sheets",
      "airtable",
      "google-calendar",
      "notion",
      "todoist",
      "microsoft-teams",
      "asana",
      "google-docs",
    ],
    faqs: [
      {
        question: "How does GAIA integrate with existing operational systems?",
        answer:
          "GAIA connects to your operational tools through MCP integrations, including Google Sheets, Airtable, Slack, and email. It acts as an intelligent automation layer on top of your existing systems without requiring you to replace anything.",
      },
      {
        question: "Can GAIA help with vendor management?",
        answer:
          "Yes. GAIA organizes vendor communications, tracks response timelines, drafts follow-up messages, and maintains vendor interaction history. It ensures consistent vendor management without the manual overhead of tracking dozens of email threads.",
      },
    ],
  },

  "team-leads": {
    slug: "team-leads",
    title: "AI Assistant for Team Leads",
    role: "Team Leads",
    metaTitle: "AI Assistant for Team Leads - Empower Your Team with AI",
    metaDescription:
      "GAIA helps team leads manage team communication, automate standup collection, track deliverables, and maintain alignment across distributed teams.",
    keywords: [
      "AI assistant for team leads",
      "team leadership automation",
      "standup automation AI",
      "team management tool",
      "team coordination AI",
    ],
    intro:
      "Team leads occupy the critical middle layer between individual contributors and management. Atlassian's research on team effectiveness shows that team leads spend an average of 62% of their time on coordination and communication rather than their own deliverables. Collecting standups, tracking team progress, managing blockers, and communicating upward creates a coordination tax that grows with team size. GAIA automates the coordination layer so you can focus on coaching, mentoring, and removing obstacles for your team.",
    painPoints: [
      "Daily standup collection and compilation across team members is repetitive and time-consuming",
      "Tracking individual team member progress across Linear, GitHub, and Slack requires constant context-switching",
      "Communicating team status upward to management demands regular report formatting",
      "Balancing individual contributor work with team coordination leaves insufficient time for both",
    ],
    howGaiaHelps: [
      {
        title: "Automated Standup Collection",
        description:
          "GAIA gathers daily updates from team members via Slack, compiles them into formatted standup summaries, and identifies blockers that need your attention. No more chasing people for updates.",
      },
      {
        title: "Team Progress Visibility",
        description:
          "GAIA monitors Linear and GitHub for your team's activity, provides real-time progress snapshots, and flags items at risk of missing deadlines before they become problems.",
      },
      {
        title: "Upward Reporting",
        description:
          "GAIA compiles weekly team performance reports from your project tools, formats them for management consumption, and delivers them via email or Slack on your preferred schedule.",
      },
    ],
    relevantIntegrations: [
      "slack",
      "linear",
      "github",
      "google-calendar",
      "gmail",
      "notion",
      "google-meet",
      "todoist",
      "asana",
      "clickup",
    ],
    faqs: [
      {
        question: "How does GAIA collect standups from my team?",
        answer:
          "GAIA monitors your team's Slack activity and project tool updates (Linear, GitHub) to compile daily progress summaries. It can also prompt team members directly in Slack for updates and compile the responses into a formatted standup report.",
      },
      {
        question: "Can GAIA help me identify team blockers early?",
        answer:
          "Yes. GAIA monitors project boards for stalled tickets, tracks PR review times on GitHub, and surfaces Slack conversations about blockers. It proactively alerts you to issues before they impact team velocity.",
      },
    ],
  },

  executives: {
    slug: "executives",
    title: "AI Assistant for Executives",
    role: "Executives",
    metaTitle:
      "AI Assistant for Executives - Strategic Intelligence on Autopilot",
    metaDescription:
      "GAIA helps executives manage information overload, automate meeting prep, streamline communication, and maintain strategic focus amidst operational demands.",
    keywords: [
      "AI assistant for executives",
      "executive productivity AI",
      "CEO assistant tool",
      "executive communication automation",
      "C-suite productivity",
    ],
    intro:
      "Executives make decisions that shape entire organizations, yet a Harvard Business Review study found that CEOs have only 28% of their time for actual strategic work. The rest is consumed by email, meetings, travel, and operational firefighting. The quality of executive decisions depends directly on the quality and timeliness of information they receive. GAIA acts as your AI executive assistant, ensuring you have the right information at the right time while automating the operational overhead that fragments your attention.",
    painPoints: [
      "Email volume at the executive level exceeds 200+ messages daily, with critical items buried in noise",
      "Meeting preparation across board meetings, investor calls, and team reviews requires extensive briefings",
      "Information from direct reports, market intelligence, and internal systems arrives in fragmented streams",
      "Strategic thinking time is constantly eroded by operational demands and urgent requests",
    ],
    howGaiaHelps: [
      {
        title: "Executive Email Intelligence",
        description:
          "GAIA processes every email through an urgency and strategic importance filter. It drafts responses for routine correspondence, escalates critical items immediately, and provides a daily email digest organized by priority.",
      },
      {
        title: "Meeting Preparation & Follow-up",
        description:
          "Before every meeting, GAIA compiles comprehensive briefings with relevant data, recent communications, and context from your connected tools. After meetings, it captures action items and tracks their completion.",
      },
      {
        title: "Strategic Information Synthesis",
        description:
          "GAIA monitors Slack, email, and connected tools for strategic signals, industry developments via Perplexity, and team performance indicators. It delivers morning intelligence briefs so you start every day informed.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "slack",
      "notion",
      "google-meet",
      "google-docs",
      "google-sheets",
      "perplexity",
      "linkedin",
      "todoist",
    ],
    faqs: [
      {
        question: "How does GAIA handle confidential executive communications?",
        answer:
          "GAIA is fully open source and self-hostable. Executives can deploy GAIA on dedicated infrastructure with enterprise-grade security controls, ensuring complete confidentiality. No data is shared with third parties or used for model training.",
      },
      {
        question:
          "Can GAIA integrate with an existing executive assistant's workflow?",
        answer:
          "Yes. GAIA complements human executive assistants by handling high-volume tasks like email triage, meeting prep compilation, and information synthesis. Your EA can focus on relationship management and high-touch coordination while GAIA handles data-intensive operational tasks.",
      },
      {
        question: "How does GAIA prioritize information for executives?",
        answer:
          "GAIA uses AI to assess urgency, strategic relevance, and sender importance. It learns your priorities over time through graph-based memory, ensuring the information hierarchy it presents aligns with your actual decision-making needs.",
      },
    ],
  },

  "real-estate-agents": {
    slug: "real-estate-agents",
    title: "AI Assistant for Real Estate Agents",
    role: "Real Estate Agents",
    metaTitle: "AI Assistant for Real Estate Agents - Close More Deals with AI",
    metaDescription:
      "GAIA helps real estate agents manage leads, automate follow-ups, schedule showings, and keep clients informed with proactive AI-powered communication management.",
    keywords: [
      "AI assistant for real estate agents",
      "real estate automation",
      "real estate CRM AI",
      "showing scheduler AI",
      "real estate lead management",
    ],
    intro:
      "Real estate is a relationship-driven business where response time directly impacts conversion rates. NAR research shows that agents who respond to leads within 5 minutes are 21x more likely to convert them compared to 30-minute response times. Yet most agents manage 20+ active clients while prospecting for new business, making instant response nearly impossible without automation. GAIA ensures every lead gets a prompt response and every client stays informed throughout their transaction.",
    painPoints: [
      "Lead response time suffers when juggling showings, closings, and client calls simultaneously",
      "Client communication across email, text, and phone creates scattered conversation histories",
      "Showing scheduling and coordination with listing agents consumes hours of back-and-forth",
      "Market updates and neighborhood information need to be shared proactively with active buyers",
    ],
    howGaiaHelps: [
      {
        title: "Instant Lead Response",
        description:
          "GAIA monitors Gmail for new lead inquiries and drafts personalized initial responses within minutes. It categorizes leads by intent and urgency, ensuring hot leads receive immediate attention.",
      },
      {
        title: "Client Communication Tracking",
        description:
          "GAIA organizes all client communications from Gmail and Slack into per-client timelines, tracks last contact dates, and prompts you to reach out when clients have gone quiet.",
      },
      {
        title: "Showing & Meeting Coordination",
        description:
          "GAIA manages your Google Calendar for showings, coordinates scheduling with listing agents via email, sends confirmation and reminder messages, and prepares property briefings using Google Maps and Yelp neighborhood data.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "google-maps",
      "yelp",
      "google-docs",
      "google-sheets",
      "todoist",
      "hubspot",
      "slack",
      "google-meet",
    ],
    faqs: [
      {
        question:
          "How does GAIA help real estate agents respond to leads faster?",
        answer:
          "GAIA monitors your email inbox 24/7 for new lead inquiries and drafts personalized responses immediately. While you are at a showing, GAIA ensures every new lead receives a professional, timely response that keeps them engaged until you can follow up personally.",
      },
      {
        question: "Can GAIA help with property research?",
        answer:
          "Yes. GAIA integrates with Google Maps and Yelp to compile neighborhood information, nearby amenities, and area insights. It can prepare property briefings and area comparisons to share with buyers.",
      },
      {
        question: "Does GAIA integrate with real estate CRMs?",
        answer:
          "GAIA integrates with HubSpot for CRM management and can track client relationships through Gmail. Custom MCP integrations can connect GAIA to specialized real estate platforms.",
      },
    ],
  },

  lawyers: {
    slug: "lawyers",
    title: "AI Assistant for Lawyers",
    role: "Lawyers",
    metaTitle: "AI Assistant for Lawyers - Maximize Billable Hours with AI",
    metaDescription:
      "GAIA helps lawyers manage client communications, track deadlines, automate document workflows, and reduce the administrative burden of legal practice.",
    keywords: [
      "AI assistant for lawyers",
      "legal productivity AI",
      "law practice automation",
      "legal deadline tracking",
      "lawyer workflow tool",
    ],
    intro:
      "Lawyers face the dual pressure of maximizing billable hours while managing extensive administrative requirements. The Clio Legal Trends Report consistently shows that lawyers bill only 2.5 hours of an 8-hour workday on average, with the remainder consumed by email, document management, scheduling, and administrative tasks. GAIA automates the non-billable operational work of legal practice so you can spend more time on the substantive legal work that clients value and you can bill.",
    painPoints: [
      "Client communication management across email chains for multiple cases is overwhelming",
      "Court deadlines, filing dates, and statute of limitations tracking requires meticulous attention",
      "Document organization and version control across cases creates administrative overhead",
      "Billing and time tracking interruptions fragment focus on substantive legal work",
    ],
    howGaiaHelps: [
      {
        title: "Client Communication Management",
        description:
          "GAIA organizes client emails by case matter, drafts responses for routine inquiries, tracks response deadlines, and ensures no client communication falls through the cracks of a busy practice.",
      },
      {
        title: "Deadline & Calendar Management",
        description:
          "GAIA tracks critical deadlines in Todoist and Google Calendar, sends proactive reminders with sufficient lead time, and ensures filing dates and court appearances are never missed.",
      },
      {
        title: "Document Workflow Automation",
        description:
          "GAIA organizes case documents in Google Docs and Notion, tracks document versions, and manages review workflows. It ensures the right documents are prepared and accessible when you need them.",
      },
      {
        title: "Research Assistance",
        description:
          "GAIA leverages Perplexity for legal research queries, organizes findings by case matter in Notion, and helps you build research memos more efficiently.",
      },
    ],
    relevantIntegrations: [
      "gmail",
      "google-calendar",
      "google-docs",
      "notion",
      "todoist",
      "google-sheets",
      "perplexity",
      "google-meet",
      "slack",
      "google-tasks",
    ],
    faqs: [
      {
        question: "Is GAIA secure enough for attorney-client communications?",
        answer:
          "GAIA is fully open source and self-hostable. Law firms can deploy GAIA on their own infrastructure with full data sovereignty, ensuring attorney-client privilege is maintained. No data is ever shared with third parties or used for training.",
      },
      {
        question: "How does GAIA help lawyers track deadlines?",
        answer:
          "GAIA monitors your email for deadline-related communications, creates tasks with due dates in Todoist or Google Tasks, and sends proactive reminders with configurable lead times. It ensures critical legal deadlines like filing dates and statute of limitations are tracked reliably.",
      },
      {
        question: "Can GAIA help with legal research?",
        answer:
          "GAIA integrates with Perplexity for AI-powered research and organizes findings in Notion. While it does not replace specialized legal research platforms, it accelerates the research process and helps organize findings by case matter for easy reference.",
      },
    ],
  },
};

export function getPersona(slug: string): PersonaData | undefined {
  return personas[slug];
}

export function getAllPersonaSlugs(): string[] {
  return Object.keys(personas);
}

export function getAllPersonas(): PersonaData[] {
  return Object.values(personas);
}
