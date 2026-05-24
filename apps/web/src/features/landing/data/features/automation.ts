import type { FeatureData } from "../featuresData";

export const AUTOMATION_FEATURES: FeatureData[] = [
  {
    slug: "workflows",
    category: "Automation",
    icon: "WorkflowSquare10Icon",
    title: "Workflows",
    tagline: "Describe an automation in plain language — GAIA builds it",
    headline: "Describe the automation. GAIA builds it.",
    subheadline:
      "Tell GAIA what you want automated in plain language — it generates the steps, picks the integrations, configures the trigger, and runs it on schedule.",
    benefits: [
      {
        icon: "LanguageCircleIcon",
        title: "Plain language creation",
        description:
          "Write one sentence, get a complete multi-step workflow back.",
      },
      {
        icon: "Zap01Icon",
        title: "11+ trigger types",
        description:
          "Schedule, Gmail, Slack, GitHub, Google Sheets, Linear, Notion, Todoist, Asana, and more.",
      },
      {
        icon: "Clock01Icon",
        title: "Full execution history",
        description:
          "Every run logged with status, duration, summary, and conversation link.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Describe what to automate",
        description: "Tell GAIA what you want in plain language, one sentence.",
      },
      {
        number: "02",
        title: "GAIA generates steps and selects trigger",
        description:
          "Agent builds the workflow, picks integrations, sets the trigger.",
      },
      {
        number: "03",
        title: "Activate and it runs on schedule",
        description:
          "One click to activate. GAIA runs it automatically from that point on.",
      },
    ],
    faqs: [
      {
        question: "Can I edit a workflow after GAIA generates it?",
        answer:
          "Yes. Each step is editable — change the action, modify parameters, reorder steps, or add new ones before activating.",
      },
      {
        question: "What happens when a workflow step fails?",
        answer:
          "The workflow stops at the failed step, logs the error, and sends a notification. Previous steps that succeeded are not rolled back.",
      },
      {
        question: "Can I trigger a workflow manually instead of on a schedule?",
        answer:
          "Yes. Any workflow can be run manually from the workflows list with a single click, regardless of its configured trigger.",
      },
      {
        question: "How many workflows can I have running at once?",
        answer:
          "There is no hard cap on active workflows. Concurrent execution limits depend on your plan tier.",
      },
    ],
    useCases: [
      {
        title: "Auto-triage incoming GitHub issues",
        description:
          "When a new issue is opened, a workflow reads it, assigns a label, creates a Linear ticket, and posts a Slack notification — all in under 10 seconds.",
      },
      {
        title: "Weekly competitive intelligence digest",
        description:
          "Every Friday, a workflow searches for news about three competitors, summarizes findings, and posts a formatted digest to a Slack channel.",
      },
      {
        title: "New lead enrichment pipeline",
        description:
          "When a new HubSpot contact is created, a workflow researches the company, fills in missing fields, and assigns the contact to the right sales rep.",
      },
    ],
    relatedSlugs: ["scheduled-automation", "event-triggers", "integrations"],
    demoComponent: "workflows",
  },
  {
    slug: "scheduled-automation",
    category: "Automation",
    icon: "Clock01Icon",
    title: "Scheduled Automation",
    tagline: "Run any task daily, weekly, or on any custom schedule",
    headline: "Set it once. Run it forever.",
    subheadline:
      "Schedule any GAIA workflow to run at any frequency — from every 5 minutes to once a month — with per-workflow timezone support and execution tracking.",
    benefits: [
      {
        icon: "Calendar02Icon",
        title: "Visual cron builder",
        description:
          "Build schedules with a UI picker or write a cron expression directly.",
      },
      {
        icon: "GlobalIcon",
        title: "Per-workflow timezones",
        description:
          "Each workflow has its own timezone so global teams get briefings at the right local time.",
      },
      {
        icon: "Analytics01Icon",
        title: "Execution monitoring",
        description:
          "See every past run: when it fired, duration, success/failure, and what it produced.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Set a schedule in plain language",
        description:
          "Tell GAIA when to run — daily at 8am, every weekday, first Monday of the month — or use the visual cron builder.",
      },
      {
        number: "02",
        title: "Attach any workflow to the schedule",
        description:
          "Select an existing workflow or create a new one and link it to the trigger.",
      },
      {
        number: "03",
        title: "GAIA runs it automatically on time",
        description:
          "Each execution fires at the scheduled time, logs the result, and notifies you of any failures.",
      },
    ],
    faqs: [
      {
        question: "What is the shortest supported schedule interval?",
        answer:
          "Every 5 minutes. Shorter intervals are not supported to prevent runaway execution costs.",
      },
      {
        question: "What happens if a scheduled run fails?",
        answer:
          "GAIA logs the failure with an error message and marks the run as failed in the execution history. It does not retry automatically — trigger a manual re-run from the history panel.",
      },
      {
        question: "Can I pause a schedule without deleting it?",
        answer:
          "Yes. Each scheduled workflow has an active/paused toggle. Pausing stops future runs but preserves the schedule and all past execution history.",
      },
      {
        question: "Does each workflow have its own timezone?",
        answer:
          "Yes. Each workflow has a timezone setting independent of your account timezone. Run one workflow at 9am New York time and another at 9am London time simultaneously.",
      },
    ],
    useCases: [
      {
        title: "Daily sales pipeline digest",
        description:
          "A sales manager schedules a 7am workflow that pulls open deals from HubSpot and new emails from high-value contacts, delivering a briefing card before the day starts.",
      },
      {
        title: "Weekly GitHub PR summary to Slack",
        description:
          "An engineering team schedules a Friday 5pm run that queries all open PRs across their repos and posts a formatted summary to their Slack #engineering channel.",
      },
      {
        title: "Monthly expense report generation",
        description:
          "An operations lead schedules a first-of-month workflow that pulls transaction data, generates a formatted PDF, and emails it to the finance team automatically.",
      },
    ],
    relatedSlugs: ["workflows", "event-triggers", "proactive-ai"],
    demoComponent: "scheduled-automation",
  },
  {
    slug: "event-triggers",
    category: "Automation",
    icon: "FlashIcon",
    title: "Event Triggers",
    tagline: "React instantly when something happens across your tools",
    headline: "When X happens, GAIA handles it.",
    subheadline:
      "Wire workflows to fire the moment a new email arrives, a PR is opened, a Notion page is updated, or any other event across your connected apps.",
    benefits: [
      {
        icon: "Mail01Icon",
        title: "Gmail triggers",
        description:
          "Fire when new email arrives: process, categorize, reply, or create a task.",
      },
      {
        icon: "SourceCodeSquareIcon",
        title: "GitHub and Linear",
        description:
          "Trigger on PRs, issues, commits, or status changes automatically.",
      },
      {
        icon: "MessageMultiple02Icon",
        title: "Slack and Sheets",
        description:
          "React to new messages or row additions for data pipelines and alerts.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Connect the source app as a trigger",
        description:
          "Select Gmail, GitHub, Slack, Notion, or any connected integration as the event source.",
      },
      {
        number: "02",
        title: "Define the event condition",
        description:
          "Specify which event fires the workflow — a new email from a specific sender, a PR merge, a Slack message in a specific channel.",
      },
      {
        number: "03",
        title: "Workflow runs the moment the event fires",
        description:
          "GAIA detects the event in real time and executes the linked workflow immediately.",
      },
    ],
    faqs: [
      {
        question: "How quickly does GAIA react to an event?",
        answer:
          "Most triggers fire within seconds of the event. Gmail triggers poll every 60 seconds; webhook-based triggers like GitHub and Slack react in near real time.",
      },
      {
        question:
          "Can I filter triggers so they only fire on specific conditions?",
        answer:
          "Yes. Gmail triggers support sender, subject, and label filters. GitHub triggers support event type and branch filters. Slack triggers support channel and keyword filters.",
      },
      {
        question:
          "What happens if the same event fires while the workflow is still running?",
        answer:
          "Each event creates a separate workflow run. Concurrent runs are allowed. If you want to prevent that, set a cooldown period on the trigger.",
      },
      {
        question: "Can one event trigger multiple workflows?",
        answer:
          "Yes. Multiple workflows can listen to the same event. Each fires independently when the condition matches.",
      },
    ],
    useCases: [
      {
        title: "Auto-label and reply to support emails",
        description:
          "A support team wires a Gmail trigger so every email with 'bug' in the subject gets labeled, a task created in Linear, and an acknowledgment reply sent — all in under 10 seconds.",
      },
      {
        title: "PR merge notification to Slack",
        description:
          "A developer links a GitHub PR-merged event to a workflow that posts a formatted Slack message with the PR title, author, and a diff summary to the team channel.",
      },
      {
        title: "CRM update on new client email",
        description:
          "A salesperson connects Gmail to trigger a workflow when an email arrives from a HubSpot contact, automatically updating the contact's last-activity date and adding a note.",
      },
    ],
    relatedSlugs: ["workflows", "scheduled-automation", "integrations"],
    demoComponent: "event-triggers",
  },
  {
    slug: "document-generation",
    category: "Automation",
    icon: "FileEditIcon",
    title: "Document Generation",
    tagline: "Generate PDFs, DOCX, and HTML from any conversation",
    headline: "Any conversation becomes a document.",
    subheadline:
      "Ask GAIA to generate a report, spec, or export — it produces a fully formatted PDF, DOCX, or HTML file, ready to download instantly.",
    benefits: [
      {
        icon: "File01Icon",
        title: "Six formats",
        description:
          "PDF, DOCX, ODT, HTML, TXT, or EPUB with font, margin, and paper size options.",
      },
      {
        icon: "ListViewIcon",
        title: "Structured output",
        description:
          "Table of contents, section numbering, and clean formatting generated automatically.",
      },
      {
        icon: "Download01Icon",
        title: "Instant download",
        description:
          "Document uploaded to CDN and linked directly in chat. One click to download or share.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Ask GAIA to generate a document",
        description:
          "Request a report, spec, meeting notes, or any structured output in natural language.",
      },
      {
        number: "02",
        title: "GAIA formats and structures the content",
        description:
          "Content is organized with headings, sections, a table of contents, and proper formatting for the target file format.",
      },
      {
        number: "03",
        title: "Download or share from chat",
        description:
          "The document is uploaded to CDN and a download link appears inline in the conversation.",
      },
    ],
    faqs: [
      {
        question: "What file formats are supported?",
        answer:
          "PDF, DOCX, ODT, HTML, TXT, and EPUB. Each format supports options for fonts, margins, and paper size.",
      },
      {
        question:
          "Can GAIA generate documents from data pulled by other tools?",
        answer:
          "Yes. Ask GAIA to pull data from Gmail, Google Sheets, or any connected integration and include it in the document. The generation step happens after data retrieval.",
      },
      {
        question: "Is there a size limit on generated documents?",
        answer:
          "Documents up to approximately 50,000 words are supported. For larger outputs, generate in sections and combine manually.",
      },
      {
        question: "How long does generation take?",
        answer:
          "Most documents are ready in 10 to 30 seconds. PDF generation with complex formatting takes slightly longer than plain HTML or TXT.",
      },
    ],
    useCases: [
      {
        title: "Project status report from Slack threads",
        description:
          "A project manager asks GAIA to read the last week of Slack messages in a project channel and generate a formatted PDF status report, ready to share with stakeholders.",
      },
      {
        title: "Technical spec from a conversation",
        description:
          "An engineer describes a feature in chat, and GAIA produces a DOCX spec with an overview, requirements section, and edge cases listed, formatted for the team's template.",
      },
      {
        title: "Meeting notes auto-export",
        description:
          "After a meeting summary conversation, a consultant asks GAIA to generate an HTML version of the notes and email it to all attendees as a follow-up.",
      },
    ],
    relatedSlugs: ["workflows", "rich-responses", "email"],
    demoComponent: "document-generation",
  },
  {
    slug: "skills",
    category: "Automation",
    icon: "PackageIcon",
    title: "Skills",
    tagline: "Install or create custom skills to extend GAIA's capabilities",
    headline: "Teach GAIA new tricks.",
    subheadline:
      "Install skills from GitHub to give GAIA new workflows, or create custom skills in plain language — extending what GAIA knows how to do without code.",
    benefits: [
      {
        icon: "Github01Icon",
        title: "Install from GitHub",
        description:
          "Any GitHub repo following the Agent Skills standard can be installed with one command.",
      },
      {
        icon: "PencilEdit01Icon",
        title: "Create custom skills",
        description:
          "Describe a workflow in natural language and save it as a reusable skill.",
      },
      {
        icon: "PackageIcon",
        title: "30+ built-in skills",
        description:
          "Pre-installed skills for Slack, Gmail, GitHub, Notion, Calendar, artifacts, and more.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Browse or install a skill",
        description:
          "Find a skill in the built-in library, install one from a GitHub repo URL, or describe a workflow and save it as a named skill.",
      },
      {
        number: "02",
        title: "Skill is indexed into GAIA's toolkit",
        description:
          "Installed skills are available immediately — GAIA selects them automatically when a matching request comes in.",
      },
      {
        number: "03",
        title: "Invoke from any conversation or workflow",
        description:
          "Call a skill by name or just describe the task. GAIA routes to the right skill without manual selection.",
      },
    ],
    faqs: [
      {
        question: "Can I install skills from any GitHub repository?",
        answer:
          "Any public GitHub repo following the Agent Skills standard can be installed. The repo must include a skill manifest file describing the available actions.",
      },
      {
        question: "How is a custom skill different from a workflow?",
        answer:
          "A workflow is a one-time or scheduled automation for a specific task. A skill is a reusable capability invocable from any conversation or workflow step.",
      },
      {
        question: "Can I keep a custom skill private?",
        answer:
          "Yes. Skills are private by default. Publishing to the marketplace is a manual opt-in step.",
      },
      {
        question: "Do skills work inside automated workflows?",
        answer:
          "Yes. Skills are available as steps in the workflow builder — chain them with other actions or triggers.",
      },
    ],
    useCases: [
      {
        title: "Reusable email triage skill",
        description:
          "A team creates a custom skill that reads the inbox, labels emails by project, and creates Linear issues for anything flagged urgent — reused across multiple workflows.",
      },
      {
        title: "GitHub repo summarizer from community",
        description:
          "A developer installs a community skill from GitHub that fetches a repo's README, recent commits, and open issues and returns a structured summary in chat.",
      },
      {
        title: "Daily briefing skill for executives",
        description:
          "An EA builds a custom briefing skill that combines calendar, email, and Slack highlights into a single morning summary card, reused across the team.",
      },
    ],
    relatedSlugs: ["workflows", "marketplace", "integrations"],
    demoComponent: "skills",
  },
];
