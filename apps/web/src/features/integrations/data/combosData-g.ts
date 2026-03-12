import type { IntegrationCombo } from "./combosData";

export const combosBatchG: Record<string, IntegrationCombo> = {
  "discord-slack": {
    slug: "discord-slack",
    toolA: "Discord",
    toolASlug: "discord",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline:
      "Bridge your Discord community and Slack work channels automatically",
    metaTitle:
      "Discord + Slack Automation - Community to Work Channel Bridge | GAIA",
    metaDescription:
      "Connect Discord and Slack with GAIA. Route community signals to Slack teams, mirror announcements, and keep community managers and internal teams aligned.",
    keywords: [
      "discord slack integration",
      "connect discord slack",
      "discord slack automation",
      "discord slack workflow",
      "gaia discord slack",
    ],
    intro:
      "Many teams run their public community on Discord while internal collaboration happens in Slack. Without a bridge, community managers must manually relay feedback, bug reports, and feature requests to engineering and product teams, adding delay and losing context.\n\nGAIA connects Discord and Slack so important community signals flow to the right Slack channels automatically. Announcements posted in Slack can be mirrored to Discord in seconds, and flagged Discord messages can surface directly in Slack threads — keeping both audiences informed without duplicate effort.",
    useCases: [
      {
        title: "Mirror Discord announcements to Slack",
        description:
          "When a message is posted in a Discord announcement channel, GAIA forwards it to the designated Slack channel. Internal teams stay informed of community news without monitoring Discord directly.",
      },
      {
        title: "Escalate community bug reports to Slack engineering",
        description:
          "GAIA watches Discord support channels for messages tagged with bug keywords and routes them to your Slack engineering channel with context. Engineers see real user issues without leaving Slack.",
      },
      {
        title: "Post Slack release notes to Discord",
        description:
          "When your team posts a release update in Slack, GAIA formats and publishes it to the appropriate Discord channel so your community is always first to hear about new features.",
      },
      {
        title: "Sync community feedback to Slack product channel",
        description:
          "GAIA collects Discord reactions and feedback threads above a threshold and posts a daily digest to your Slack product channel. Product managers get a clear picture of community sentiment without context switching.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Discord and Slack to GAIA",
        description:
          "Authorize GAIA with your Discord server and Slack workspace. Select which Discord channels and Slack channels should be linked.",
      },
      {
        step: "Configure routing rules",
        description:
          "Define which Discord events — announcements, flagged messages, keywords — should post to which Slack channels. Set formatting preferences so messages appear naturally in each platform.",
      },
      {
        step: "GAIA bridges your platforms automatically",
        description:
          "Once configured, GAIA monitors both platforms and routes messages according to your rules. Your community and internal teams stay synchronized without any manual forwarding.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync messages in both directions between Discord and Slack?",
        answer:
          "Yes. GAIA supports bidirectional routing — Discord to Slack and Slack to Discord. You configure which channels and event types trigger each direction independently.",
      },
      {
        question:
          "Will GAIA expose internal Slack messages to the Discord community?",
        answer:
          "No. GAIA only posts to Discord when you explicitly configure a rule for that direction. Internal-only Slack channels are never exposed unless you set up a rule to share them.",
      },
      {
        question: "Can I filter which Discord messages get forwarded?",
        answer:
          "Yes. You can filter by keyword, channel, role, reaction count, or message type so only relevant signals reach your Slack team. Noise from casual community chat is excluded by default.",
      },
    ],
  },

  "discord-google-calendar": {
    slug: "discord-google-calendar",
    toolA: "Discord",
    toolASlug: "discord",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline: "Schedule Discord events and get calendar reminders automatically",
    metaTitle: "Discord + Google Calendar Automation - Event Scheduling | GAIA",
    metaDescription:
      "Connect Discord and Google Calendar with GAIA. Auto-create calendar events from Discord scheduling, send reminders in Discord, and keep your community on schedule.",
    keywords: [
      "discord google calendar integration",
      "connect discord google calendar",
      "discord google calendar automation",
      "discord google calendar workflow",
      "gaia discord google calendar",
    ],
    intro:
      "Communities on Discord plan events — game nights, study sessions, AMAs — but coordinating across time zones and ensuring members actually show up is a persistent challenge. Google Calendar is the universal scheduling tool, yet Discord and Calendar never talk to each other natively.\n\nGAIA connects Discord and Google Calendar so events scheduled in Discord are automatically added to participants' calendars, and upcoming events trigger timely reminders back in Discord. Your community stays on the same schedule without manual back-and-forth.",
    useCases: [
      {
        title: "Auto-create calendar events from Discord event posts",
        description:
          "When a community event is posted in a designated Discord channel, GAIA creates a corresponding Google Calendar event with the correct time and description. Members can accept the invite directly from their calendar.",
      },
      {
        title: "Post Discord reminders before scheduled events",
        description:
          "GAIA sends countdown reminders to the Discord channel at configurable intervals — 24 hours and 1 hour before each event. Members get a nudge without anyone having to remember to post manually.",
      },
      {
        title: "Announce new calendar events in Discord",
        description:
          "When a calendar event is added to a shared Google Calendar, GAIA posts an announcement in the Discord events channel. Community members are informed instantly and can react to confirm attendance.",
      },
      {
        title: "Post post-event recaps to Discord",
        description:
          "After a calendar event ends, GAIA posts a recap prompt in Discord so organizers can share notes or recordings. It keeps the conversation tied to the event timeline automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Discord and Google Calendar to GAIA",
        description:
          "Authorize GAIA with your Discord server and link your Google Calendar. Choose which Discord channels and which calendars should be paired.",
      },
      {
        step: "Set reminder and announcement preferences",
        description:
          "Configure how far in advance GAIA should post reminders in Discord and which Google Calendar changes should trigger Discord announcements.",
      },
      {
        step: "GAIA keeps Discord and Calendar in sync",
        description:
          "From that point, GAIA handles event creation, reminders, and announcements automatically. Your community always knows what's happening and when.",
      },
    ],
    faqs: [
      {
        question:
          "Can community members add events to Google Calendar directly from Discord?",
        answer:
          "Yes. GAIA can generate a Google Calendar invite link and post it in Discord so members can add the event with a single click, without needing a GAIA account themselves.",
      },
      {
        question: "What time zone does GAIA use for reminders?",
        answer:
          "GAIA uses the time zone configured in your Google Calendar by default. For Discord reminders, the time is displayed in the server's configured time zone and can include a UTC reference.",
      },
      {
        question: "Can GAIA handle recurring Discord events?",
        answer:
          "Yes. Recurring events defined in Google Calendar will trigger recurring Discord reminders on the same schedule. You only set it up once and GAIA maintains the cadence.",
      },
    ],
  },

  "discord-todoist": {
    slug: "discord-todoist",
    toolA: "Discord",
    toolASlug: "discord",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline:
      "Create Todoist tasks from Discord messages without leaving the conversation",
    metaTitle: "Discord + Todoist Automation - Capture Tasks from Chat | GAIA",
    metaDescription:
      "Connect Discord and Todoist with GAIA. Turn Discord messages into Todoist tasks instantly, assign owners, set due dates, and never lose an action item in chat.",
    keywords: [
      "discord todoist integration",
      "connect discord todoist",
      "discord todoist automation",
      "discord todoist workflow",
      "gaia discord todoist",
    ],
    intro:
      "Action items surface constantly in Discord conversations — a feature request in the feedback channel, a bug flagged in support, a task someone volunteers for in a thread. Without a way to capture these, they get buried under new messages and forgotten.\n\nGAIA lets anyone on your Discord server create a Todoist task with a simple command or reaction. Tasks are added to the right project with assignee and due date already set, so nothing falls through the cracks and Todoist stays the single source of truth for what needs to get done.",
    useCases: [
      {
        title: "Capture action items from Discord with a reaction",
        description:
          "When a team member reacts to a Discord message with a designated emoji, GAIA creates a Todoist task from that message. The task includes a link back to the Discord message for full context.",
      },
      {
        title: "Create tasks via Discord slash command",
        description:
          "Team members type a GAIA command in any Discord channel to create a Todoist task on the spot. They can specify the project, due date, and assignee without ever leaving Discord.",
      },
      {
        title: "Route channel-specific messages to Todoist projects",
        description:
          "Messages in your Discord bug-report or feature-request channels are automatically converted into Todoist tasks in the corresponding project. Triage happens without manual data entry.",
      },
      {
        title: "Post Todoist task completions back to Discord",
        description:
          "When a Todoist task is completed, GAIA posts a brief update to the originating Discord channel. The team sees progress in context without checking Todoist separately.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Discord and Todoist to GAIA",
        description:
          "Authorize GAIA with your Discord server and your Todoist account. Map Discord channels to Todoist projects so tasks land in the right place.",
      },
      {
        step: "Choose capture triggers",
        description:
          "Select whether tasks are created by emoji reactions, slash commands, or automatic channel rules. Configure default assignees and due-date conventions for each channel.",
      },
      {
        step: "GAIA captures and tracks tasks automatically",
        description:
          "GAIA monitors Discord for your configured triggers and creates Todoist tasks instantly. Completions flow back to Discord so the whole team stays informed.",
      },
    ],
    faqs: [
      {
        question: "Do Discord members need a Todoist account to create tasks?",
        answer:
          "No. Discord members trigger task creation through GAIA's Discord bot. Only the GAIA account connected to Todoist needs a valid Todoist login.",
      },
      {
        question:
          "Can I assign tasks to specific Todoist projects based on the Discord channel?",
        answer:
          "Yes. GAIA's channel-to-project mapping lets you route tasks from different Discord channels into separate Todoist projects automatically. You configure the mapping once in GAIA's settings.",
      },
      {
        question:
          "Will GAIA create duplicate tasks if the same message is reacted to twice?",
        answer:
          "GAIA deduplicates by tracking which messages have already generated tasks. If a task already exists for a message, subsequent reactions are ignored rather than creating a duplicate.",
      },
    ],
  },

  "discord-trello": {
    slug: "discord-trello",
    toolA: "Discord",
    toolASlug: "discord",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Track community projects on Trello straight from Discord channels",
    metaTitle:
      "Discord + Trello Automation - Community Project Tracking | GAIA",
    metaDescription:
      "Connect Discord and Trello with GAIA. Create Trello cards from Discord messages, post card updates to Discord, and keep community projects moving without leaving chat.",
    keywords: [
      "discord trello integration",
      "connect discord trello",
      "discord trello automation",
      "discord trello workflow",
      "gaia discord trello",
    ],
    intro:
      "Open-source communities and creator teams often coordinate on Discord but track work on Trello. The gap between them means cards get created late, assignees miss updates, and contributors don't know what's been completed until they check the board manually.\n\nGAIA bridges Discord and Trello so community members can create and update Trello cards directly from Discord, and Trello activity posts back to the relevant Discord channel. Your community's kanban board stays current without anyone having to leave the conversation.",
    useCases: [
      {
        title: "Create Trello cards from Discord messages",
        description:
          "A reaction or slash command in Discord triggers GAIA to create a Trello card with the message content, assigned list, and due date. Contributors can submit work items without opening Trello.",
      },
      {
        title: "Post Trello card updates to Discord",
        description:
          "When a card moves to 'Done' or a comment is added in Trello, GAIA posts an update to the linked Discord channel. The team celebrates wins and stays aware of progress in real time.",
      },
      {
        title: "Sync Discord feature requests to a Trello backlog",
        description:
          "Feature requests posted in your Discord feedback channel are automatically added as Trello cards in the product backlog. Nothing is lost in chat history and prioritization can happen directly on the board.",
      },
      {
        title: "Daily Trello board digest in Discord",
        description:
          "Each morning, GAIA posts a summary of overdue and due-today Trello cards to your Discord project channel. Contributors know their priorities without a standup or manual board review.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Discord and Trello to GAIA",
        description:
          "Authorize GAIA with your Discord server and your Trello workspace. Link specific Discord channels to Trello boards and lists.",
      },
      {
        step: "Configure card creation and notification rules",
        description:
          "Choose which Discord triggers create Trello cards and which Trello events post back to Discord. Set default labels, lists, and assignees for each channel mapping.",
      },
      {
        step: "GAIA keeps Discord and Trello in sync",
        description:
          "GAIA handles card creation and status updates automatically. Your community gets real-time project visibility without switching between Discord and Trello.",
      },
    ],
    faqs: [
      {
        question:
          "Can Discord community members who don't have Trello accounts create cards?",
        answer:
          "Yes. GAIA's Discord bot acts as the Trello account for card creation. Community members only interact with GAIA through Discord reactions or commands.",
      },
      {
        question: "Which Trello list does GAIA add new cards to?",
        answer:
          "You configure the default list per Discord channel in GAIA's settings. You can also allow users to specify a list in the Discord command at creation time.",
      },
      {
        question: "Can I limit which Discord channels can create Trello cards?",
        answer:
          "Yes. GAIA only listens for card-creation triggers in the channels you explicitly configure. Other Discord channels are ignored, preventing accidental card creation from casual conversation.",
      },
    ],
  },

  "discord-jira": {
    slug: "discord-jira",
    toolA: "Discord",
    toolASlug: "discord",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Surface Jira issue updates in Discord engineering channels automatically",
    metaTitle:
      "Discord + Jira Automation - Engineering Channel Issue Updates | GAIA",
    metaDescription:
      "Connect Discord and Jira with GAIA. Post Jira issue updates to Discord channels, create Jira tickets from Discord, and keep open-source engineers informed.",
    keywords: [
      "discord jira integration",
      "connect discord jira",
      "discord jira automation",
      "discord jira workflow",
      "gaia discord jira",
    ],
    intro:
      "Engineering teams that collaborate on Discord still rely on Jira for issue tracking, but context gets siloed between the two. Developers miss status changes because they're heads-down in Discord, while Jira comments go unnoticed by contributors who don't have Jira notifications configured.\n\nGAIA bridges Discord and Jira so engineers stay informed in their primary channel. Jira issue transitions, new assignments, and sprint updates post to the right Discord channels automatically, and team members can create Jira issues directly from Discord without switching tools.",
    useCases: [
      {
        title: "Post Jira issue status changes to Discord",
        description:
          "When a Jira issue transitions — from 'In Progress' to 'In Review', for example — GAIA posts an update to the linked Discord channel. Engineers see real-time sprint progress without checking Jira constantly.",
      },
      {
        title: "Create Jira issues from Discord messages",
        description:
          "A slash command or emoji reaction in Discord lets contributors file a Jira issue instantly. GAIA pre-fills the summary, description, and project from the message context.",
      },
      {
        title: "Alert Discord when a Jira bug is set to Critical",
        description:
          "GAIA monitors Jira for priority escalations and posts an immediate alert to your Discord engineering channel when a ticket is marked Critical or Blocker. The right engineers are notified without delay.",
      },
      {
        title: "Daily Jira sprint digest in Discord",
        description:
          "Each morning GAIA posts a summary of open sprint issues, blockers, and items completed yesterday to your Discord standup channel. Teams get sprint visibility without a dedicated standup meeting.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Discord and Jira to GAIA",
        description:
          "Authorize GAIA with your Discord server and your Jira project. Map Discord channels to Jira projects so updates and alerts land in the right place.",
      },
      {
        step: "Configure notification and creation rules",
        description:
          "Select which Jira events — status changes, priority escalations, new assignments — trigger Discord posts. Define which Discord channels can create Jira issues.",
      },
      {
        step: "GAIA keeps Discord and Jira synchronized",
        description:
          "GAIA monitors both platforms and routes information according to your rules. Engineers stay informed in Discord while Jira remains the authoritative issue tracker.",
      },
    ],
    faqs: [
      {
        question:
          "Do contributors need a Jira account to create issues from Discord?",
        answer:
          "Creating issues via GAIA requires the GAIA account to have Jira write access. Contributors trigger creation through Discord, but the issue is filed under GAIA's connected Jira identity.",
      },
      {
        question:
          "Can GAIA notify different Discord channels for different Jira projects?",
        answer:
          "Yes. You can map each Jira project to a separate Discord channel in GAIA's settings. Issues from the mobile project post to the mobile channel, backend issues to the backend channel, and so on.",
      },
      {
        question: "Will GAIA spam Discord with every minor Jira comment?",
        answer:
          "No. You control which Jira event types trigger Discord notifications. By default, GAIA only posts status transitions and priority changes — not every comment — to keep signal high.",
      },
    ],
  },

  "zoom-asana": {
    slug: "zoom-asana",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline: "Turn Zoom meeting action items into Asana tasks automatically",
    metaTitle: "Zoom + Asana Automation - Meeting Action Items to Tasks | GAIA",
    metaDescription:
      "Connect Zoom and Asana with GAIA. Auto-create Asana tasks from Zoom meeting summaries, assign owners, set due dates, and ensure every action item gets tracked.",
    keywords: [
      "zoom asana integration",
      "connect zoom asana",
      "zoom asana automation",
      "zoom asana workflow",
      "gaia zoom asana",
    ],
    intro:
      "Zoom meetings generate action items, but those action items are only as useful as the system that captures them. Without an automatic bridge, someone must manually review the recording or notes and create tasks in Asana — a step that gets skipped when everyone is busy.\n\nGAIA listens to Zoom meeting summaries and transcripts, identifies action items, and creates Asana tasks with the right assignees and due dates before the call is even over. Your team leaves every meeting with a clear, tracked to-do list.",
    useCases: [
      {
        title: "Auto-create Asana tasks from meeting action items",
        description:
          "After a Zoom call ends, GAIA parses the meeting summary for action items and creates an Asana task for each one. Assignees and due dates from the conversation are applied automatically.",
      },
      {
        title: "Link Zoom recording to the Asana project",
        description:
          "GAIA attaches the Zoom recording URL to the relevant Asana project as a task or note. Team members can reference the recording directly from the Asana board without hunting through email.",
      },
      {
        title: "Post meeting summary to Asana project updates",
        description:
          "GAIA posts a formatted meeting summary — attendees, decisions, action items — as an Asana project status update so stakeholders who weren't on the call are immediately informed.",
      },
      {
        title: "Create recurring tasks from recurring Zoom standups",
        description:
          "For regular Zoom standups, GAIA generates recurring Asana tasks each session based on blockers and commitments raised. Sprint tracking stays current without manual entry after each meeting.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Asana to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Asana workspace. Link specific recurring Zoom meetings to the Asana projects they relate to.",
      },
      {
        step: "Configure task creation preferences",
        description:
          "Set which sections action items land in, how due dates are inferred, and whether GAIA should tag assignees based on who was mentioned in the meeting.",
      },
      {
        step: "GAIA converts meetings into trackable tasks",
        description:
          "After each Zoom call, GAIA processes the summary and populates Asana automatically. Your team leaves meetings knowing every commitment is already captured.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA require Zoom AI Companion or a specific Zoom plan?",
        answer:
          "GAIA works with Zoom's meeting summary and transcript features, which are available on Zoom Business and above. If your plan doesn't include summaries, GAIA can use the raw transcript instead.",
      },
      {
        question: "How does GAIA determine who to assign tasks to in Asana?",
        answer:
          "GAIA matches names mentioned in the meeting summary or transcript to Asana members in the linked workspace. You can review and adjust assignments before they are finalized.",
      },
      {
        question: "Can GAIA handle meetings with multiple Asana projects?",
        answer:
          "Yes. You can map a single Zoom meeting to multiple Asana projects, and GAIA will route action items to the correct project based on labels or keywords in the meeting notes.",
      },
    ],
  },

  "zoom-linear": {
    slug: "zoom-linear",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline:
      "Post Zoom sprint summaries to Linear issues and keep engineering on track",
    metaTitle:
      "Zoom + Linear Automation - Sprint Meeting Summaries to Issues | GAIA",
    metaDescription:
      "Connect Zoom and Linear with GAIA. Auto-post sprint meeting summaries to Linear, create issues from action items, and keep your engineering cycle updated after every call.",
    keywords: [
      "zoom linear integration",
      "connect zoom linear",
      "zoom linear automation",
      "zoom linear workflow",
      "gaia zoom linear",
    ],
    intro:
      "Engineering sprint meetings happen in Zoom, but the decisions and commitments made there need to live in Linear where the actual work is tracked. When that bridge is manual, sprint issues go un-updated, blockers stay undocumented, and the Linear board drifts from reality.\n\nGAIA connects Zoom and Linear so sprint summaries are automatically posted to the relevant Linear cycle, and action items become Linear issues with proper assignees and priority. Your Linear board stays accurate after every sprint ceremony without anyone doing data entry.",
    useCases: [
      {
        title: "Post sprint retrospective notes to Linear cycle",
        description:
          "After a Zoom retro, GAIA formats the discussion into a structured update and posts it to the active Linear cycle. The team has a searchable record of every retro without manual documentation.",
      },
      {
        title: "Create Linear issues from Zoom standup blockers",
        description:
          "Blockers raised during a Zoom standup are automatically converted into Linear issues by GAIA. Each issue is assigned to the person who raised the blocker and linked to the current sprint.",
      },
      {
        title: "Update Linear issue status from Zoom planning decisions",
        description:
          "When a Zoom planning call moves issues between sprints or changes priorities, GAIA applies those decisions in Linear automatically. The board reflects planning outcomes instantly.",
      },
      {
        title: "Attach Zoom recording links to Linear project updates",
        description:
          "GAIA adds the Zoom recording URL to the relevant Linear project as a comment so engineers can replay any part of the planning or retro discussion directly from their issue tracker.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Linear to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Linear workspace. Map recurring Zoom sprint meetings to the corresponding Linear teams and cycles.",
      },
      {
        step: "Define what gets created or updated in Linear",
        description:
          "Choose whether GAIA creates new issues, updates existing ones, or posts cycle comments based on meeting type — standup, planning, or retro.",
      },
      {
        step: "GAIA updates Linear after every sprint meeting",
        description:
          "Following each Zoom call, GAIA processes the summary and applies changes to Linear automatically. Sprint ceremonies produce immediate, traceable outcomes.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA distinguish between different sprint ceremony types?",
        answer:
          "Yes. GAIA identifies meeting type by name or by the Zoom meeting ID you configure. Standups, planning sessions, and retros each trigger different Linear actions.",
      },
      {
        question:
          "Will GAIA create duplicate Linear issues if the same blocker is mentioned twice?",
        answer:
          "GAIA deduplicates by checking for existing open issues with similar titles before creating new ones. If a match is found, it adds a comment rather than a new issue.",
      },
      {
        question:
          "Does this work with Linear's cycle (sprint) feature specifically?",
        answer:
          "Yes. GAIA posts summaries and creates issues within the active Linear cycle. If no cycle is active at meeting time, GAIA queues the items for the next cycle or adds them to the backlog.",
      },
    ],
  },

  "zoom-jira": {
    slug: "zoom-jira",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Log Zoom sprint meeting summaries directly to Jira sprints and epics",
    metaTitle: "Zoom + Jira Automation - Sprint Summaries to Jira | GAIA",
    metaDescription:
      "Connect Zoom and Jira with GAIA. Auto-log Zoom sprint meeting outcomes to Jira, create issues from action items, and keep your Jira board current after every ceremony.",
    keywords: [
      "zoom jira integration",
      "connect zoom jira",
      "zoom jira automation",
      "zoom jira workflow",
      "gaia zoom jira",
    ],
    intro:
      "Sprint ceremonies in Zoom generate commitments, decisions, and blockers that should live in Jira — but when the meeting ends, the notes often stay in someone's notebook or a shared doc that nobody reads. Jira issues go un-updated and sprint boards drift from what was actually discussed.\n\nGAIA closes this gap by processing Zoom meeting summaries and logging outcomes directly to the corresponding Jira sprint. Action items become Jira issues, blockers get flagged, and sprint updates are posted before the team has even closed their laptops.",
    useCases: [
      {
        title: "Create Jira issues from Zoom meeting action items",
        description:
          "GAIA parses Zoom call summaries for action items and creates Jira issues in the active sprint. Each issue includes the description, assignee, and due date captured from the meeting.",
      },
      {
        title: "Post sprint planning outcomes to Jira epics",
        description:
          "After a Zoom planning session, GAIA logs the scope decisions and story point commitments as Jira epic comments. Product managers have a clear record of what was committed and why.",
      },
      {
        title: "Flag Jira blockers surfaced in Zoom standups",
        description:
          "Blockers mentioned in a Zoom standup trigger GAIA to set the Blocker flag on the corresponding Jira issue. Scrum masters see impediments updated in real time without manual triage.",
      },
      {
        title: "Attach Zoom recording to Jira sprint",
        description:
          "GAIA adds the Zoom recording URL as a link on the active Jira sprint board. Stakeholders can review any ceremony recording directly from Jira without asking for the link.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Jira to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Jira project. Map your recurring Zoom sprint meetings to the corresponding Jira boards and sprints.",
      },
      {
        step: "Configure issue creation and update rules",
        description:
          "Define which meeting types create new Jira issues, which update existing ones, and how GAIA should infer priority and assignee from meeting context.",
      },
      {
        step: "GAIA logs meeting outcomes to Jira automatically",
        description:
          "After each Zoom call, GAIA processes the summary and updates Jira accordingly. Sprint boards stay accurate and every commitment is traceable to the meeting where it was made.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA work with Jira Software's sprint feature specifically?",
        answer:
          "Yes. GAIA integrates with Jira Software and can add issues to the active sprint, update story status, and post sprint-level comments. It works with both company-managed and team-managed projects.",
      },
      {
        question:
          "Can GAIA map different Zoom meetings to different Jira boards?",
        answer:
          "Yes. Each recurring Zoom meeting can be mapped to a separate Jira board in GAIA's settings. Frontend standups post to the frontend board; backend planning posts to the backend board.",
      },
      {
        question: "What happens if Zoom's meeting summary is incomplete?",
        answer:
          "If the summary is sparse, GAIA falls back to the raw transcript to extract action items. You can also review GAIA's proposed Jira updates before they are applied if you prefer a human checkpoint.",
      },
    ],
  },

  "zoom-teams": {
    slug: "zoom-teams",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Microsoft Teams",
    toolBSlug: "microsoft-teams",
    tagline: "Bridge Zoom and Microsoft Teams for dual-platform organizations",
    metaTitle:
      "Zoom + Microsoft Teams Automation - Dual Platform Bridge | GAIA",
    metaDescription:
      "Connect Zoom and Microsoft Teams with GAIA. Share meeting summaries across platforms, notify Teams channels of Zoom events, and keep both platforms in sync.",
    keywords: [
      "zoom microsoft teams integration",
      "connect zoom microsoft teams",
      "zoom teams automation",
      "zoom teams workflow",
      "gaia zoom microsoft teams",
    ],
    intro:
      "Many organizations run Zoom for video calls and Microsoft Teams for messaging, creating a split where meeting context lives in one platform and team communication in another. Colleagues who weren't on a Zoom call miss decisions; Teams notifications go unseen by people who live in Zoom.\n\nGAIA bridges Zoom and Microsoft Teams so meeting summaries, recordings, and action items flow into the right Teams channels automatically. Both platform users stay informed and aligned without anyone manually copy-pasting between tools.",
    useCases: [
      {
        title: "Post Zoom meeting summaries to Microsoft Teams channels",
        description:
          "After a Zoom call, GAIA formats the meeting summary and posts it to the designated Teams channel. Team members who weren't on the call get full context without needing to watch the recording.",
      },
      {
        title: "Send Teams reminders for upcoming Zoom meetings",
        description:
          "GAIA posts a reminder in the relevant Teams channel 15 minutes before a Zoom meeting starts, including the join link. Participants never miss a call because they were heads-down in Teams.",
      },
      {
        title: "Share Zoom recording links in Teams",
        description:
          "When a Zoom recording is ready, GAIA posts the link to the appropriate Teams channel. Stakeholders access the recording in their primary collaboration tool without hunting through email.",
      },
      {
        title: "Notify Teams of Zoom meeting action items",
        description:
          "GAIA extracts action items from Zoom summaries and posts a structured list to Teams. Each item shows the owner and due date, giving the team a clear view of commitments made in the call.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Microsoft Teams to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Microsoft Teams tenant. Map Zoom meetings or meeting series to the corresponding Teams channels.",
      },
      {
        step: "Configure notification and summary preferences",
        description:
          "Choose which Zoom events — meeting end, recording ready, action items — trigger posts to Teams and set the format and channel for each notification type.",
      },
      {
        step: "GAIA keeps both platforms synchronized",
        description:
          "GAIA monitors your Zoom account and posts structured updates to Teams automatically. Users on either platform stay informed without manual handoffs.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA also notify Zoom participants about Teams messages?",
        answer:
          "Yes. GAIA can bridge in both directions — important Teams channel messages can trigger a Zoom chat notification or email digest for participants who primarily use Zoom for communication.",
      },
      {
        question: "Does this work for organizations that use Zoom Rooms?",
        answer:
          "GAIA integrates with Zoom Meetings and Zoom Webinars via the Zoom API. Zoom Rooms support depends on whether your Zoom plan exposes room meeting data through the same API.",
      },
      {
        question:
          "Is there a risk of double-notifications if users have both Zoom and Teams open?",
        answer:
          "GAIA posts to Teams channels rather than individual DMs by default, so notifications appear as channel posts rather than personal pings. You can adjust per-channel notification settings in Teams to control alert frequency.",
      },
    ],
  },

  "zoom-drive": {
    slug: "zoom-drive",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Auto-save Zoom recordings and notes to organized Google Drive folders",
    metaTitle: "Zoom + Google Drive Automation - Auto-Save Recordings | GAIA",
    metaDescription:
      "Connect Zoom and Google Drive with GAIA. Automatically save Zoom recordings to Drive, organize by meeting type, and keep your team's video archive structured.",
    keywords: [
      "zoom google drive integration",
      "connect zoom google drive",
      "zoom google drive automation",
      "zoom google drive workflow",
      "gaia zoom google drive",
    ],
    intro:
      "Zoom recordings pile up in the cloud without organization, making it hard to find a specific call weeks later. Google Drive is where most teams already store their documents and shared files, yet Zoom recordings never land there automatically.\n\nGAIA moves Zoom recordings to Google Drive as soon as they're ready and organizes them into folders by meeting name, date, or project. Your team always knows exactly where to find a recording, and Drive becomes the single archive for both documents and video.",
    useCases: [
      {
        title: "Auto-upload Zoom recordings to Google Drive",
        description:
          "When a Zoom recording is processed, GAIA uploads it to the designated Google Drive folder automatically. No manual downloading and re-uploading required.",
      },
      {
        title: "Organize recordings by project or team folder",
        description:
          "GAIA routes recordings to different Drive folders based on the Zoom meeting name or host. Client calls go to the client folder; internal standups go to the team folder.",
      },
      {
        title: "Save meeting transcripts as Drive documents",
        description:
          "GAIA converts the Zoom transcript into a Google Doc and saves it alongside the recording. The searchable text doc makes it easy to find specific moments without scrubbing video.",
      },
      {
        title: "Share Drive folder links in meeting follow-up emails",
        description:
          "After saving a recording, GAIA sends a follow-up email to meeting participants with the Google Drive link. Everyone has instant access without requesting permissions manually.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Google Drive to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Google Drive. Specify the root Drive folder where recordings should be stored.",
      },
      {
        step: "Set folder organization rules",
        description:
          "Configure how GAIA names and organizes folders — by meeting title, date, host, or a combination. GAIA creates subfolders automatically as new meeting series appear.",
      },
      {
        step: "GAIA archives every recording automatically",
        description:
          "When Zoom finishes processing a recording, GAIA transfers it to Drive and applies your folder rules. Your video archive stays organized without any manual intervention.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA delete the recording from Zoom after saving it to Drive?",
        answer:
          "By default, GAIA saves to Drive and leaves the Zoom cloud recording intact. You can optionally configure GAIA to delete from Zoom after a successful Drive upload to manage Zoom storage limits.",
      },
      {
        question: "How long does it take for a recording to appear in Drive?",
        answer:
          "GAIA uploads the recording as soon as Zoom finishes processing it, which typically takes 5–30 minutes after the meeting ends depending on length. You'll receive a notification when it's available in Drive.",
      },
      {
        question:
          "Can GAIA handle recordings from multiple Zoom hosts in one organization?",
        answer:
          "Yes. GAIA supports multiple Zoom hosts within the same organization and can route each host's recordings to a separate Drive folder based on the host's identity.",
      },
    ],
  },

  "zoom-figma": {
    slug: "zoom-figma",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Schedule Zoom design reviews from Figma milestones and share feedback automatically",
    metaTitle: "Zoom + Figma Automation - Design Review Scheduling | GAIA",
    metaDescription:
      "Connect Zoom and Figma with GAIA. Auto-schedule Zoom design reviews when Figma milestones are hit, post meeting feedback to Figma files, and streamline design workflows.",
    keywords: [
      "zoom figma integration",
      "connect zoom figma",
      "zoom figma automation",
      "zoom figma workflow",
      "gaia zoom figma",
    ],
    intro:
      "Design reviews happen in Zoom, but the designs live in Figma — and the feedback captured in the meeting rarely makes it back to the Figma file in a timely way. Designers end up reconciling handwritten notes with verbal comments from a recording they have to scrub through.\n\nGAIA connects Zoom and Figma so design review meetings are scheduled automatically when Figma milestones are reached, and feedback from the call is posted as Figma comments before the designer's next work session. Design and review stay tightly coupled.",
    useCases: [
      {
        title: "Schedule Zoom reviews when Figma milestones are reached",
        description:
          "When a Figma file is marked ready for review, GAIA schedules a Zoom meeting with the relevant stakeholders. The meeting invite includes a direct link to the Figma file.",
      },
      {
        title: "Post Zoom review feedback as Figma comments",
        description:
          "After a design review call, GAIA parses the meeting notes for feedback items and posts them as comments on the relevant Figma frames. Designers have structured feedback without re-watching the recording.",
      },
      {
        title: "Notify Figma team of Zoom meeting recording",
        description:
          "When a design review recording is ready, GAIA posts the Zoom link as a Figma file comment. Anyone who missed the call can watch the review in the context of the file being discussed.",
      },
      {
        title: "Create follow-up Zoom sessions for unresolved Figma comments",
        description:
          "GAIA monitors Figma for comments that remain unresolved after a review and schedules a quick follow-up Zoom session with the designer and reviewer. No action item gets forgotten between design cycles.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and Figma to GAIA",
        description:
          "Authorize GAIA with your Zoom account and Figma workspace. Specify which Figma projects and status labels should trigger Zoom meeting scheduling.",
      },
      {
        step: "Define review triggers and feedback routing",
        description:
          "Set which Figma milestone or status change schedules a Zoom review, and configure how GAIA formats and posts meeting feedback back to Figma.",
      },
      {
        step: "GAIA automates your design review cycle",
        description:
          "GAIA monitors Figma for milestone changes, schedules Zoom calls, and closes the loop by returning feedback to Figma. Design reviews happen on time with complete documentation.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA post feedback to specific Figma frames rather than the whole file?",
        answer:
          "Yes. If the meeting notes reference specific frame names or component names, GAIA attempts to match them to Figma frames and post comments at the frame level rather than the file level.",
      },
      {
        question: "Who gets invited to the Zoom design review automatically?",
        answer:
          "GAIA invites the Figma file's editors and any stakeholders you configure in GAIA's review settings. You can also specify a fixed reviewer list per Figma project.",
      },
      {
        question: "Does GAIA work with Figma's branching feature?",
        answer:
          "GAIA tracks reviews at the file level. If you use Figma branches, configure the milestone status on the branch file and GAIA will schedule the review for that branch's reviewers.",
      },
    ],
  },

  "zoom-hubspot": {
    slug: "zoom-hubspot",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Log Zoom customer calls to HubSpot CRM and keep every deal updated",
    metaTitle: "Zoom + HubSpot Automation - Log Customer Calls to CRM | GAIA",
    metaDescription:
      "Connect Zoom and HubSpot with GAIA. Auto-log Zoom customer calls to HubSpot contacts and deals, capture action items, and keep your CRM current after every call.",
    keywords: [
      "zoom hubspot integration",
      "connect zoom hubspot",
      "zoom hubspot automation",
      "zoom hubspot workflow",
      "gaia zoom hubspot",
    ],
    intro:
      "Sales and customer success teams live in HubSpot, but their customer conversations happen in Zoom. Without an automatic bridge, call notes go un-logged, follow-up tasks get missed, and HubSpot deal timelines miss critical touchpoints that inform pipeline forecasting.\n\nGAIA logs every Zoom customer call to the right HubSpot contact and deal automatically. Meeting summaries become CRM notes, action items become tasks, and deal stages update based on what was discussed — so your CRM reflects reality without manual data entry after every call.",
    useCases: [
      {
        title: "Auto-log Zoom call summaries to HubSpot deals",
        description:
          "When a Zoom customer call ends, GAIA creates a HubSpot activity log on the matching contact and deal. The summary includes attendees, key discussion points, and next steps.",
      },
      {
        title: "Create HubSpot follow-up tasks from Zoom action items",
        description:
          "Action items identified in a Zoom call summary become HubSpot tasks assigned to the account owner. Due dates from the conversation are applied so nothing slips post-call.",
      },
      {
        title: "Update HubSpot deal stage based on call outcomes",
        description:
          "If a Zoom call results in a verbal agreement or a scheduled demo, GAIA advances the HubSpot deal stage accordingly. Pipeline stages stay current without relying on reps to update manually.",
      },
      {
        title: "Attach Zoom recording to HubSpot contact",
        description:
          "GAIA attaches the Zoom recording URL to the HubSpot contact record. Sales managers can review calls directly from CRM without asking reps for links after the fact.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and HubSpot to GAIA",
        description:
          "Authorize GAIA with your Zoom account and HubSpot portal. GAIA matches Zoom meeting participants to HubSpot contacts by email address automatically.",
      },
      {
        step: "Configure CRM logging preferences",
        description:
          "Set which meeting types trigger CRM logging, how deal stage changes are inferred, and which HubSpot pipelines GAIA should update.",
      },
      {
        step: "GAIA logs every customer call to HubSpot",
        description:
          "After each Zoom call, GAIA creates the activity, tasks, and any deal stage updates in HubSpot. Your CRM is always current without post-call admin work.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA match a Zoom meeting to the right HubSpot contact?",
        answer:
          "GAIA matches participants by email address. If a Zoom participant's email exists as a HubSpot contact, the call is logged to that contact. Unmatched participants are flagged for manual review.",
      },
      {
        question:
          "Can GAIA log calls to both a contact and an associated deal in HubSpot?",
        answer:
          "Yes. GAIA logs the activity to the contact record and associates it with all open deals linked to that contact. You can configure it to target a specific pipeline if a contact has multiple deals.",
      },
      {
        question: "Does GAIA work with HubSpot's free CRM or only paid tiers?",
        answer:
          "GAIA works with any HubSpot tier that provides API access. The free CRM supports basic contact and activity logging. Task creation and deal stage updates require HubSpot Starter or above.",
      },
    ],
  },

  "zoom-clickup": {
    slug: "zoom-clickup",
    toolA: "Zoom",
    toolASlug: "zoom",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline: "Post Zoom meeting action items to ClickUp tasks automatically",
    metaTitle:
      "Zoom + ClickUp Automation - Meeting Action Items to Tasks | GAIA",
    metaDescription:
      "Connect Zoom and ClickUp with GAIA. Auto-create ClickUp tasks from Zoom meeting action items, assign owners, set due dates, and keep your workspace current after every call.",
    keywords: [
      "zoom clickup integration",
      "connect zoom clickup",
      "zoom clickup automation",
      "zoom clickup workflow",
      "gaia zoom clickup",
    ],
    intro:
      "Zoom meetings produce action items, but those commitments only move work forward if they're captured in the project management tool your team actually uses. For teams on ClickUp, that means someone has to manually translate meeting notes into tasks — a step that often gets deprioritized.\n\nGAIA eliminates that step by parsing Zoom meeting summaries and creating ClickUp tasks automatically. Each action item gets the right assignee, due date, and list placement so your ClickUp workspace reflects every commitment made on the call.",
    useCases: [
      {
        title: "Create ClickUp tasks from Zoom meeting action items",
        description:
          "GAIA processes the Zoom meeting summary and creates a ClickUp task for each action item. Assignees and due dates from the meeting are applied, and a link to the Zoom recording is attached.",
      },
      {
        title: "Post meeting summaries to ClickUp docs",
        description:
          "After a Zoom call, GAIA creates a ClickUp Doc with the full meeting summary, attendee list, and decisions. Teams have a searchable record of every meeting in the same tool they use for tasks.",
      },
      {
        title: "Route action items to the right ClickUp list",
        description:
          "GAIA maps action items to ClickUp lists based on keywords or assignees in the meeting notes. Engineering tasks go to the dev list; marketing tasks go to the campaigns list automatically.",
      },
      {
        title: "Update ClickUp task status based on Zoom follow-up calls",
        description:
          "When a follow-up Zoom call closes out an open ClickUp task, GAIA marks it complete and posts a note with the call summary. Task history stays connected to the conversations that drove it.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Zoom and ClickUp to GAIA",
        description:
          "Authorize GAIA with your Zoom account and ClickUp workspace. Map Zoom meeting series to the ClickUp spaces, folders, and lists where tasks should be created.",
      },
      {
        step: "Configure task creation and routing rules",
        description:
          "Define how GAIA infers assignees, due dates, and priority from meeting context. Set keyword-based routing rules to place tasks in the correct ClickUp list automatically.",
      },
      {
        step: "GAIA turns every Zoom call into ClickUp tasks",
        description:
          "After each Zoom meeting, GAIA creates tasks in ClickUp with full context. Your team leaves every call with a complete, tracked to-do list ready to execute.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create tasks in different ClickUp spaces for different meeting types?",
        answer:
          "Yes. You can configure separate ClickUp space and list mappings for each recurring Zoom meeting or meeting type. Each meeting series routes to its own ClickUp destination.",
      },
      {
        question: "Does GAIA work with ClickUp's subtask feature?",
        answer:
          "Yes. If an action item in the meeting summary has sub-steps, GAIA can create a parent task with subtasks. You can enable or disable subtask creation in GAIA's ClickUp settings.",
      },
      {
        question:
          "How does GAIA handle meetings where no clear action items are identified?",
        answer:
          "If no action items are found, GAIA creates a summary-only ClickUp Doc rather than tasks. You receive a notification so you can manually add tasks if the meeting contained implicit commitments.",
      },
    ],
  },
};
