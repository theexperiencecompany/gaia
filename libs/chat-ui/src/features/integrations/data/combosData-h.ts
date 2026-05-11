import type { IntegrationCombo } from "./combosData";

export const combosBatchH: Record<string, IntegrationCombo> = {
  "teams-slack": {
    slug: "teams-slack",
    toolA: "Microsoft Teams",
    toolASlug: "microsoft-teams",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline: "Bridge Teams and Slack for seamless dual-platform collaboration",
    metaTitle: "Microsoft Teams + Slack Automation - Unified Team Comms | GAIA",
    metaDescription:
      "Connect Microsoft Teams and Slack with GAIA. Mirror messages across platforms, route alerts to the right tool, and keep dual-platform teams aligned automatically.",
    keywords: [
      "microsoft teams slack integration",
      "connect teams slack",
      "teams slack automation",
      "gaia microsoft teams slack",
      "teams slack workflow",
    ],
    intro:
      "Organizations that have grown through acquisitions or departmental preferences often find themselves running both Microsoft Teams and Slack simultaneously. Messages sent in one platform go unseen by colleagues on the other, and critical decisions get siloed inside whichever tool a team happens to prefer.\n\nGAIA bridges the gap by routing messages, alerts, and notifications between Teams and Slack automatically. Announcements posted in a Teams channel can be mirrored to the equivalent Slack channel, and Slack bot alerts can be forwarded to Teams so every stakeholder stays informed regardless of which platform they live in.",
    useCases: [
      {
        title: "Mirror announcements across platforms",
        description:
          "Company-wide announcements posted in Teams are automatically reposted to the corresponding Slack channel. Every employee sees the message in their preferred tool without the sender duplicating effort.",
      },
      {
        title: "Route support alerts to the right platform",
        description:
          "Monitoring alerts configured for Slack are forwarded to Teams channels where on-call engineers work. Incidents get the right eyes on them immediately regardless of platform preference.",
      },
      {
        title: "Cross-platform meeting summaries",
        description:
          "After a Teams meeting concludes, GAIA posts an AI-generated summary to the relevant Slack channel. Slack-native teammates stay in the loop without needing a Teams account.",
      },
      {
        title: "Unified status updates",
        description:
          "Project status messages from Slack workflows are mirrored into Teams project channels. Leadership teams using Teams always have current project visibility.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Microsoft Teams and Slack to GAIA",
        description:
          "Authorize GAIA with your Teams tenant and Slack workspace in a few clicks. GAIA securely stores credentials and begins monitoring both platforms.",
      },
      {
        step: "Configure channel mappings and routing rules",
        description:
          "Specify which Teams channels map to which Slack channels and set filters for message types, keywords, or senders to route. GAIA applies your rules without syncing noise.",
      },
      {
        step: "GAIA automates cross-platform messaging",
        description:
          "Messages matching your rules are formatted and posted to the target platform in real time. GAIA attributes the source clearly so recipients know where the message originated.",
      },
    ],
    faqs: [
      {
        question: "Will GAIA create an infinite loop of mirrored messages?",
        answer:
          "No. GAIA tags mirrored messages internally and skips re-processing them. Only original messages trigger cross-platform forwarding.",
      },
      {
        question: "Can I filter which messages get mirrored?",
        answer:
          "Yes. You can restrict mirroring to specific channels, message types, or keywords. GAIA gives you granular control so only meaningful content crosses platforms.",
      },
      {
        question: "Does this work with private channels?",
        answer:
          "GAIA can access private channels in both platforms if granted the appropriate permissions during setup. You control which channels are in scope.",
      },
    ],
  },

  "teams-notion": {
    slug: "teams-notion",
    toolA: "Microsoft Teams",
    toolASlug: "microsoft-teams",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Save Teams meeting notes and decisions to Notion automatically",
    metaTitle:
      "Microsoft Teams + Notion Automation - Meeting Notes to Docs | GAIA",
    metaDescription:
      "Connect Microsoft Teams and Notion with GAIA. Auto-save meeting summaries, decisions, and action items from Teams to structured Notion pages.",
    keywords: [
      "microsoft teams notion integration",
      "connect teams notion",
      "teams notion automation",
      "gaia microsoft teams notion",
      "teams meeting notes notion",
    ],
    intro:
      "Microsoft Teams hosts hundreds of meetings every week, but the knowledge shared in those calls rarely makes it into a searchable, organized format. Meeting notes live in someone's local document or get lost in chat history, making it nearly impossible to recall decisions or action items weeks later.\n\nGAIA automatically captures Teams meeting summaries and posts them as structured Notion pages. Action items become tasks in your Notion project database, and key decisions are logged with context so your team builds an institutional knowledge base with zero manual effort.",
    useCases: [
      {
        title: "Auto-generate meeting notes in Notion",
        description:
          "After every Teams meeting, GAIA creates a Notion page with an AI-generated summary, attendees, and key discussion points. Teams accumulate a searchable archive of every conversation.",
      },
      {
        title: "Capture action items as Notion tasks",
        description:
          "Action items discussed in Teams meetings are extracted by GAIA and added as tasks in the linked Notion database with assignees and due dates pre-filled.",
      },
      {
        title: "Log decisions to a Notion decision register",
        description:
          "Decisions made during Teams calls are logged to a dedicated Notion database with date, context, and owner. Teams build an auditable record of how and why decisions were made.",
      },
      {
        title: "Post Teams channel highlights to Notion",
        description:
          "Pinned messages and important threads from Teams channels are summarized and saved to the relevant Notion project page, keeping documentation current without manual copy-pasting.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Microsoft Teams and Notion to GAIA",
        description:
          "Authorize GAIA with your Teams tenant and Notion workspace. GAIA gains access to meeting transcripts and your target Notion databases.",
      },
      {
        step: "Configure Notion templates and mappings",
        description:
          "Select which Notion databases receive meeting notes, tasks, and decisions. GAIA uses your existing templates so new pages match your documentation style.",
      },
      {
        step: "GAIA automates post-meeting documentation",
        description:
          "When a Teams meeting ends, GAIA processes the transcript, populates the Notion page, and notifies attendees with a link. Documentation is done before anyone leaves the call.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA require Teams transcription to be enabled?",
        answer:
          "Yes, Teams meeting transcription must be enabled in your tenant for GAIA to process meeting content. GAIA works with the transcript data Teams generates.",
      },
      {
        question: "Can I customize the Notion page structure?",
        answer:
          "Yes. GAIA supports custom Notion templates so the generated pages match your team's existing documentation format including properties, sections, and linked databases.",
      },
      {
        question: "How quickly does the Notion page appear after a meeting?",
        answer:
          "GAIA typically creates the Notion page within a few minutes of the meeting ending, once the Teams transcript is processed and available.",
      },
    ],
  },

  "teams-github": {
    slug: "teams-github",
    toolA: "Microsoft Teams",
    toolASlug: "microsoft-teams",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline: "Get GitHub PR and issue notifications directly in Teams channels",
    metaTitle:
      "Microsoft Teams + GitHub Automation - Dev Alerts in Teams | GAIA",
    metaDescription:
      "Connect Microsoft Teams and GitHub with GAIA. Post pull request updates, issue alerts, and CI status to Teams channels and keep your engineering team informed.",
    keywords: [
      "microsoft teams github integration",
      "connect teams github",
      "teams github automation",
      "gaia microsoft teams github",
      "github notifications teams",
    ],
    intro:
      "Engineering teams that use Microsoft Teams for communication need GitHub activity to surface in their chat, not buried in email notifications or the GitHub web interface. Pull requests waiting for review, failing CI pipelines, and new issue reports all require fast human attention that email simply cannot deliver.\n\nGAIA connects GitHub to Microsoft Teams so every relevant event — PR opened, review requested, CI failed, issue labeled — appears as a formatted Teams message in the right channel. Engineers spend less time checking GitHub manually and more time shipping code.",
    useCases: [
      {
        title: "Pull request review notifications",
        description:
          "When a PR is opened or a review is requested, GAIA posts a formatted card to the Teams engineering channel with the PR title, author, and a direct link. Reviewers see requests immediately.",
      },
      {
        title: "CI/CD pipeline failure alerts",
        description:
          "Failed GitHub Actions runs trigger an instant Teams alert with the workflow name, failing step, and branch. The on-call engineer can act within seconds of a pipeline breaking.",
      },
      {
        title: "Issue triage notifications",
        description:
          "New GitHub issues labeled 'bug' or 'urgent' are posted to the Teams support channel automatically. Triage happens in Teams without requiring everyone to monitor GitHub directly.",
      },
      {
        title: "Release and deployment announcements",
        description:
          "When a GitHub release is published, GAIA posts the release notes to the Teams product channel. The whole team is informed the moment a new version ships.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Microsoft Teams and GitHub to GAIA",
        description:
          "Authorize GAIA with your Teams tenant and GitHub organization. GAIA sets up webhooks on the repositories you select.",
      },
      {
        step: "Map repositories to Teams channels",
        description:
          "Specify which repositories send notifications to which Teams channels and which event types to include. GAIA filters noise so only meaningful events reach your team.",
      },
      {
        step: "GAIA automates GitHub-to-Teams notifications",
        description:
          "GitHub events matching your rules are formatted into rich Teams adaptive cards and posted in real time. Engineers get full context without leaving Teams.",
      },
    ],
    faqs: [
      {
        question: "Can I choose which GitHub events trigger Teams messages?",
        answer:
          "Yes. GAIA lets you select from events including PR opened, PR merged, review requested, CI failure, issue created, and release published. You control the signal-to-noise ratio.",
      },
      {
        question: "Can different repos post to different Teams channels?",
        answer:
          "Yes. Each repository can be mapped to a separate Teams channel. For example, frontend PRs go to #frontend and infrastructure alerts go to #ops.",
      },
      {
        question: "Does GAIA support GitHub Enterprise?",
        answer:
          "GAIA supports GitHub Enterprise as well as GitHub.com. Provide your Enterprise hostname during setup and GAIA connects to your self-hosted instance.",
      },
    ],
  },

  "teams-google-calendar": {
    slug: "teams-google-calendar",
    toolA: "Microsoft Teams",
    toolASlug: "microsoft-teams",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline: "Keep Teams meetings and Google Calendar in perfect sync",
    metaTitle:
      "Microsoft Teams + Google Calendar Sync - Unified Scheduling | GAIA",
    metaDescription:
      "Connect Microsoft Teams and Google Calendar with GAIA. Sync meetings bidirectionally, avoid double-bookings, and keep your schedule unified across both platforms.",
    keywords: [
      "microsoft teams google calendar integration",
      "connect teams google calendar",
      "teams google calendar sync",
      "gaia microsoft teams google calendar",
      "teams google calendar workflow",
    ],
    intro:
      "Many professionals live in Google Calendar for personal scheduling while their employer uses Microsoft Teams for meetings. The result is a fragmented calendar where Teams meeting invites and Google Calendar events exist in separate silos, making it easy to double-book or miss meetings entirely.\n\nGAIA synchronizes Microsoft Teams meetings with Google Calendar bidirectionally. New Teams meetings appear in Google Calendar automatically, and Google Calendar events can trigger Teams meeting creation with the correct join link. Your schedule is always unified in the calendar you prefer to use.",
    useCases: [
      {
        title: "Auto-add Teams meetings to Google Calendar",
        description:
          "When a Teams meeting is scheduled, GAIA creates a corresponding Google Calendar event with the Teams join link embedded. You see all meetings in one place.",
      },
      {
        title: "Prevent double-bookings across platforms",
        description:
          "GAIA checks availability in both Teams and Google Calendar before confirming a new meeting. Conflicts are surfaced before they cause scheduling collisions.",
      },
      {
        title: "Daily agenda from both calendars",
        description:
          "Each morning, GAIA compiles your Teams meetings and Google Calendar events into a unified agenda posted to your Teams chat. You start the day with a complete schedule.",
      },
      {
        title: "Meeting reminders via Teams message",
        description:
          "GAIA sends a Teams message reminder 10 minutes before Google Calendar events that have no Teams counterpart, so you never miss an external meeting while working in Teams.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Microsoft Teams and Google Calendar to GAIA",
        description:
          "Authorize GAIA with your Teams account and Google Calendar. GAIA reads and writes to both calendars with the permissions you grant.",
      },
      {
        step: "Set sync direction and preferences",
        description:
          "Choose one-way or bidirectional sync, set which calendars to include, and configure reminder preferences. GAIA applies your rules to keep the sync clean.",
      },
      {
        step: "GAIA automates calendar synchronization",
        description:
          "New and updated meetings in either platform are mirrored to the other in real time. Your schedule stays unified without manual duplication.",
      },
    ],
    faqs: [
      {
        question: "Will the Teams join link appear in Google Calendar?",
        answer:
          "Yes. GAIA embeds the Teams meeting join URL in the Google Calendar event description so attendees can join directly from either platform.",
      },
      {
        question: "Does GAIA sync cancellations and rescheduling?",
        answer:
          "Yes. When a Teams meeting is cancelled or rescheduled, GAIA updates or removes the corresponding Google Calendar event automatically.",
      },
      {
        question: "Can I limit sync to specific calendars?",
        answer:
          "Yes. During setup you select which Google Calendar calendars and which Teams calendars participate in the sync, keeping personal and work events separate if preferred.",
      },
    ],
  },

  "teams-asana": {
    slug: "teams-asana",
    toolA: "Microsoft Teams",
    toolASlug: "microsoft-teams",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline:
      "Bring Asana project updates into Teams and create tasks from chat",
    metaTitle:
      "Microsoft Teams + Asana Automation - Tasks Meet Team Chat | GAIA",
    metaDescription:
      "Connect Microsoft Teams and Asana with GAIA. Post Asana project updates to Teams channels and turn Teams messages into Asana tasks without leaving chat.",
    keywords: [
      "microsoft teams asana integration",
      "connect teams asana",
      "teams asana automation",
      "gaia microsoft teams asana",
      "teams asana workflow",
    ],
    intro:
      "Project managers track work in Asana while the team communicates in Microsoft Teams, creating a gap where task updates and chat decisions live in separate places. Important action items decided in Teams never make it into Asana, and Asana deadline changes go unnoticed by teammates in Teams.\n\nGAIA closes this gap by posting Asana project milestones and task updates to Teams channels and by letting team members create Asana tasks directly from Teams messages. Work gets captured where decisions are made and tracked where projects are managed.",
    useCases: [
      {
        title: "Post Asana milestone updates to Teams",
        description:
          "When a project milestone is completed in Asana, GAIA posts a celebration update to the Teams project channel. The whole team sees progress without needing to open Asana.",
      },
      {
        title: "Create Asana tasks from Teams messages",
        description:
          "React to any Teams message with a designated emoji or use a slash command to have GAIA create an Asana task from it. Action items are captured instantly without leaving the conversation.",
      },
      {
        title: "Deadline approaching alerts",
        description:
          "GAIA monitors Asana tasks approaching their due date and posts a warning to the Teams channel. Assignees are tagged so nothing slips past a deadline unnoticed.",
      },
      {
        title: "Daily standup digest from Asana",
        description:
          "Before standup each morning, GAIA posts a digest of each team member's Asana tasks due today to the Teams standup channel. The team arrives at standup already up to speed.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Microsoft Teams and Asana to GAIA",
        description:
          "Authorize GAIA with your Teams tenant and Asana workspace. GAIA links your Asana projects to their corresponding Teams channels.",
      },
      {
        step: "Configure update triggers and task creation rules",
        description:
          "Choose which Asana events post to Teams and how Teams message commands map to Asana projects. GAIA gives you per-project control.",
      },
      {
        step: "GAIA automates task and project communication",
        description:
          "Asana events appear in Teams as formatted cards with direct links, and Teams-originated tasks are created in Asana with full context. Both tools stay current automatically.",
      },
    ],
    faqs: [
      {
        question: "Can any Teams member create Asana tasks, or only admins?",
        answer:
          "Any Teams member whose Asana account is connected to GAIA can create tasks from Teams messages. You can restrict this to specific roles if needed.",
      },
      {
        question: "Which Asana events can trigger Teams messages?",
        answer:
          "GAIA supports task completion, milestone achieved, due date approaching, task assigned, and project status changed as trigger events. You choose which ones to enable.",
      },
      {
        question: "Does GAIA support Asana portfolios and goals?",
        answer:
          "Yes. GAIA can post portfolio-level status updates and goal progress to Teams channels so leadership gets high-level visibility without drilling into Asana.",
      },
    ],
  },

  "drive-slack": {
    slug: "drive-slack",
    toolA: "Google Drive",
    toolASlug: "google-drive",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline: "Share Drive files in Slack and auto-save Slack files to Drive",
    metaTitle:
      "Google Drive + Slack Automation - File Sharing Made Easy | GAIA",
    metaDescription:
      "Connect Google Drive and Slack with GAIA. Share Drive files with proper permissions in Slack channels and automatically save important Slack files to Drive folders.",
    keywords: [
      "google drive slack integration",
      "connect google drive slack",
      "google drive slack automation",
      "gaia google drive slack",
      "google drive slack workflow",
    ],
    intro:
      "Teams share files in Slack constantly, but those attachments disappear into Slack's storage with no organization and limited searchability. Meanwhile, important Google Drive documents are shared via long links in chat without proper access control, leaving colleagues unable to open them.\n\nGAIA connects Google Drive and Slack so file sharing becomes effortless and organized. Files shared in Slack can be automatically saved to the right Drive folder, and Drive file links shared in Slack are enriched with previews and access-checked links. Your team's documents stay organized in Drive while the sharing experience lives in Slack.",
    useCases: [
      {
        title: "Auto-save Slack file uploads to Drive",
        description:
          "Files uploaded to designated Slack channels are automatically saved to the corresponding Google Drive folder. Attachments are organized and searchable rather than lost in Slack storage.",
      },
      {
        title: "Share Drive files with correct permissions",
        description:
          "When you ask GAIA to share a Drive file in a Slack channel, it checks and sets view permissions for all channel members before posting. No more 'request access' errors.",
      },
      {
        title: "Drive file change notifications in Slack",
        description:
          "When a collaborator edits a shared Drive document, GAIA posts a notification to the relevant Slack channel. Reviewers are alerted the moment new content is ready.",
      },
      {
        title: "Search Drive from Slack",
        description:
          "Ask GAIA in any Slack channel to find a Drive document by name or topic. GAIA searches your Drive and returns a direct link without you ever leaving Slack.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Drive and Slack to GAIA",
        description:
          "Authorize GAIA with your Google Drive and Slack workspace. GAIA gets the permissions needed to read, write, and manage sharing settings on Drive files.",
      },
      {
        step: "Configure folder mappings and channel rules",
        description:
          "Map Slack channels to Google Drive folders and set rules for which file types to auto-save. GAIA applies your organization structure automatically.",
      },
      {
        step: "GAIA automates file sharing and organization",
        description:
          "Files flow between Slack and Drive according to your rules. Uploads are organized, links are permission-checked, and change alerts keep the team informed.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA save every file shared in Slack to Drive?",
        answer:
          "No. You configure which channels and file types trigger auto-save. GAIA only moves files that match your defined rules, avoiding clutter.",
      },
      {
        question: "Can GAIA set specific sharing permissions on Drive files?",
        answer:
          "Yes. GAIA can set viewer, commenter, or editor permissions for individuals or entire Slack channels when sharing a Drive file via chat.",
      },
      {
        question: "What file types are supported?",
        answer:
          "GAIA supports all Google Drive native file types (Docs, Sheets, Slides) as well as uploaded files including PDFs, images, and Office documents.",
      },
    ],
  },

  "drive-notion": {
    slug: "drive-notion",
    toolA: "Google Drive",
    toolASlug: "google-drive",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Attach Drive files to Notion pages and organize Drive by project",
    metaTitle:
      "Google Drive + Notion Automation - Connect Docs and Pages | GAIA",
    metaDescription:
      "Connect Google Drive and Notion with GAIA. Embed Drive files in Notion pages, organize Drive folders by project, and keep documentation and files in sync.",
    keywords: [
      "google drive notion integration",
      "connect google drive notion",
      "google drive notion automation",
      "gaia google drive notion",
      "google drive notion workflow",
    ],
    intro:
      "Google Drive and Notion serve complementary purposes — Drive stores raw files while Notion structures knowledge and projects. But teams often maintain two separate systems that don't reference each other, forcing colleagues to hunt through Drive for the file mentioned in a Notion page or vice versa.\n\nGAIA links Google Drive and Notion so files and documentation stay connected. Drive documents can be embedded in Notion pages automatically when projects start, and new Notion project pages trigger the creation of organized Drive folder structures. Your files and your documentation always know about each other.",
    useCases: [
      {
        title: "Embed Drive files in Notion project pages",
        description:
          "When a new Drive document is added to a project folder, GAIA attaches it to the corresponding Notion project page. Team members find all relevant files without leaving Notion.",
      },
      {
        title: "Auto-create Drive folders from Notion projects",
        description:
          "When a new project page is created in Notion, GAIA creates a structured Drive folder hierarchy for that project. File organization mirrors your project structure from day one.",
      },
      {
        title: "Sync document status between Drive and Notion",
        description:
          "When a Drive document is moved to a 'Final' folder, GAIA updates the linked Notion page status to 'Completed.' Document and project status stay consistent automatically.",
      },
      {
        title: "Aggregate Drive files into Notion dashboards",
        description:
          "GAIA scans Drive folders and populates a Notion database with file names, owners, and links. Teams get a searchable index of all project documents inside Notion.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Drive and Notion to GAIA",
        description:
          "Authorize GAIA with your Google Drive and Notion workspace. GAIA maps your Drive folder structure to your Notion database schema.",
      },
      {
        step: "Configure project and folder mappings",
        description:
          "Define how Notion projects correspond to Drive folders and which file types to surface in Notion. GAIA uses these mappings to keep both systems aligned.",
      },
      {
        step: "GAIA automates file-to-documentation linking",
        description:
          "New files, folder changes, and document status updates flow between Drive and Notion according to your rules. Both systems reflect the same project reality.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA embed a Drive file preview inside a Notion page?",
        answer:
          "Yes. GAIA embeds Drive files as Notion embed blocks so collaborators can preview documents directly within the Notion page without downloading.",
      },
      {
        question: "Does GAIA create sub-folders or just top-level folders?",
        answer:
          "GAIA can create multi-level folder hierarchies in Drive based on templates you define. For example, each Notion project gets Assets, Deliverables, and Archive sub-folders automatically.",
      },
      {
        question: "What happens if a Drive file is deleted?",
        answer:
          "GAIA can detect Drive file deletions and update the linked Notion page to mark the attachment as unavailable, keeping Notion documentation accurate.",
      },
    ],
  },

  "drive-asana": {
    slug: "drive-asana",
    toolA: "Google Drive",
    toolASlug: "google-drive",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline:
      "Attach Drive documents to Asana tasks and keep project files organized",
    metaTitle:
      "Google Drive + Asana Automation - Files Meet Task Management | GAIA",
    metaDescription:
      "Connect Google Drive and Asana with GAIA. Attach relevant Drive files to Asana tasks automatically, create Drive folders for new projects, and keep work organized.",
    keywords: [
      "google drive asana integration",
      "connect google drive asana",
      "google drive asana automation",
      "gaia google drive asana",
      "google drive asana workflow",
    ],
    intro:
      "Asana tasks often reference documents stored in Google Drive, but linking them manually is tedious and easy to forget. Team members end up hunting through Drive to find the brief, spec, or design file associated with a task they're working on, wasting time that should go toward actual work.\n\nGAIA connects Google Drive and Asana so relevant files are attached to tasks automatically. When a new Asana project is created, GAIA builds the matching Drive folder structure. When a Drive document changes, GAIA updates the linked Asana task to flag the revision. Files and tasks stay connected throughout the project lifecycle.",
    useCases: [
      {
        title: "Auto-attach Drive files to Asana tasks",
        description:
          "When a Drive file is added to a project folder, GAIA attaches it to the relevant Asana task automatically. Team members find everything they need directly on the task card.",
      },
      {
        title: "Create Drive folders when Asana projects launch",
        description:
          "New Asana projects trigger GAIA to create a corresponding Drive folder with standard sub-folders. File organization is consistent from the first day of every project.",
      },
      {
        title: "Flag document revisions on Asana tasks",
        description:
          "When an attached Drive document is edited, GAIA posts a comment on the Asana task noting the change. Assignees are always aware of the latest file version.",
      },
      {
        title: "Compile project deliverables in Drive at completion",
        description:
          "When an Asana project is marked complete, GAIA collects all task attachments and organizes them into a final deliverables folder in Drive for easy archiving.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Drive and Asana to GAIA",
        description:
          "Authorize GAIA with your Google Drive and Asana workspace. GAIA links Asana projects to their Drive folder counterparts.",
      },
      {
        step: "Define folder templates and attachment rules",
        description:
          "Set which Drive folders correspond to which Asana projects and how file types map to task sections. GAIA uses these rules to route files automatically.",
      },
      {
        step: "GAIA automates file attachment and organization",
        description:
          "Files added to Drive folders are attached to Asana tasks and revision alerts are posted as comments. Project files stay organized and always accessible from tasks.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA attach every Drive file or only specific types?",
        answer:
          "You configure which file types and folders trigger task attachment. GAIA only attaches files that match your defined rules, keeping tasks clean.",
      },
      {
        question:
          "Can GAIA set Drive file permissions when attaching to Asana?",
        answer:
          "Yes. When attaching a Drive file to an Asana task, GAIA can automatically grant view access to all task assignees and followers.",
      },
      {
        question: "Does this work with Asana custom fields?",
        answer:
          "Yes. GAIA can populate Asana custom fields such as 'Drive link' or 'Document status' based on the attached Drive file metadata.",
      },
    ],
  },

  "drive-trello": {
    slug: "drive-trello",
    toolA: "Google Drive",
    toolASlug: "google-drive",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Attach Drive files to Trello cards and keep project docs accessible",
    metaTitle: "Google Drive + Trello Automation - Files on Every Card | GAIA",
    metaDescription:
      "Connect Google Drive and Trello with GAIA. Automatically attach Drive documents to Trello cards, create Drive folders for boards, and keep project files organized.",
    keywords: [
      "google drive trello integration",
      "connect google drive trello",
      "google drive trello automation",
      "gaia google drive trello",
      "google drive trello workflow",
    ],
    intro:
      "Trello boards give teams a visual overview of work in progress, but files related to each card still live in Google Drive without a clear connection. Team members switch between Trello and Drive constantly to find the document they need, breaking flow and causing version confusion when multiple Drive files exist for a single card.\n\nGAIA links Google Drive and Trello so the right files are always attached to the right cards. Drive documents added to project folders are attached to corresponding Trello cards, and creating a new Trello board triggers the creation of an organized Drive folder structure. Files and cards stay connected from kickoff to completion.",
    useCases: [
      {
        title: "Auto-attach Drive files to Trello cards",
        description:
          "When a Drive document is added to a project folder, GAIA attaches it to the matching Trello card. Every card has its relevant files without anyone manually adding attachments.",
      },
      {
        title: "Create Drive folders when Trello boards launch",
        description:
          "A new Trello board triggers GAIA to create a structured Drive folder with lists matching the board's columns. File organization mirrors your workflow from day one.",
      },
      {
        title: "Document revision alerts as Trello card comments",
        description:
          "When an attached Drive document is edited, GAIA posts a comment on the Trello card noting the update. Card members are notified and can review the latest version immediately.",
      },
      {
        title: "Archive card files to Drive on completion",
        description:
          "When a Trello card moves to the 'Done' list, GAIA organizes its attached Drive files into an archive folder. Completed work is preserved and searchable.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Drive and Trello to GAIA",
        description:
          "Authorize GAIA with your Google Drive and Trello account. GAIA maps Trello boards and lists to corresponding Drive folders.",
      },
      {
        step: "Configure folder templates and card attachment rules",
        description:
          "Define which Drive folders map to which Trello boards and how file additions trigger card attachments. GAIA applies your rules consistently.",
      },
      {
        step: "GAIA automates file-to-card linking",
        description:
          "Drive file additions and edits are reflected on Trello cards in real time. Teams always find the latest files directly on the card without searching Drive.",
      },
    ],
    faqs: [
      {
        question: "Will GAIA attach every file in Drive to a Trello card?",
        answer:
          "No. GAIA only attaches files from folders you map to specific Trello boards. You maintain full control over which Drive content surfaces on cards.",
      },
      {
        question: "Can GAIA grant Drive access to Trello card members?",
        answer:
          "Yes. When attaching a Drive file to a Trello card, GAIA can automatically grant view or edit permissions to all current card members.",
      },
      {
        question:
          "Does GAIA support Trello Power-Ups in addition to direct integration?",
        answer:
          "GAIA works at the API level and is independent of Trello Power-Ups. It provides automation capabilities beyond what the built-in Google Drive Power-Up offers.",
      },
    ],
  },

  "figma-slack": {
    slug: "figma-slack",
    toolA: "Figma",
    toolASlug: "figma",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline: "Get Figma design updates and comment alerts directly in Slack",
    metaTitle: "Figma + Slack Automation - Design Notifications in Chat | GAIA",
    metaDescription:
      "Connect Figma and Slack with GAIA. Post design update notifications, comment alerts, and version changes from Figma to Slack channels automatically.",
    keywords: [
      "figma slack integration",
      "connect figma slack",
      "figma slack automation",
      "gaia figma slack",
      "figma slack workflow",
    ],
    intro:
      "Design teams share Figma files with product managers, engineers, and stakeholders who have no reliable way to know when designs change. Important comment threads in Figma go unnoticed by developers who are heads-down in Slack, causing feedback loops to stall and designs to ship without incorporating requested changes.\n\nGAIA connects Figma and Slack so design activity surfaces where the team already communicates. New comments, frame updates, and version publishes in Figma appear as Slack notifications in the right channel, ensuring stakeholders stay informed and feedback gets actioned quickly.",
    useCases: [
      {
        title: "Comment notifications in Slack",
        description:
          "When a comment is added to a Figma file, GAIA posts a notification to the Slack channel with the commenter name, comment text, and a direct link to the frame. Feedback is visible instantly.",
      },
      {
        title: "Design version published alerts",
        description:
          "When a designer publishes a new Figma version, GAIA notifies the product and engineering Slack channels. Stakeholders know a design is ready for review without polling Figma.",
      },
      {
        title: "Frame status change notifications",
        description:
          "When a frame is tagged as 'Ready for Development' in Figma, GAIA alerts the engineering Slack channel. Handoffs happen automatically without a separate message.",
      },
      {
        title: "Daily design activity digest",
        description:
          "GAIA posts a morning summary of yesterday's Figma activity — new comments, resolved threads, and version changes — to the design Slack channel. The team starts each day aligned.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Figma and Slack to GAIA",
        description:
          "Authorize GAIA with your Figma account and Slack workspace. GAIA monitors the Figma files and projects you specify for activity.",
      },
      {
        step: "Map Figma files to Slack channels",
        description:
          "Specify which Figma projects send notifications to which Slack channels and which event types to include. GAIA filters noise so only meaningful activity is surfaced.",
      },
      {
        step: "GAIA automates design-to-chat notifications",
        description:
          "Figma events matching your rules are formatted and posted to Slack in real time. Teams get full context including file name, frame name, and a deep link.",
      },
    ],
    faqs: [
      {
        question: "Can I receive notifications for only specific Figma files?",
        answer:
          "Yes. GAIA lets you select individual Figma files or entire projects to monitor. Unrelated files produce no Slack noise.",
      },
      {
        question:
          "Does GAIA notify the specific person mentioned in a Figma comment?",
        answer:
          "Yes. If a Figma comment mentions a team member with @, GAIA can DM them in Slack so they are personally notified of the mention.",
      },
      {
        question: "Can developers reply to Figma comments from Slack?",
        answer:
          "GAIA can post replies back to Figma comment threads on behalf of a connected user. Responding to feedback without leaving Slack is possible with this setup.",
      },
    ],
  },

  "figma-notion": {
    slug: "figma-notion",
    toolA: "Figma",
    toolASlug: "figma",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Embed Figma designs in Notion pages and sync design status",
    metaTitle: "Figma + Notion Automation - Designs Inside Your Docs | GAIA",
    metaDescription:
      "Connect Figma and Notion with GAIA. Embed live Figma frames in Notion project pages, sync design status to databases, and keep documentation and design in sync.",
    keywords: [
      "figma notion integration",
      "connect figma notion",
      "figma notion automation",
      "gaia figma notion",
      "figma notion workflow",
    ],
    intro:
      "Product and design teams maintain Notion pages for requirements and specifications while the actual designs live in Figma. The disconnect means that Notion documents reference outdated screenshots instead of live designs, and design status updates in Figma never reach the project tracking databases in Notion.\n\nGAIA links Figma and Notion so designs are always embedded live in the right pages and design status flows into Notion databases automatically. When a designer marks a frame ready, the Notion feature page reflects it. When a new Notion feature page is created, GAIA creates a linked Figma file ready for design work.",
    useCases: [
      {
        title: "Embed live Figma frames in Notion pages",
        description:
          "When a new Figma frame is created for a feature, GAIA embeds it live in the corresponding Notion page. Stakeholders always see the current design, not a stale screenshot.",
      },
      {
        title: "Sync design status to Notion project database",
        description:
          "When a Figma file's status changes to 'Ready for Review,' GAIA updates the Notion project database record. Product managers see design progress without leaving Notion.",
      },
      {
        title: "Create Figma files from Notion project pages",
        description:
          "When a new feature is created in the Notion product database, GAIA creates a corresponding Figma file from your team's template. Design starts organized and linked from day one.",
      },
      {
        title: "Log Figma version history in Notion",
        description:
          "Each time a Figma version is published, GAIA appends an entry to the design history table on the Notion page. Teams maintain a clear design changelog inside their documentation.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Figma and Notion to GAIA",
        description:
          "Authorize GAIA with your Figma account and Notion workspace. GAIA maps your Figma projects to the corresponding Notion databases.",
      },
      {
        step: "Configure embedding rules and status mappings",
        description:
          "Define which Figma files embed in which Notion pages and how Figma status tags map to Notion database properties. GAIA maintains these links automatically.",
      },
      {
        step: "GAIA automates design-to-documentation sync",
        description:
          "Figma updates flow into Notion in real time. Designs are embedded live, statuses are updated, and version history is logged without manual intervention.",
      },
    ],
    faqs: [
      {
        question: "Are Figma embeds in Notion live or static images?",
        answer:
          "GAIA uses Figma's embed URL to insert live, interactive embeds in Notion. Viewers see the current design and can navigate frames directly within the Notion page.",
      },
      {
        question: "Can GAIA sync Figma comments to Notion?",
        answer:
          "Yes. Figma comment threads can be mirrored to a comments section of the Notion page, giving non-Figma users visibility into design feedback without needing a Figma account.",
      },
      {
        question: "Does this work with Figma branches?",
        answer:
          "GAIA can track specific Figma branches and reflect branch status in Notion. When a branch is merged, the Notion page status updates accordingly.",
      },
    ],
  },

  "figma-asana": {
    slug: "figma-asana",
    toolA: "Figma",
    toolASlug: "figma",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline: "Link Figma design deliverables to Asana tasks automatically",
    metaTitle:
      "Figma + Asana Automation - Design Handoffs in Task Management | GAIA",
    metaDescription:
      "Connect Figma and Asana with GAIA. Link Figma design files to Asana tasks, update task status when designs are ready, and streamline design-to-development handoffs.",
    keywords: [
      "figma asana integration",
      "connect figma asana",
      "figma asana automation",
      "gaia figma asana",
      "figma asana workflow",
    ],
    intro:
      "Design handoffs are a perennial pain point between design and engineering teams. Designers mark a Figma file ready, but the corresponding Asana task for the engineer remains untouched. Engineers start development with no indication that the design has been finalized, or they build from an outdated version.\n\nGAIA connects Figma and Asana to automate the handoff. When a Figma design moves to 'Ready for Development,' the linked Asana task is updated, the design file is attached, and the assignee is notified. The design-to-development handoff happens automatically with zero manual coordination.",
    useCases: [
      {
        title: "Auto-update Asana tasks when designs are ready",
        description:
          "When a Figma frame is tagged 'Ready for Development,' GAIA updates the linked Asana task status and notifies the assigned engineer. Handoffs are instant and automatic.",
      },
      {
        title: "Attach Figma file links to Asana tasks",
        description:
          "When a Figma file is created for a feature, GAIA attaches the Figma link to the corresponding Asana task. Engineers always have direct access to the latest designs from the task.",
      },
      {
        title: "Create Asana tasks from Figma comment action items",
        description:
          "When a comment in Figma is marked as a revision request, GAIA creates an Asana task for the designer with the comment text and frame link. No revision gets lost in comment threads.",
      },
      {
        title: "Design milestone progress in Asana",
        description:
          "As Figma frames progress through design stages, GAIA updates the Asana project milestone completion percentage. Project managers see design progress in their existing tool.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Figma and Asana to GAIA",
        description:
          "Authorize GAIA with your Figma account and Asana workspace. GAIA links your Figma projects to their corresponding Asana projects.",
      },
      {
        step: "Map Figma status tags to Asana task states",
        description:
          "Define how Figma status labels correspond to Asana task sections and custom fields. GAIA translates design workflow stages into project management language.",
      },
      {
        step: "GAIA automates design handoffs and task updates",
        description:
          "Figma status changes trigger Asana task updates, file attachments, and assignee notifications. Handoffs are complete before anyone sends a single message.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA know which Figma file corresponds to which Asana task?",
        answer:
          "You configure the mapping during setup by linking Figma projects to Asana projects. GAIA then matches files and frames to tasks based on naming conventions or custom tags you define.",
      },
      {
        question:
          "Can GAIA handle multiple design revisions on the same Asana task?",
        answer:
          "Yes. Each time a new Figma version is published, GAIA appends a comment to the Asana task with the version number and link. The full revision history is visible on the task.",
      },
      {
        question: "Does GAIA work with Figma components and libraries?",
        answer:
          "GAIA focuses on Figma files and frames rather than component libraries. Handoff automation applies to design files associated with specific product features in Asana.",
      },
    ],
  },

  "stripe-slack": {
    slug: "stripe-slack",
    toolA: "Stripe",
    toolASlug: "stripe",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline:
      "Get payment alerts, MRR updates, and churn notifications in Slack",
    metaTitle: "Stripe + Slack Automation - Revenue Alerts in Team Chat | GAIA",
    metaDescription:
      "Connect Stripe and Slack with GAIA. Post payment notifications, MRR milestones, failed charge alerts, and churn warnings to Slack channels automatically.",
    keywords: [
      "stripe slack integration",
      "connect stripe slack",
      "stripe slack automation",
      "gaia stripe slack",
      "stripe payment notifications slack",
    ],
    intro:
      "Revenue events happen in Stripe but the team learns about them through manual dashboard checks or end-of-month reports. Failed payments go unnoticed for days, churn happens silently, and MRR milestones are celebrated after the fact instead of in real time when the energy is highest.\n\nGAIA connects Stripe to Slack so every meaningful revenue event surfaces immediately in the right channel. New subscriptions ring the virtual sales bell, failed charges alert the support team instantly, and MRR milestone posts keep the whole company motivated and informed without anyone opening the Stripe dashboard.",
    useCases: [
      {
        title: "New subscription and payment notifications",
        description:
          "Every new Stripe subscription triggers a Slack message in the sales channel with the customer name and plan. The team celebrates wins in real time as they happen.",
      },
      {
        title: "Failed payment alerts for immediate recovery",
        description:
          "Failed charges post an instant Slack alert to the support channel with the customer, amount, and failure reason. Recovery outreach begins within minutes instead of days.",
      },
      {
        title: "MRR milestone announcements",
        description:
          "When MRR crosses a milestone threshold, GAIA posts a company-wide Slack announcement. Revenue milestones are celebrated the moment they are achieved.",
      },
      {
        title: "Churn and cancellation alerts",
        description:
          "Subscription cancellations trigger a Slack alert to the customer success team with churn reason if available. Retention outreach can begin immediately after a cancellation.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Stripe and Slack to GAIA",
        description:
          "Authorize GAIA with your Stripe account and Slack workspace. GAIA listens to Stripe webhook events and routes them to your configured channels.",
      },
      {
        step: "Configure event types and channel routing",
        description:
          "Choose which Stripe events post to which Slack channels and set thresholds for MRR milestone alerts. GAIA gives you per-event control over routing.",
      },
      {
        step: "GAIA automates revenue event notifications",
        description:
          "Stripe events matching your rules are formatted into clear Slack messages with relevant customer and amount details posted in real time.",
      },
    ],
    faqs: [
      {
        question: "Can I set custom MRR milestone thresholds?",
        answer:
          "Yes. You configure any MRR values that should trigger a Slack announcement. GAIA tracks cumulative MRR and posts when your defined thresholds are crossed.",
      },
      {
        question: "Does GAIA expose sensitive customer data in Slack messages?",
        answer:
          "GAIA lets you control which data fields appear in Slack notifications. You can include customer name and amount while omitting payment method details to protect sensitive information.",
      },
      {
        question:
          "Can GAIA send Stripe alerts to different Slack channels by plan type?",
        answer:
          "Yes. You can route enterprise plan events to one channel and startup plan events to another. GAIA supports conditional routing based on Stripe metadata fields.",
      },
    ],
  },

  "stripe-notion": {
    slug: "stripe-notion",
    toolA: "Stripe",
    toolASlug: "stripe",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline:
      "Build revenue dashboards and track payments inside Notion databases",
    metaTitle: "Stripe + Notion Automation - Revenue Data in Your Docs | GAIA",
    metaDescription:
      "Connect Stripe and Notion with GAIA. Sync Stripe payment data to Notion databases, build revenue dashboards, and track subscriptions alongside your business documentation.",
    keywords: [
      "stripe notion integration",
      "connect stripe notion",
      "stripe notion automation",
      "gaia stripe notion",
      "stripe revenue dashboard notion",
    ],
    intro:
      "Business operators often want revenue data alongside their strategy documents, customer notes, and planning databases in Notion, but Stripe data is locked inside the Stripe dashboard. Building manual revenue reports in Notion means exporting CSVs and copy-pasting numbers that are outdated the moment they are entered.\n\nGAIA connects Stripe to Notion so revenue data flows automatically into your Notion databases. New subscriptions create records in your customer database, payment events update revenue tracking tables, and MRR figures refresh daily. Your Notion workspace becomes a live business intelligence hub without any manual data entry.",
    useCases: [
      {
        title: "Auto-create customer records from Stripe subscriptions",
        description:
          "When a new Stripe subscription is created, GAIA adds a record to your Notion customer database with plan, MRR contribution, and start date. Your CRM stays current automatically.",
      },
      {
        title: "Live MRR and revenue tracking in Notion",
        description:
          "GAIA updates a Notion revenue dashboard daily with current MRR, new revenue, and churn figures pulled from Stripe. Leadership has live revenue metrics without touching the Stripe dashboard.",
      },
      {
        title: "Payment event log in Notion",
        description:
          "Successful payments and failed charges are logged to a Notion database with date, customer, and amount. Finance teams have a searchable, filterable payment history inside Notion.",
      },
      {
        title: "Subscription change tracking",
        description:
          "Upgrades, downgrades, and cancellations in Stripe trigger updates to the Notion customer record. The subscription history for every customer is always current in your Notion CRM.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Stripe and Notion to GAIA",
        description:
          "Authorize GAIA with your Stripe account and Notion workspace. GAIA maps Stripe event types to your Notion database schemas.",
      },
      {
        step: "Configure Notion database mappings",
        description:
          "Define which Notion databases receive customer records, payment logs, and revenue metrics. GAIA uses your existing database properties to populate data correctly.",
      },
      {
        step: "GAIA automates Stripe-to-Notion data sync",
        description:
          "Stripe events create and update Notion records in real time. Revenue data, customer status, and payment history stay current without manual exports.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA backfill historical Stripe data into Notion?",
        answer:
          "Yes. During setup, GAIA can import existing Stripe customers and past payment records into Notion so your database starts populated with historical data.",
      },
      {
        question:
          "How frequently does GAIA update the Notion revenue dashboard?",
        answer:
          "GAIA updates the dashboard on a schedule you configure — hourly, daily, or on every Stripe event. Real-time updates are available for critical metrics like new subscriptions.",
      },
      {
        question: "Is sensitive billing data stored in Notion?",
        answer:
          "GAIA lets you choose which Stripe fields to sync to Notion. Payment method details and full card numbers are never synced — only business-relevant data like plan and amount.",
      },
    ],
  },

  "airtable-slack": {
    slug: "airtable-slack",
    toolA: "Airtable",
    toolASlug: "airtable",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline:
      "Post Airtable record updates to Slack and create records from chat",
    metaTitle: "Airtable + Slack Automation - Database Meets Team Chat | GAIA",
    metaDescription:
      "Connect Airtable and Slack with GAIA. Get Airtable record update notifications in Slack channels and create new Airtable records directly from Slack messages.",
    keywords: [
      "airtable slack integration",
      "connect airtable slack",
      "airtable slack automation",
      "gaia airtable slack",
      "airtable slack workflow",
    ],
    intro:
      "Airtable bases hold structured data for projects, CRMs, inventories, and more, but changes to that data go unnoticed by teammates who are active in Slack. Important record updates — a deal moving to closed, a task marked complete, an inventory item hitting zero — need to surface in chat where the team can act on them.\n\nGAIA connects Airtable and Slack bidirectionally. Record changes in Airtable trigger formatted Slack notifications in the right channel, and Slack messages can create or update Airtable records without the sender ever opening a browser tab. Data flows where the team lives.",
    useCases: [
      {
        title: "Record status change notifications in Slack",
        description:
          "When an Airtable record status field changes — a deal closes, a task completes, a request is approved — GAIA posts a Slack notification to the relevant channel. Teams act on changes the moment they happen.",
      },
      {
        title: "Create Airtable records from Slack messages",
        description:
          "Team members use a simple Slack command or message format to create Airtable records from chat. Leads, tasks, and requests captured in conversation are immediately stored in the right base.",
      },
      {
        title: "New record alerts for intake workflows",
        description:
          "When a new record is added to an Airtable form or base, GAIA notifies the responsible Slack channel. Intake requests, bug reports, and form submissions are actioned quickly.",
      },
      {
        title: "Daily Airtable summary digests in Slack",
        description:
          "GAIA posts a morning digest of key Airtable metrics — open tasks, pipeline value, pending requests — to the team Slack channel. Everyone starts the day with the same data.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Airtable and Slack to GAIA",
        description:
          "Authorize GAIA with your Airtable account and Slack workspace. GAIA links your Airtable bases and views to the relevant Slack channels.",
      },
      {
        step: "Configure trigger fields and message formats",
        description:
          "Define which Airtable field changes trigger Slack messages and how those messages are formatted. GAIA uses your Airtable field names to populate notifications with meaningful context.",
      },
      {
        step: "GAIA automates database-to-chat notifications",
        description:
          "Airtable record changes produce formatted Slack messages in real time, and Slack commands create Airtable records instantly. Both tools stay in sync without manual updates.",
      },
    ],
    faqs: [
      {
        question: "Can I filter notifications to only specific Airtable views?",
        answer:
          "Yes. GAIA can scope notifications to records that match a specific Airtable view filter. Only records relevant to a team's context appear in their Slack channel.",
      },
      {
        question: "Which Airtable field types can trigger Slack notifications?",
        answer:
          "GAIA supports triggers on single select, status, checkbox, date, and linked record field changes. You configure the specific fields and values that are meaningful.",
      },
      {
        question:
          "Can Slack notifications include linked record data from related tables?",
        answer:
          "Yes. GAIA can pull in linked record fields and roll-up values to include in Slack notifications, giving recipients complete context from related tables.",
      },
    ],
  },

  "airtable-notion": {
    slug: "airtable-notion",
    toolA: "Airtable",
    toolASlug: "airtable",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline: "Sync data between Airtable bases and Notion databases seamlessly",
    metaTitle: "Airtable + Notion Automation - Sync Your Databases | GAIA",
    metaDescription:
      "Connect Airtable and Notion with GAIA. Sync records bidirectionally between Airtable bases and Notion databases and keep structured data consistent across both tools.",
    keywords: [
      "airtable notion integration",
      "connect airtable notion",
      "airtable notion automation",
      "gaia airtable notion",
      "airtable notion sync",
    ],
    intro:
      "Teams often use Airtable for structured data management and Notion for documentation and project planning, resulting in duplicate data entry when the same information needs to live in both tools. A CRM record updated in Airtable never reflects in the Notion client page, and tasks added to a Notion project database don't appear in the Airtable operations tracker.\n\nGAIA syncs Airtable and Notion so data flows automatically between both systems. Record updates in Airtable propagate to the corresponding Notion database entries, and Notion page status changes update the linked Airtable records. Teams maintain one source of truth without choosing between the two tools they rely on.",
    useCases: [
      {
        title: "Sync Airtable CRM records to Notion client pages",
        description:
          "When a client record is updated in Airtable, GAIA updates the corresponding Notion client page with the latest status, owner, and notes. Both tools reflect the same information without duplicate entry.",
      },
      {
        title: "Mirror Notion project tasks to Airtable",
        description:
          "Tasks created in a Notion project database are automatically added to the Airtable operations base. Operations teams track all work in Airtable while project managers work in Notion.",
      },
      {
        title: "Sync status fields bidirectionally",
        description:
          "Status changes in Airtable flow to the linked Notion database record and vice versa. Teams working in either tool always see current status without manual reconciliation.",
      },
      {
        title: "Aggregate Airtable data in Notion dashboards",
        description:
          "GAIA pulls summary metrics from Airtable — counts, sums, averages — and updates Notion dashboard pages daily. Leadership sees live operational data inside their Notion workspace.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Airtable and Notion to GAIA",
        description:
          "Authorize GAIA with your Airtable account and Notion workspace. GAIA maps Airtable table fields to Notion database properties for each sync pair you configure.",
      },
      {
        step: "Configure field mappings and sync direction",
        description:
          "Define which fields sync between Airtable and Notion and whether sync is one-way or bidirectional. GAIA handles field type translation between the two platforms.",
      },
      {
        step: "GAIA automates cross-platform data sync",
        description:
          "Record changes in either platform are mirrored to the other according to your mappings. Data stays consistent without anyone manually updating two systems.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA handle field type differences between Airtable and Notion?",
        answer:
          "GAIA translates common field types automatically — Airtable select fields map to Notion select properties, Airtable dates map to Notion date properties. Custom mappings are available for edge cases.",
      },
      {
        question: "Can GAIA sync Airtable attachments to Notion?",
        answer:
          "Yes. Airtable attachment fields can be synced to Notion file and media properties. Files are transferred and linked so both records reference the same assets.",
      },
      {
        question: "Does bidirectional sync risk creating duplicate records?",
        answer:
          "No. GAIA assigns unique identifiers to synced records and tracks origin to prevent duplication. Records updated in either tool update their counterpart rather than creating a new entry.",
      },
    ],
  },

  "airtable-google-calendar": {
    slug: "airtable-google-calendar",
    toolA: "Airtable",
    toolASlug: "airtable",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Sync Airtable date fields to Google Calendar events automatically",
    metaTitle: "Airtable + Google Calendar Sync - Dates Become Events | GAIA",
    metaDescription:
      "Connect Airtable and Google Calendar with GAIA. Turn Airtable date fields into Google Calendar events, keep deadlines visible, and sync changes in real time.",
    keywords: [
      "airtable google calendar integration",
      "connect airtable google calendar",
      "airtable google calendar automation",
      "gaia airtable google calendar",
      "airtable google calendar sync",
    ],
    intro:
      "Airtable bases are rich with date fields — project deadlines, content publish dates, event schedules, campaign launches — but those dates sit inside Airtable where they're invisible to anyone who manages their time in Google Calendar. Important deadlines get missed because they never made it onto anyone's calendar.\n\nGAIA bridges Airtable and Google Calendar by turning Airtable date records into Google Calendar events automatically. When a deadline is added or changed in Airtable, the corresponding calendar event is created or updated in real time. Your Airtable schedule becomes a live calendar that the whole team can see and act on.",
    useCases: [
      {
        title: "Turn Airtable project deadlines into calendar events",
        description:
          "Every date field in your Airtable project tracker creates a Google Calendar event with the record name and a link back to Airtable. Deadlines are visible on everyone's calendar automatically.",
      },
      {
        title: "Content calendar sync to Google Calendar",
        description:
          "Publish dates from an Airtable content calendar appear as Google Calendar events for the content team. Writers and editors see their schedule in the calendar they live in.",
      },
      {
        title: "Event management scheduling",
        description:
          "Event records in Airtable — with venue, time, and organizer — generate detailed Google Calendar events with full descriptions. Event teams plan in Airtable and calendar invites are sent automatically.",
      },
      {
        title: "Deadline change propagation",
        description:
          "When a due date is pushed in Airtable, GAIA updates the Google Calendar event immediately. No one attends a meeting for a deadline that has already moved.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Airtable and Google Calendar to GAIA",
        description:
          "Authorize GAIA with your Airtable account and Google Calendar. GAIA identifies the date fields and tables you want to sync to calendar events.",
      },
      {
        step: "Map Airtable fields to calendar event properties",
        description:
          "Define which Airtable fields populate the event title, description, location, and attendees. GAIA uses your field mappings to create well-structured calendar events.",
      },
      {
        step: "GAIA automates date-to-event synchronization",
        description:
          "New and updated Airtable dates create or modify Google Calendar events in real time. Your calendar always reflects the latest schedule from Airtable.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync to specific Google Calendars, not just the primary?",
        answer:
          "Yes. During setup you choose which Google Calendar receives events from each Airtable table. Different tables can populate different calendars — a content calendar and a project calendar, for example.",
      },
      {
        question: "Does GAIA add Google Meet links to calendar events?",
        answer:
          "Yes. GAIA can optionally add a Google Meet link to each generated calendar event, making it easy to schedule virtual meetings directly from Airtable records.",
      },
      {
        question: "What happens if an Airtable record is deleted?",
        answer:
          "When an Airtable record is deleted, GAIA removes the corresponding Google Calendar event. Your calendar stays clean and only reflects active Airtable records.",
      },
    ],
  },
};
