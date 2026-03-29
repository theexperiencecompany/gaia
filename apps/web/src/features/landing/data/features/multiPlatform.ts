import type { FeatureData } from "../featuresData";

export const MULTI_PLATFORM_FEATURES: FeatureData[] = [
  {
    slug: "voice",
    category: "Multi-Platform",
    icon: "MicrophoneIcon",
    title: "Voice",
    tagline: "Talk to GAIA hands-free — real-time voice conversations",
    headline: "Say it. GAIA handles the rest.",
    subheadline:
      "Activate voice mode and have a real-time conversation — Deepgram transcribes, GAIA responds with ElevenLabs TTS, and all the same tools are available hands-free.",
    benefits: [
      {
        icon: "Clock01Icon",
        title: "Sub-second STT",
        description:
          "Deepgram delivers near-instant transcription so GAIA hears you as you speak.",
      },
      {
        icon: "VoiceIcon",
        title: "Natural TTS",
        description:
          "ElevenLabs generates expressive, natural speech for every GAIA response.",
      },
      {
        icon: "WorkflowSquare10Icon",
        title: "Full tool access",
        description:
          "Voice mode has all the same capabilities as chat: todos, email, research, calendar, workflows.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Activate voice mode in the app",
        description:
          "Tap the microphone button in chat to start a real-time voice session.",
      },
      {
        number: "02",
        title: "Speak and GAIA listens",
        description:
          "Deepgram transcribes your speech in near real time and sends the text to GAIA's agent.",
      },
      {
        number: "03",
        title: "GAIA responds and reads it aloud",
        description:
          "The agent completes actions and ElevenLabs TTS speaks the response back through your speaker.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA take real actions in voice mode?",
        answer:
          "Yes. Voice mode has the same tool access as chat — create tasks, send emails, search the web, set reminders, and more, all hands-free.",
      },
      {
        question: "What speech-to-text engine is used?",
        answer:
          "Deepgram Nova is used for transcription, providing near real-time accuracy with low latency on most accents and languages.",
      },
      {
        question: "Can I choose a different voice for responses?",
        answer:
          "Yes. Several ElevenLabs voice profiles are available in settings. Choose from multiple accents and speaking styles.",
      },
      {
        question: "Does voice mode work on mobile?",
        answer:
          "Yes. Voice mode is fully supported on the iOS and Android mobile apps with the same capabilities as the web version.",
      },
    ],
    useCases: [
      {
        title: "Hands-free task creation while commuting",
        description:
          "A founder commutes by train and dictates tasks to GAIA hands-free — GAIA creates them with the right project and priority parsed from the spoken instruction.",
      },
      {
        title: "Quick email reply without typing",
        description:
          "A manager says 'reply to the last email from Sarah and tell her the report is ready' — GAIA drafts and sends without the user touching a keyboard.",
      },
      {
        title: "Real-time research during a walk",
        description:
          "A researcher asks GAIA about a topic while walking, receives a spoken summary, and follows up with clarifying questions — a full research session hands-free.",
      },
    ],
    relatedSlugs: ["smart-chat", "mobile", "reminders"],
    demoComponent: "voice",
  },
  {
    slug: "slack-bot",
    category: "Multi-Platform",
    icon: "MessageMultiple02Icon",
    title: "Slack Bot",
    tagline: "Use GAIA directly inside your Slack workspace",
    headline: "@GAIA in Slack, doing real work.",
    subheadline:
      "Mention @GAIA in any channel or DM, run slash commands, or receive automated workflow posts — all from inside the Slack your team already uses.",
    benefits: [
      {
        icon: "AtIcon",
        title: "Mention anywhere",
        description:
          "@GAIA in any channel creates tasks, answers questions, and posts updates.",
      },
      {
        icon: "CommandIcon",
        title: "Slash commands",
        description:
          "/gaia, /todo, /workflow — full GAIA capabilities through native Slack commands.",
      },
      {
        icon: "Notification01Icon",
        title: "Workflow posts",
        description:
          "Automated workflows post results directly to Slack channels: briefings, alerts, reports.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Install GAIA in your Slack workspace",
        description:
          "Add the GAIA Slack app from the integrations page with one OAuth click.",
      },
      {
        number: "02",
        title: "Mention @GAIA or use slash commands",
        description:
          "Type @GAIA in any channel with a request, or use /gaia, /todo, and /workflow commands.",
      },
      {
        number: "03",
        title: "GAIA responds and takes action",
        description:
          "Responses appear directly in the thread. Workflows can post to channels automatically on any schedule.",
      },
    ],
    faqs: [
      {
        question: "Does every team member need a GAIA account?",
        answer:
          "Each user must link their own GAIA account to Slack to use the bot. Workspace-level install allows the bot to be added, but personal account linking is required for GAIA to act on that user's data.",
      },
      {
        question: "Can GAIA post to Slack from automated workflows?",
        answer:
          "Yes. Use Slack as a workflow output step to post messages, summaries, or alerts to any channel on a schedule or when an event fires.",
      },
      {
        question: "Does @GAIA work in private channels?",
        answer:
          "Yes, as long as GAIA is invited to the private channel. Invite it like any other user.",
      },
      {
        question: "Can I use GAIA in a Slack DM?",
        answer:
          "Yes. Open a direct message with the GAIA app and use it exactly like the web chat — full tool access, memory, and context.",
      },
    ],
    useCases: [
      {
        title: "Instant GitHub PR summary in Slack",
        description:
          "A developer mentions @GAIA in the #engineering channel asking for a summary of all open PRs — GAIA queries GitHub and posts a formatted list in under 10 seconds.",
      },
      {
        title: "Daily standup briefing posted automatically",
        description:
          "A team sets up a scheduled workflow to post a morning standup summary to #general every weekday at 9am, pulling todos and calendar events for each member.",
      },
      {
        title: "Create a task from a Slack message",
        description:
          "A manager replies to a message with @GAIA create task and GAIA creates a Linear issue with the message content, priority p2, and assigns it to the sender.",
      },
    ],
    relatedSlugs: ["workflows", "integrations", "discord-bot"],
    demoComponent: "slack-bot",
  },
  {
    slug: "discord-bot",
    category: "Multi-Platform",
    icon: "GameboyIcon",
    title: "Discord Bot",
    tagline: "Full GAIA capabilities in your Discord server",
    headline: "GAIA lives in your Discord server.",
    subheadline:
      "Use slash commands, mention GAIA in channels, execute workflows, and get streaming AI responses — all inside Discord with rich embeds and context menus.",
    benefits: [
      {
        icon: "LayoutIcon",
        title: "Rich embeds",
        description:
          "Discord's embed format lets GAIA render structured, colored, field-based responses.",
      },
      {
        icon: "CursorIcon",
        title: "Context menus",
        description:
          'Right-click any message to "Summarize with GAIA" or "Add as Todo."',
      },
      {
        icon: "UserGroupIcon",
        title: "Server-wide access",
        description:
          "Every team member can use GAIA in any channel with their own linked account.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Add GAIA bot to your Discord server",
        description:
          "Authorize the GAIA Discord app from the integrations page to install it into any server you manage.",
      },
      {
        number: "02",
        title: "Use slash commands or right-click menus",
        description:
          "Type /gaia with a request, use /todo or /workflow, or right-click any message for context menu actions.",
      },
      {
        number: "03",
        title: "GAIA responds with rich embeds",
        description:
          "Responses arrive as formatted Discord embeds with colored fields, links, and structured content.",
      },
    ],
    faqs: [
      {
        question: "Does each server member need their own GAIA account?",
        answer:
          "Yes. Each user must link their GAIA account to their Discord account. The bot can be installed server-wide, but each person acts within their own GAIA workspace.",
      },
      {
        question: "Can I use GAIA in a private Discord server?",
        answer:
          "Yes. The bot can be added to any server you have Manage Server permission for, including private or invite-only servers.",
      },
      {
        question: "What are context menus?",
        answer:
          "Right-clicking any message in Discord reveals a GAIA context menu with options like Summarize, Add as Todo, and Research This. Each option triggers the corresponding GAIA action.",
      },
      {
        question: "Can GAIA post workflow results to a Discord channel?",
        answer:
          "Yes. Use Discord as an output step in any workflow. Results, briefings, and alerts can be posted to any channel the bot has access to.",
      },
    ],
    useCases: [
      {
        title: "Community knowledge base search",
        description:
          "A Discord community installs GAIA and members use /gaia to search the community's linked Notion docs, getting answers directly in the server without leaving Discord.",
      },
      {
        title: "Summarize a long discussion thread",
        description:
          "A moderator right-clicks a long thread and selects Summarize with GAIA — a concise embed with key points appears in the channel within seconds.",
      },
      {
        title: "Automated project updates to Discord",
        description:
          "A game dev team connects GitHub to a workflow that posts a daily build status embed to their Discord #updates channel every morning at 10am.",
      },
    ],
    relatedSlugs: ["slack-bot", "telegram-bot", "workflows"],
    demoComponent: "discord-bot",
  },
  {
    slug: "telegram-bot",
    category: "Multi-Platform",
    icon: "AirplaneIcon",
    title: "Telegram Bot",
    tagline: "GAIA in your Telegram — commands, DMs, group chats",
    headline: "GAIA in your Telegram, anywhere in the world.",
    subheadline:
      "Use /gaia, /todo, and /workflow commands in DMs or groups — with native command suggestion menus and automatic ephemeral responses in group chats.",
    benefits: [
      {
        icon: "CommandIcon",
        title: "Native command menus",
        description:
          "Telegram's \"/\" suggestion menu is always in sync with GAIA's full command set.",
      },
      {
        icon: "UserGroupIcon",
        title: "Group-friendly",
        description:
          "In group chats, responses are sent as private DMs to avoid spam.",
      },
      {
        icon: "GlobalIcon",
        title: "Global reach",
        description:
          "Telegram works anywhere with a data connection, no VPN or workspace required.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Start a chat with the GAIA Telegram bot",
        description:
          "Search for @GAIA_bot on Telegram and start a DM, or add it to a group chat.",
      },
      {
        number: "02",
        title: "Link your GAIA account",
        description:
          "Send /start and follow the link to connect your GAIA account — one-time setup.",
      },
      {
        number: "03",
        title: "Use commands or just type a request",
        description:
          "Use /gaia, /todo, or /workflow commands, or type any request in plain language and GAIA responds.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA respond in group chats?",
        answer:
          "Yes, but responses in group chats are sent as private DMs to avoid cluttering the group. The bot acknowledges the request in the group so others can see it was received.",
      },
      {
        question: "Are Telegram messages end-to-end encrypted?",
        answer:
          "Regular Telegram chats are encrypted in transit but not end-to-end. Secret Chats are end-to-end encrypted but bots cannot participate in them. GAIA operates in regular chats only.",
      },
      {
        question: "What commands are available?",
        answer:
          "/gaia starts a conversation, /todo creates a task, /workflow runs a workflow by name. The full list appears in Telegram's / suggestion menu and updates automatically.",
      },
      {
        question: "Can I receive workflow notifications on Telegram?",
        answer:
          "Yes. Add Telegram as an output step in any workflow to receive scheduled briefings, alerts, and reports as Telegram messages.",
      },
    ],
    useCases: [
      {
        title: "Reminders on the go via Telegram",
        description:
          "A consultant sets reminders through the Telegram bot while traveling — no app switching, no desktop needed. Reminders arrive as Telegram messages at the right time.",
      },
      {
        title: "Quick task capture from anywhere",
        description:
          "A product manager sends /todo review launch checklist before 5pm Friday to the GAIA bot and the task is created immediately with the correct due date.",
      },
      {
        title: "International team workflow alerts",
        description:
          "A distributed team uses Telegram as their primary messaging app. A scheduled GAIA workflow sends daily deployment status to the team's Telegram group bot.",
      },
    ],
    relatedSlugs: ["slack-bot", "discord-bot", "mobile"],
    demoComponent: "telegram-bot",
  },
  {
    slug: "mobile",
    category: "Multi-Platform",
    icon: "SmartPhone01Icon",
    title: "Mobile App",
    tagline: "The full GAIA experience on iOS and Android",
    headline: "The full GAIA experience on mobile.",
    subheadline:
      "Every feature available on web — chat, todos, workflows, integrations, voice — optimized for iOS and Android with native push notifications and offline support.",
    benefits: [
      {
        icon: "Notification01Icon",
        title: "Native push notifications",
        description:
          "Workflow completions, reminders, and alerts delivered as OS-level notifications.",
      },
      {
        icon: "DatabaseIcon",
        title: "Offline support",
        description:
          "Message history cached with IndexedDB so you can browse past conversations without a connection.",
      },
      {
        icon: "TouchInteractionIcon",
        title: "Touch-optimized",
        description:
          "iMessage-style bubbles, long-press bulk select, bottom sheets, haptic feedback — built for thumbs.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Download the app for iOS or Android",
        description:
          "Install GAIA from the App Store or Google Play and log in with your existing account.",
      },
      {
        number: "02",
        title: "All your data syncs instantly",
        description:
          "Conversations, todos, workflows, and integrations are all available immediately — no extra setup.",
      },
      {
        number: "03",
        title: "Use GAIA with touch, voice, or push",
        description:
          "Chat by typing or voice, manage tasks with long-press bulk select, and receive workflow completions as native push notifications.",
      },
    ],
    faqs: [
      {
        question: "Is the mobile app a full version or a lighter version?",
        answer:
          "Full version. Every feature available on web — chat, todos, workflows, integrations, voice, goals, reminders — is available on mobile with the same capabilities.",
      },
      {
        question: "Does the mobile app work offline?",
        answer:
          "Past conversations and tasks are cached locally and browsable without a connection. New requests and actions require an internet connection.",
      },
      {
        question: "Are push notifications supported?",
        answer:
          "Yes. Workflow completions, reminders, and scheduled briefings are delivered as OS-level push notifications on both iOS and Android.",
      },
      {
        question: "Is there a tablet layout?",
        answer:
          "Yes. The app adapts to iPad and Android tablets with a split-view layout showing the conversation list alongside the active chat.",
      },
    ],
    useCases: [
      {
        title: "Morning briefing on the commute",
        description:
          "An executive opens GAIA on their phone every morning to review the automated briefing — calendar, emails, and todos for the day — before arriving at the office.",
      },
      {
        title: "Voice task capture while driving",
        description:
          "A sales rep dictates new tasks and follow-up reminders to GAIA hands-free via the mobile app's voice mode while driving between client meetings.",
      },
      {
        title: "Real-time workflow notifications",
        description:
          "A developer receives a push notification the moment a scheduled deployment workflow completes, with a summary of what ran and whether it succeeded.",
      },
    ],
    relatedSlugs: ["voice", "smart-chat", "telegram-bot"],
    demoComponent: "mobile",
  },
];
