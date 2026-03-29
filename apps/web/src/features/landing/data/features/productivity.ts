import type { FeatureData } from "../featuresData";

export const PRODUCTIVITY_FEATURES: FeatureData[] = [
  {
    slug: "todos",
    category: "Productivity",
    icon: "CheckListIcon",
    title: "Tasks & Todos",
    tagline: "Smart task management that understands natural language",
    headline: "Tasks that understand plain English.",
    subheadline:
      'Type "call Alex tomorrow @finance p1" and GAIA creates the task with the right priority, due date, and project — no dropdowns, no forms.',
    benefits: [
      {
        icon: "LanguageCircleIcon",
        title: "Natural language parsing",
        description:
          '@project, #label, p1/p2/p3, "next Monday," "in 5 days" — all parsed automatically.',
      },
      {
        icon: "WorkflowCircleIcon",
        title: "AI workflow generation",
        description:
          "For any task, GAIA can generate a multi-step workflow to complete it and run it with one click.",
      },
      {
        icon: "ListViewIcon",
        title: "Subtasks and bulk ops",
        description:
          "Break tasks into subtasks, reorganize by project, complete or delete many at once.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Type a task in plain language",
        description:
          "Include priority, due date, project, and labels in the same sentence — GAIA parses all of it.",
      },
      {
        number: "02",
        title: "Task is created with all fields populated",
        description:
          "Due date, priority, project assignment, and labels are extracted and applied without any form-filling.",
      },
      {
        number: "03",
        title: "GAIA can generate a workflow to complete it",
        description:
          "For complex tasks, ask GAIA to generate sub-steps or a full automated workflow and run it with one click.",
      },
    ],
    faqs: [
      {
        question: "What natural language date formats does it understand?",
        answer:
          "It handles 'tomorrow,' 'next Monday,' 'in 5 days,' 'end of month,' and specific dates like 'March 15.' Relative expressions are resolved against your local timezone.",
      },
      {
        question: "Can I assign tasks to other people?",
        answer:
          "Yes. Include '@name' in the task description and GAIA assigns it to that team member if they are in your workspace.",
      },
      {
        question: "Do tasks sync with external tools like Linear or Asana?",
        answer:
          "Yes. Connect Linear, Asana, or Todoist and GAIA creates tasks in those tools directly from chat.",
      },
      {
        question: "Can I set recurring tasks?",
        answer:
          "Yes. Say 'every Monday' or 'first of each month' and GAIA creates a recurring task with the appropriate recurrence rule.",
      },
    ],
    useCases: [
      {
        title: "Capture action items from meeting notes",
        description:
          "Paste meeting notes and ask GAIA to extract action items as tasks. Each one is created with the right owner and due date.",
      },
      {
        title: "Daily task list from inbox priorities",
        description:
          "Ask GAIA to scan your inbox and create tasks for every email requiring follow-up. Flagged with the sender name and due by end of day.",
      },
      {
        title: "Sprint planning in under five minutes",
        description:
          "Describe the sprint goals and ask GAIA to generate a task list. It creates all tasks, assigns priorities, and organizes them by milestone.",
      },
    ],
    relatedSlugs: ["calendar", "goals", "workflows"],
    demoComponent: "todos",
  },
  {
    slug: "calendar",
    category: "Productivity",
    icon: "Calendar02Icon",
    title: "Calendar",
    tagline: "Schedule, reschedule, and prep for meetings with AI",
    headline: "Schedule anything without opening your calendar.",
    subheadline:
      "Create events, find free time, prep for meetings, and set recurring schedules — all through natural language, synced with Google Calendar in real time.",
    benefits: [
      {
        icon: "Time04Icon",
        title: "Find free slots",
        description:
          "GAIA scans your calendar, suggests times, and creates the event in one step.",
      },
      {
        icon: "Calendar03Icon",
        title: "Meeting prep",
        description:
          "Before any call, pull agenda, attendee context, and related emails in seconds.",
      },
      {
        icon: "RepeatIcon",
        title: "Recurring events",
        description:
          '"Every weekday at 9am" becomes a proper recurrence rule automatically.',
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Describe the event in natural language",
        description:
          "Say 'Schedule a 1-on-1 with Sarah next Tuesday at 2pm' and GAIA handles title, time, and invite.",
      },
      {
        number: "02",
        title: "GAIA checks for conflicts and creates the event",
        description:
          "Your calendar is scanned for conflicts before the event is created in Google Calendar.",
      },
      {
        number: "03",
        title: "Meeting prep is available on demand",
        description:
          "Ask for a briefing before any event — GAIA pulls attendee context, recent emails, and open tasks.",
      },
    ],
    faqs: [
      {
        question: "Does it support Google Calendar only?",
        answer:
          "Google Calendar is fully supported with two-way sync. Outlook and Apple Calendar support is on the roadmap.",
      },
      {
        question: "Can GAIA find a time that works for multiple people?",
        answer:
          "Yes. If attendees are in your workspace, GAIA checks their calendars for mutual availability before suggesting a time.",
      },
      {
        question: "Can I reschedule or cancel an event through chat?",
        answer:
          "Yes. Say 'move my 3pm tomorrow to 4pm' and GAIA finds the event, updates the time, and notifies attendees if configured.",
      },
      {
        question:
          "Does GAIA handle timezones for events with remote participants?",
        answer:
          "Yes. Specify a participant's timezone or location and GAIA sets the event in your timezone while displaying the correct time for each attendee.",
      },
    ],
    useCases: [
      {
        title: "Book a meeting without leaving a chat",
        description:
          "Ask GAIA to schedule a 30-minute call with three colleagues next week. It finds a mutual open slot, creates the event, and sends invites.",
      },
      {
        title: "Pre-meeting research brief in 30 seconds",
        description:
          "Before a sales call, ask GAIA for a briefing. It surfaces the contact's last email, open tasks, and any notes from previous meetings.",
      },
      {
        title: "Batch-schedule a recurring weekly sync",
        description:
          "Say 'every Thursday at 10am with the design team for 45 minutes' and GAIA creates a recurring series in Google Calendar.",
      },
    ],
    relatedSlugs: ["todos", "email", "reminders"],
    demoComponent: "calendar",
  },
  {
    slug: "email",
    category: "Productivity",
    icon: "Mail01Icon",
    title: "Email",
    tagline: "Triage, summarize, and compose email through AI",
    headline: "Inbox zero, with AI doing the work.",
    subheadline:
      "GAIA reads your inbox, summarizes threads, drafts replies in your tone, and handles bulk operations — so you spend minutes on email, not hours.",
    benefits: [
      {
        icon: "FilterIcon",
        title: "AI triage",
        description:
          "GAIA scans, flags important emails, and summarizes threads so you know what needs attention.",
      },
      {
        icon: "Edit01Icon",
        title: "Tone-matched drafts",
        description:
          "Tell GAIA what to say; it writes it in your style with length and formality controls.",
      },
      {
        icon: "CheckListIcon",
        title: "Bulk operations",
        description:
          "Mark, archive, star, and delete dozens of emails through a single conversation instruction.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Connect Gmail with one-click OAuth",
        description:
          "GAIA requests read and send permissions. No API keys or manual config required.",
      },
      {
        number: "02",
        title: "Ask GAIA to triage, summarize, or respond",
        description:
          "Describe what to do — 'summarize my unread emails' or 'reply to John saying I'll follow up Friday.'",
      },
      {
        number: "03",
        title: "Review drafts and approve before sending",
        description:
          "GAIA shows the draft inline. Confirm, edit, or discard before anything is sent.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA work with multiple Gmail accounts?",
        answer:
          "Yes. Connect multiple Gmail accounts and GAIA treats them as separate inboxes, drafting and sending from the correct account.",
      },
      {
        question: "Can GAIA send emails without my approval?",
        answer:
          "Not by default. GAIA drafts and shows a preview first. Auto-send can be enabled per workflow for specific automated use cases.",
      },
      {
        question: "How does tone matching work?",
        answer:
          "GAIA analyzes your past sent emails to learn vocabulary, sentence length, and formality level. Specify 'brief and casual' or 'formal' to override for a single draft.",
      },
      {
        question: "Can it handle email threads, not just individual messages?",
        answer:
          "Yes. GAIA reads full thread context before drafting a reply. The summary includes every message in the thread, not just the latest.",
      },
    ],
    useCases: [
      {
        title: "Inbox zero on a Monday morning",
        description:
          "Ask GAIA to summarize all unread emails, flag the urgent ones, and archive everything older than 7 days. Done in under two minutes.",
      },
      {
        title: "Bulk reply to event RSVPs",
        description:
          "Ask GAIA to reply 'yes' to all pending calendar invites from this week. It reads each thread, drafts the response, and sends after a single confirmation.",
      },
      {
        title: "Follow-up reminders from sent emails",
        description:
          "Ask GAIA to scan sent mail for emails with no reply in over 5 days and create follow-up tasks for each one.",
      },
    ],
    relatedSlugs: ["calendar", "todos", "proactive-ai"],
    demoComponent: "email",
  },
  {
    slug: "goals",
    category: "Productivity",
    icon: "Target02Icon",
    title: "Goals",
    tagline: "Set a goal — get an AI-generated roadmap to achieve it",
    headline: "Turn ambitions into step-by-step roadmaps.",
    subheadline:
      "Describe a goal in one sentence and GAIA generates a structured roadmap with milestones — then tracks your progress as you complete each step.",
    benefits: [
      {
        icon: "ChartBarLineIcon",
        title: "AI roadmap generation",
        description:
          "From a one-line description, a multi-step plan with specific achievable milestones.",
      },
      {
        icon: "ChartIncreaseIcon",
        title: "Progress tracking",
        description:
          "Check off nodes, GAIA tracks overall completion and keeps the roadmap current.",
      },
      {
        icon: "BookOpenIcon",
        title: "60+ goal templates",
        description:
          "Start from a curated library across career, wellness, finance, and creative categories.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Describe your goal in one sentence",
        description:
          "State the outcome — GAIA generates a structured roadmap with milestones and sub-steps automatically.",
      },
      {
        number: "02",
        title: "Review and customize the roadmap",
        description:
          "Edit, reorder, or add milestones before activating. Each node is a concrete, completable action.",
      },
      {
        number: "03",
        title: "Track progress as you complete milestones",
        description:
          "Check off nodes and GAIA updates overall completion percentage and surfaces the next step.",
      },
    ],
    faqs: [
      {
        question: "Can I create a goal from scratch instead of a template?",
        answer:
          "Yes. Type any goal in plain language and GAIA generates a custom roadmap. Templates are a starting point, not a requirement.",
      },
      {
        question: "How many milestones does GAIA generate per goal?",
        answer:
          "Typically 5 to 10 milestones, each broken into 2 to 4 sub-steps. The depth is based on goal complexity and can be adjusted after generation.",
      },
      {
        question: "Can goals be linked to tasks or calendar events?",
        answer:
          "Yes. From any milestone, create a linked todo or calendar event. Completing the task marks the milestone as done.",
      },
      {
        question: "Are goals private or shared with the workspace?",
        answer:
          "Goals are private by default. Sharing with specific workspace members is available through the goal detail page.",
      },
    ],
    useCases: [
      {
        title: "Six-month career transition plan",
        description:
          "Describe the role you are targeting and GAIA generates a roadmap covering skill gaps, portfolio projects, networking steps, and application timelines.",
      },
      {
        title: "Launch a side project in 90 days",
        description:
          "Set a goal to launch a product by a date. GAIA creates a roadmap covering validation, build, marketing, and launch milestones with deadlines.",
      },
      {
        title: "Personal fitness goal with weekly milestones",
        description:
          "State a fitness target and GAIA generates weekly workout and nutrition milestones. Check off each week to track the full journey.",
      },
    ],
    relatedSlugs: ["todos", "reminders", "workflows"],
    demoComponent: "goals",
  },
  {
    slug: "reminders",
    category: "Productivity",
    icon: "AlarmClockIcon",
    title: "Reminders",
    tagline: "Set recurring or one-time reminders in plain language",
    headline: "Reminders that speak your language.",
    subheadline:
      '"Remind me every Monday at 9am to review my pipeline" — GAIA creates the recurring reminder with your timezone, no configuration needed.',
    benefits: [
      {
        icon: "RepeatIcon",
        title: "Recurring patterns",
        description:
          "Cron-powered recurrence with max occurrence limits and stop-after dates.",
      },
      {
        icon: "GlobalIcon",
        title: "Timezone-aware",
        description:
          "All reminders respect your local timezone, no UTC confusion.",
      },
      {
        icon: "Search01Icon",
        title: "Fully searchable",
        description:
          "Find, update, or cancel any reminder by searching across all scheduled notifications.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Set a reminder in plain language",
        description:
          "Say 'remind me every Monday at 9am to review my pipeline' and GAIA creates the recurring reminder.",
      },
      {
        number: "02",
        title: "Timezone and recurrence are applied automatically",
        description:
          "Your local timezone is used by default. Recurrence patterns like 'every weekday' are converted to cron rules.",
      },
      {
        number: "03",
        title: "Reminder fires at the scheduled time",
        description:
          "Notification appears in-app, on mobile, or via the configured bot channel at exactly the right time.",
      },
    ],
    faqs: [
      {
        question: "Can reminders be sent to Slack or Telegram?",
        answer:
          "Yes. Route any reminder to a Slack DM, Telegram message, or Discord channel from reminder settings.",
      },
      {
        question:
          "Can I set a reminder to stop after a certain number of occurrences?",
        answer:
          "Yes. Say 'remind me 10 times' or 'until December 31st' and GAIA sets the max occurrence or end date accordingly.",
      },
      {
        question: "What happens if I miss a reminder notification?",
        answer:
          "Missed reminders appear in the notifications panel with a timestamp. They are not re-sent automatically but remain visible until dismissed.",
      },
      {
        question: "Can I snooze or reschedule a reminder that already fired?",
        answer:
          "Yes. From the notification or the reminders list, select 'snooze' to delay by 15 minutes, 1 hour, or a custom time.",
      },
    ],
    useCases: [
      {
        title: "Weekly pipeline review every Monday",
        description:
          "Set one recurring reminder and GAIA fires it every Monday at 9am with a prompt to review open deals in HubSpot.",
      },
      {
        title: "Follow-up reminders for pending proposals",
        description:
          "After sending a proposal, ask GAIA to remind you in 3 business days if there has been no reply. One message, one reminder created.",
      },
      {
        title: "Daily standup prompt for the team",
        description:
          "Create a recurring reminder that posts a standup prompt to a Slack channel every weekday at 9:30am.",
      },
    ],
    relatedSlugs: ["todos", "calendar", "scheduled-automation"],
    demoComponent: "reminders",
  },
  {
    slug: "pins",
    category: "Productivity",
    icon: "Pin02Icon",
    title: "Pins",
    tagline: "Save and bookmark any message for later reference",
    headline: "Never lose an important insight again.",
    subheadline:
      "Pin any message from any conversation to save it permanently — then search and browse all your pins in one place.",
    benefits: [
      {
        icon: "Bookmark01Icon",
        title: "One-click saving",
        description:
          "Pin any AI response, tool result, or message instantly from the conversation.",
      },
      {
        icon: "Search01Icon",
        title: "Searchable collection",
        description:
          "Full-text search across all pinned content to find what you saved.",
      },
      {
        icon: "LinkSquare02Icon",
        title: "Context preserved",
        description:
          "Each pin links back to the original conversation for full context.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Click pin on any message",
        description:
          "Hover any message in any conversation and click the pin icon to save it instantly.",
      },
      {
        number: "02",
        title: "Pin is stored with full context",
        description:
          "The message content, timestamp, and a link to the original conversation are saved together.",
      },
      {
        number: "03",
        title: "Browse and search all pins in one place",
        description:
          "Open the Pins panel to search, filter by date or topic, and jump back to the original conversation.",
      },
    ],
    faqs: [
      {
        question: "Can I pin tool results like charts and code outputs?",
        answer:
          "Yes. Any message in a conversation can be pinned — including rich components, code blocks, and research summaries.",
      },
      {
        question: "Are pins shared with other workspace members?",
        answer:
          "No. Pins are private to your account by default. Workspace-shared pins are not currently supported.",
      },
      {
        question: "Is there a limit to how many messages I can pin?",
        answer:
          "There is no limit. Pins are stored and indexed for full-text search regardless of volume.",
      },
      {
        question: "Can I organize pins into folders or collections?",
        answer:
          "Pins can be filtered by date and searched by keyword. Folder-based organization is on the roadmap.",
      },
    ],
    useCases: [
      {
        title: "Save a research summary for later reference",
        description:
          "Pin a deep research result so you can find it next week without re-running the query. Link back to the full conversation for context.",
      },
      {
        title: "Build a personal knowledge base from conversations",
        description:
          "Pin key facts, code snippets, and summaries from different conversations. Search them later like a personal wiki.",
      },
      {
        title: "Track decisions made in AI conversations",
        description:
          "When GAIA recommends a direction and you agree, pin that message. Revisit the decision with full context when the topic comes up again.",
      },
    ],
    relatedSlugs: ["smart-chat", "memory", "deep-research"],
    demoComponent: "pins",
  },
  {
    slug: "dashboard",
    category: "Productivity",
    icon: "DashboardSquare03Icon",
    title: "Dashboard",
    tagline: "Unified view of todos, emails, calendar, and workflows",
    headline: "Your entire work context in one view.",
    subheadline:
      "The GAIA dashboard shows unread emails, upcoming events, today's todos, active workflows, and recent conversations — all updated in real time.",
    benefits: [
      {
        icon: "GridViewIcon",
        title: "Bento widget layout",
        description:
          "Five information widgets arranged in a responsive grid, each pulling live data.",
      },
      {
        icon: "CursorIcon",
        title: "Quick-action entry",
        description:
          "The composer on the dashboard launches a new chat with full context pre-loaded.",
      },
      {
        icon: "RefreshIcon",
        title: "Real-time sync",
        description:
          "All widgets update automatically as emails arrive, events change, or tasks complete.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Connect your tools via integrations",
        description:
          "Link Gmail, Google Calendar, and your workflow setup. Dashboard widgets populate immediately after connection.",
      },
      {
        number: "02",
        title: "Dashboard assembles all live data in one view",
        description:
          "Five bento widgets show unread email count, today's events, open todos, active workflows, and recent conversations.",
      },
      {
        number: "03",
        title: "Launch a new chat with full context pre-loaded",
        description:
          "The composer on the dashboard starts a chat with your current context — inbox state, calendar, and tasks — already available.",
      },
    ],
    faqs: [
      {
        question: "Can I customize which widgets appear on the dashboard?",
        answer:
          "Widget visibility can be toggled in dashboard settings. Reordering and resizing are on the roadmap.",
      },
      {
        question: "How frequently do the widgets refresh?",
        answer:
          "Email and calendar widgets refresh every 60 seconds. Todos and workflows update in real time via WebSocket.",
      },
      {
        question:
          "Does the dashboard work without connecting all integrations?",
        answer:
          "Yes. Widgets for unconnected services show an empty state with a connect prompt. Other widgets still function normally.",
      },
      {
        question: "Is there a mobile version of the dashboard?",
        answer:
          "Yes. The mobile app has a touch-optimized dashboard with the same widgets in a vertically stacked layout.",
      },
    ],
    useCases: [
      {
        title: "Morning context check before starting work",
        description:
          "Open GAIA and see unread emails, today's three meetings, five overdue tasks, and two active workflows — all before opening a single other app.",
      },
      {
        title: "End-of-day review and planning",
        description:
          "Check the dashboard at 5pm to see what is open, fire off a quick GAIA message to reschedule tomorrow's tasks, and close the day cleanly.",
      },
      {
        title: "One-click access to the most pressing item",
        description:
          "The dashboard surfaces the highest-priority todo and the next calendar event. Click either to jump directly into the relevant GAIA workflow.",
      },
    ],
    relatedSlugs: ["todos", "calendar", "email"],
    demoComponent: "dashboard",
  },
];
