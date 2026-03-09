import type { IntegrationCombo } from "./combosData";

export const combosBatchD: Record<string, IntegrationCombo> = {
  "todoist-jira": {
    slug: "todoist-jira",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Sync personal Todoist tasks with Jira tickets without leaving your flow",
    metaTitle:
      "Todoist + Jira Integration - Personal Tasks Meet Team Tickets | GAIA",
    metaDescription:
      "Connect Todoist and Jira with GAIA. Automatically create Jira issues from Todoist tasks, sync your assigned Jira tickets into Todoist, and keep your personal and team workflows aligned.",
    keywords: [
      "Todoist Jira integration",
      "Todoist Jira sync",
      "create Jira issue from Todoist",
      "sync Jira tickets to Todoist",
      "Todoist Jira automation",
      "personal tasks Jira workflow",
    ],
    intro:
      "Software teams track engineering work in Jira, but individual contributors often capture their own action items, research notes, and follow-ups in a personal task manager like Todoist. These two systems rarely talk to each other, creating a fragmented picture of what actually needs to get done. Engineers end up maintaining two lists, manually copying ticket references into Todoist and hoping they stay in sync.\n\nGAIA eliminates this duplication by acting as a live bridge between Todoist and Jira. When you're assigned a new Jira ticket, GAIA can add it to your Todoist inbox with the ticket number, priority, and due date pre-filled. When you capture a task in Todoist that belongs in Jira, GAIA can escalate it to the appropriate project and link the two records together. Status updates flow in both directions so you always see a single source of truth.\n\nThis integration is particularly valuable for engineers who prefer Todoist's fast capture and GTD-style organization but need to stay accountable within a team Jira workflow, and for project leads who want a personal view of their Jira workload alongside non-engineering tasks.",
    useCases: [
      {
        title: "Mirror assigned Jira tickets into Todoist",
        description:
          "GAIA watches for new Jira tickets assigned to you and immediately creates a matching Todoist task with the ticket ID, summary, priority level, and a direct link back to Jira so you can triage from your personal inbox.",
      },
      {
        title: "Escalate Todoist tasks to Jira issues",
        description:
          "When a task captured in Todoist grows in scope or needs team visibility, tell GAIA to promote it to a Jira issue. GAIA creates the ticket in the right project, sets the reporter, and updates the Todoist task with the Jira link.",
      },
      {
        title: "Sync Jira status changes back to Todoist",
        description:
          "When a Jira ticket moves to Done or is closed by a teammate, GAIA automatically marks the corresponding Todoist task complete so your personal list stays accurate without manual cleanup.",
      },
      {
        title: "Daily sprint task briefing",
        description:
          "Each morning GAIA compiles your active Jira sprint tickets and any related Todoist tasks into a single prioritized list, giving you a clear picture of what requires attention before your standup.",
      },
      {
        title: "Bug report task capture",
        description:
          "When you notice a bug while working and jot it down in Todoist, GAIA can instantly create a Jira bug ticket with the right issue type, component, and severity, keeping your development workflow uninterrupted.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Jira to GAIA",
        description:
          "Authenticate your Todoist account and Jira workspace in GAIA's integration settings. GAIA uses OAuth for Todoist and Jira's REST API with scoped permissions so only your assigned projects and tasks are accessible.",
      },
      {
        step: "Configure sync rules and project mappings",
        description:
          "Tell GAIA which Jira projects map to which Todoist projects, what priority thresholds trigger sync, and whether you want bidirectional or one-way mirroring. You can express these rules in plain language.",
      },
      {
        step: "GAIA keeps both systems in sync automatically",
        description:
          "From that point on, GAIA monitors both Todoist and Jira for changes and propagates updates in real time. You can also trigger manual syncs or ask GAIA to report on discrepancies between the two systems.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA sync all Jira tickets or only tickets assigned to me?",
        answer:
          "By default GAIA only syncs Jira tickets assigned to your account, keeping your Todoist inbox focused on your personal workload. You can expand the scope to include tickets you're watching or tickets in a specific sprint if needed.",
      },
      {
        question:
          "Can GAIA handle custom Jira fields when creating issues from Todoist?",
        answer:
          "Yes. You can map Todoist task labels and priority levels to custom Jira fields during setup. GAIA will populate those fields when escalating Todoist tasks to Jira issues, respecting your team's required fields and workflows.",
      },
      {
        question:
          "What happens if a Todoist task is edited after a Jira issue is created?",
        answer:
          "GAIA can propagate title and description edits from Todoist to the linked Jira issue and vice versa. You control which fields are kept in sync and which are treated as independent to avoid unintended overwrites.",
      },
    ],
  },

  "todoist-clickup": {
    slug: "todoist-clickup",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline:
      "Bridge personal Todoist task capture with ClickUp team project management",
    metaTitle:
      "Todoist + ClickUp Integration - Personal Tasks Meet Team Projects | GAIA",
    metaDescription:
      "Connect Todoist and ClickUp with GAIA. Sync your personal Todoist tasks into ClickUp spaces, create ClickUp tasks from Todoist captures, and keep individual and team workflows aligned.",
    keywords: [
      "Todoist ClickUp integration",
      "Todoist ClickUp sync",
      "ClickUp Todoist automation",
      "personal task manager ClickUp",
      "sync Todoist to ClickUp",
      "ClickUp Todoist workflow",
    ],
    intro:
      "ClickUp is a powerful team project management platform with rich hierarchy, custom fields, and reporting capabilities. Todoist is the personal task manager that individuals reach for when they need fast, frictionless capture. Many professionals who work inside ClickUp for team collaboration still rely on Todoist for their own GTD-style inbox, creating a persistent gap between personal intentions and team-visible commitments.\n\nGAIA bridges this gap by acting as an intelligent relay between Todoist and ClickUp. Personal action items captured in Todoist can be promoted to ClickUp tasks in the right list and with the right metadata when they need team visibility. ClickUp tasks assigned to you flow into Todoist so your personal review happens in one place. Status updates propagate in both directions so neither system falls behind.\n\nThis integration is ideal for individual contributors who want to use Todoist as their personal capture tool without abandoning the ClickUp workflows their team depends on, and for managers who track their own actions in Todoist but need those actions visible in ClickUp for accountability.",
    useCases: [
      {
        title: "Capture in Todoist, execute in ClickUp",
        description:
          "Use Todoist's fast-capture interface during meetings or on the go, then let GAIA automatically promote relevant tasks to ClickUp with the correct space, folder, list, and assignee pre-filled based on project context.",
      },
      {
        title: "Pull assigned ClickUp tasks into Todoist",
        description:
          "GAIA monitors ClickUp for tasks assigned to you and mirrors them into your Todoist inbox with due dates and priorities so your daily review can happen entirely within Todoist without switching to ClickUp.",
      },
      {
        title: "Sync task completion across both tools",
        description:
          "When you check off a task in Todoist, GAIA marks the linked ClickUp task complete and vice versa, ensuring your team's project views always reflect your actual progress without manual double-entry.",
      },
      {
        title: "Weekly workload overview",
        description:
          "Each week GAIA generates a combined view of your Todoist personal tasks and ClickUp assignments grouped by project, helping you spot overload and balance commitments before deadlines arrive.",
      },
      {
        title: "Meeting action item distribution",
        description:
          "After a meeting where actions are captured in Todoist, GAIA distributes the relevant items to the appropriate ClickUp lists for each team member, turning meeting notes into trackable team tasks automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and ClickUp to GAIA",
        description:
          "Authenticate both Todoist and ClickUp in GAIA's integration settings. GAIA uses OAuth for secure access and only requests permissions for the workspaces and projects you specify.",
      },
      {
        step: "Map projects and define promotion rules",
        description:
          "Define which Todoist projects correspond to ClickUp spaces and lists. Set rules for when GAIA should automatically promote a Todoist task to ClickUp — for example, tasks tagged with a specific label or assigned a certain priority.",
      },
      {
        step: "GAIA syncs tasks in both directions continuously",
        description:
          "GAIA monitors both platforms for new tasks, assignments, and status changes, propagating updates automatically so your personal and team views always reflect the same reality.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA support ClickUp's custom task statuses?",
        answer:
          "Yes. During setup you can map Todoist's completion states to any custom status in your ClickUp workspace. This means tasks can progress through your team's specific workflow stages as they move between tools.",
      },
      {
        question: "Can I sync only specific Todoist projects to ClickUp?",
        answer:
          "Absolutely. You choose exactly which Todoist projects participate in the sync. Personal projects like shopping lists or private goals stay in Todoist only, while work projects are bridged to the relevant ClickUp spaces.",
      },
      {
        question:
          "Will GAIA create duplicate tasks if both tools update at the same time?",
        answer:
          "GAIA uses unique link identifiers to track the relationship between paired tasks. It applies last-write-wins logic with a short debounce window to resolve simultaneous edits, and alerts you when a conflict cannot be resolved automatically.",
      },
    ],
  },

  "todoist-trello": {
    slug: "todoist-trello",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Sync personal Todoist tasks to team Trello boards without manual copying",
    metaTitle:
      "Todoist + Trello Integration - From Personal Inbox to Team Board | GAIA",
    metaDescription:
      "Connect Todoist and Trello with GAIA. Automatically create Trello cards from Todoist tasks, sync card updates back to Todoist, and keep your personal and team Kanban views in step.",
    keywords: [
      "Todoist Trello integration",
      "Todoist Trello sync",
      "create Trello card from Todoist",
      "sync Todoist to Trello",
      "Todoist Trello automation",
      "personal task Trello board",
    ],
    intro:
      "Trello's visual Kanban boards are a team staple for tracking shared work, but many individuals prefer Todoist's list-based interface for their own task management. The problem is that work captured privately in Todoist rarely makes it onto the team Trello board in a timely way, creating gaps between what you've committed to and what your team can see.\n\nGAIA connects the two so that tasks flow between them automatically. When a Todoist task is ready to share with the team, GAIA can create a Trello card in the right board and list, complete with description, due date, and labels. When a Trello card is assigned to you, GAIA can pull it into your Todoist inbox for personal tracking. Completions and archive actions propagate both ways so neither board falls out of date.\n\nThis integration suits small teams who use Trello as their shared project view but allow individuals to use their preferred personal tools, and freelancers who manage their own work in Todoist but share progress with clients on a Trello board.",
    useCases: [
      {
        title: "Publish Todoist tasks as Trello cards",
        description:
          "When a task in Todoist is ready for team visibility, GAIA creates a corresponding Trello card on the designated board and list, carrying across the title, description, due date, and any relevant labels.",
      },
      {
        title: "Pull assigned Trello cards into Todoist",
        description:
          "GAIA watches for Trello cards assigned to you and adds them to your Todoist inbox with due dates and priority so your daily review stays centralized in your preferred tool.",
      },
      {
        title: "Keep completion status synchronized",
        description:
          "Checking off a Todoist task archives the linked Trello card, and moving a Trello card to Done marks the Todoist task complete, so both views stay accurate without manual housekeeping.",
      },
      {
        title: "Client project board updates",
        description:
          "Freelancers can capture work in Todoist during the day and let GAIA push completed items to a client-facing Trello board each evening, giving clients visibility without requiring a change in personal workflow.",
      },
      {
        title: "Meeting action items to Trello",
        description:
          "Action items captured in Todoist during a meeting are automatically distributed to the right Trello boards and assigned to the right team members, turning meeting notes into trackable Kanban cards.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Trello to GAIA",
        description:
          "Authenticate Todoist and Trello in GAIA's integration settings using OAuth. GAIA only requests access to the boards and projects you specify, keeping unrelated data private.",
      },
      {
        step: "Map Todoist projects to Trello boards and lists",
        description:
          "Tell GAIA which Todoist projects should sync to which Trello boards, and which Trello list newly promoted tasks should land in. You can define different mappings for different teams or clients.",
      },
      {
        step: "GAIA handles card creation and status sync automatically",
        description:
          "GAIA monitors both platforms continuously, creating and updating cards and tasks as changes occur. You can also trigger one-off syncs or ask GAIA to report on items that exist in one tool but not the other.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync Trello checklist items to Todoist sub-tasks?",
        answer:
          "Yes. GAIA can map Trello checklist items to Todoist sub-tasks when creating linked records. Changes to checklist completion status in Trello propagate to the corresponding Todoist sub-tasks and vice versa.",
      },
      {
        question: "What happens to attachments on Trello cards?",
        answer:
          "GAIA includes links to Trello card attachments in the corresponding Todoist task description. Uploading files directly to Todoist tasks and pushing them to Trello as attachments is also supported for common file types.",
      },
      {
        question:
          "Can I share a Trello board with a client without giving them access to my Todoist?",
        answer:
          "Yes. GAIA acts as the bridge between your private Todoist and the shared Trello board. Clients only see the Trello board you've shared with them; your Todoist remains entirely private.",
      },
    ],
  },

  "todoist-linear": {
    slug: "todoist-linear",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline:
      "Keep personal Todoist tasks and Linear engineering issues in perfect sync",
    metaTitle:
      "Todoist + Linear Integration - Personal Tasks and Engineering Issues Unified | GAIA",
    metaDescription:
      "Connect Todoist and Linear with GAIA. Sync assigned Linear issues into your Todoist inbox, escalate Todoist tasks to Linear, and maintain a single view of your engineering and personal workload.",
    keywords: [
      "Todoist Linear integration",
      "Todoist Linear sync",
      "Linear issues Todoist",
      "sync Linear to Todoist",
      "Todoist Linear automation",
      "engineering tasks personal inbox",
    ],
    intro:
      "Linear has become the go-to issue tracker for high-velocity engineering teams, valued for its speed and clean opinionated workflow. Todoist remains the personal task manager of choice for many engineers who want a fast, distraction-free space for their own action items outside the team's shared context. Maintaining both tools separately means duplicated effort: manually copying Linear issues into Todoist, updating statuses in two places, and losing the big picture of your actual workload.\n\nGAIA connects Todoist and Linear so the two stay synchronized automatically. New Linear issues assigned to you appear in your Todoist inbox with cycle deadlines and priority pre-filled. Tasks you capture in Todoist that belong in a Linear project can be promoted with a single command. Completion events flow in both directions so your team's cycle board and your personal list always agree.\n\nThis is particularly useful for engineers who rely on Todoist's fast-capture during planning sessions but need their personal work visible in Linear for sprint accountability, and for tech leads who track their own action items in Todoist alongside engineering issues they own.",
    useCases: [
      {
        title: "Mirror assigned Linear issues into Todoist",
        description:
          "GAIA pulls every Linear issue assigned to you into your Todoist inbox, including the team, priority, cycle end date, and a direct link, so your daily review requires only one tool.",
      },
      {
        title: "Escalate Todoist tasks to Linear issues",
        description:
          "When a personal task grows into engineering work, GAIA creates a Linear issue in the right team and project, copies the description, sets the priority, and links the two records so nothing is lost in translation.",
      },
      {
        title: "Cycle deadline reminders via Todoist",
        description:
          "GAIA adds due dates to your synced Linear issues in Todoist based on the current cycle end date, giving you deadline visibility inside your personal task manager so sprint planning stays on track.",
      },
      {
        title: "Status propagation across both systems",
        description:
          "When you mark a Todoist task done, GAIA moves the linked Linear issue to the completed state. When a teammate closes a Linear issue, GAIA checks off the corresponding Todoist task so your personal list never shows stale items.",
      },
      {
        title: "Planning session capture",
        description:
          "During sprint planning, capture all personal commitments in Todoist at speed, then let GAIA batch-promote them to the correct Linear cycle and team, converting your planning notes into trackable engineering issues automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Linear to GAIA",
        description:
          "Authorize Todoist and Linear in GAIA's integration settings. GAIA uses Linear's GraphQL API and Todoist's REST API with OAuth to access only the teams and projects you specify.",
      },
      {
        step: "Set up team mappings and sync preferences",
        description:
          "Map Linear teams to Todoist projects, define which issue states trigger sync, and set your preferred priority translation between Linear's 0–4 scale and Todoist's priority levels.",
      },
      {
        step: "GAIA maintains real-time sync between both tools",
        description:
          "GAIA listens for webhooks from both Linear and Todoist to propagate changes in near real-time. Daily digest summaries are also available to surface any sync discrepancies.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA support Linear's cycle concept when syncing to Todoist?",
        answer:
          "Yes. GAIA maps the active cycle's end date to the Todoist task due date, and can include cycle labels so you can see at a glance which Todoist tasks belong to your current sprint.",
      },
      {
        question: "Can GAIA sync Linear sub-issues to Todoist sub-tasks?",
        answer:
          "Yes. Linear sub-issues are mirrored as Todoist sub-tasks under the parent task. Completion of all sub-tasks in Todoist can optionally trigger a status update on the parent Linear issue.",
      },
      {
        question:
          "What happens to Linear issues that are reassigned to someone else?",
        answer:
          "If a Linear issue is reassigned away from you, GAIA removes or archives the corresponding Todoist task depending on your preference, keeping your personal list focused on work that is genuinely yours.",
      },
    ],
  },

  "todoist-github": {
    slug: "todoist-github",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline:
      "Turn GitHub issues assigned to you into Todoist tasks automatically",
    metaTitle:
      "Todoist + GitHub Integration - Code Issues in Your Personal Task Manager | GAIA",
    metaDescription:
      "Connect Todoist and GitHub with GAIA. Sync GitHub issues and pull request reviews assigned to you into Todoist, create GitHub issues from Todoist tasks, and manage your dev workload in one place.",
    keywords: [
      "Todoist GitHub integration",
      "GitHub issues Todoist",
      "sync GitHub to Todoist",
      "Todoist GitHub automation",
      "GitHub pull request Todoist",
      "developer task manager GitHub",
    ],
    intro:
      "GitHub is where software development happens: issues are filed, pull requests are reviewed, and bugs are tracked. Todoist is where many developers manage everything else — personal projects, meeting actions, and daily to-dos. The problem is that GitHub notifications are overwhelming and GitHub's own task tracking is built for collaboration, not personal GTD-style organization. Important issues and PR reviews get buried in notification noise.\n\nGAIA bridges Todoist and GitHub so your development obligations surface cleanly in your personal task manager. When a GitHub issue is assigned to you or a PR is ready for your review, GAIA creates a Todoist task with the repository name, issue number, and a direct link. When you resolve a task in Todoist, GAIA can close or comment on the linked GitHub issue. You can also capture a task in Todoist and have GAIA create a corresponding GitHub issue for visibility on the team's board.\n\nThis integration is built for developers who want GitHub accountability without living in GitHub's notification UI, and for open-source contributors who manage multiple repositories and need a consolidated personal view of their obligations.",
    useCases: [
      {
        title: "Auto-create Todoist tasks from GitHub issue assignments",
        description:
          "Whenever a GitHub issue is assigned to you, GAIA instantly creates a Todoist task with the issue title, repository, number, priority label, and a direct link so you can triage from your personal inbox.",
      },
      {
        title: "PR review reminders in Todoist",
        description:
          "GAIA adds a Todoist task every time you're requested as a reviewer on a pull request, including the PR title, author, and repository, so code reviews appear in your daily task list alongside other work.",
      },
      {
        title: "Create GitHub issues from Todoist tasks",
        description:
          "When a Todoist task belongs in a GitHub repository for team visibility, ask GAIA to escalate it. GAIA creates the GitHub issue in the right repo, copies the description, and links the two records together.",
      },
      {
        title: "Close GitHub issues when Todoist tasks are completed",
        description:
          "Checking off a Todoist task that is linked to a GitHub issue triggers GAIA to close the issue with an automated comment, keeping your GitHub issue board clean without requiring a context switch.",
      },
      {
        title: "Multi-repository consolidated inbox",
        description:
          "For contributors to multiple repos, GAIA aggregates all GitHub assignments and review requests across every repository into a single prioritized Todoist project, eliminating the need to check each repo individually.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and GitHub to GAIA",
        description:
          "Authorize Todoist and your GitHub account in GAIA's integration settings. GAIA uses GitHub's OAuth app flow and only requests the repository scopes you specify, keeping private repos private.",
      },
      {
        step: "Choose which repositories and event types to sync",
        description:
          "Select the GitHub repositories GAIA should monitor and the event types that trigger Todoist task creation — issue assignments, PR review requests, mentions, or all of the above.",
      },
      {
        step: "GAIA creates and manages tasks automatically",
        description:
          "GAIA listens to GitHub webhooks for your chosen events and creates, updates, or completes Todoist tasks in real time. You can review a daily summary of all GitHub-originated tasks from within GAIA's chat interface.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync GitHub milestones as Todoist due dates?",
        answer:
          "Yes. When GAIA creates a Todoist task from a GitHub issue, it uses the issue's milestone due date as the Todoist task due date if one is set, giving you deadline visibility without manually checking GitHub milestones.",
      },
      {
        question: "Does GAIA support GitHub Projects in addition to issues?",
        answer:
          "GAIA primarily syncs issues and pull requests. GitHub Projects integration is on the roadmap. In the meantime, issues linked to GitHub Projects are synced normally via their issue record.",
      },
      {
        question:
          "How does GAIA handle issues that are unassigned or reassigned?",
        answer:
          "If a GitHub issue is unassigned from you, GAIA archives or removes the corresponding Todoist task based on your preference. Reassignment to another person follows the same rule, keeping your Todoist focused on active responsibilities.",
      },
    ],
  },

  "todoist-slack": {
    slug: "todoist-slack",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline:
      "Create Todoist tasks from Slack messages and share completions back to your team",
    metaTitle:
      "Todoist + Slack Integration - Tasks from Messages, Updates to Channels | GAIA",
    metaDescription:
      "Connect Todoist and Slack with GAIA. Turn Slack messages into Todoist tasks instantly, receive task reminders in Slack, and share completed work back to your team's channels automatically.",
    keywords: [
      "Todoist Slack integration",
      "Slack to Todoist task",
      "create task from Slack message",
      "Todoist Slack automation",
      "Slack task reminder Todoist",
      "Todoist Slack workflow",
    ],
    intro:
      "Slack is where your team communicates, but conversations move fast and action items get buried in channel history within minutes. Todoist is where you capture and organize the things you actually need to do. The gap between the two is where commitments get lost: someone asks you to handle something in Slack, you mean to add it to Todoist, and three days later it surfaces again as an embarrassing follow-up.\n\nGAIA closes this gap by making it effortless to turn Slack messages into Todoist tasks without leaving Slack. A single command or emoji reaction triggers GAIA to capture the message content as a Todoist task with the sender, channel, and timestamp for context. You can set due dates and priorities in the same command. When tasks are completed, GAIA can post a brief update to the original Slack channel so your team knows the work is done without a manual status message.\n\nThis combination is essential for anyone who manages commitments made in Slack, from individual contributors tracking action items from standup threads to managers who need to capture decisions from executive channels and follow through reliably.",
    canonicalSlug: "slack-todoist",
    useCases: [
      {
        title: "Convert Slack messages to Todoist tasks instantly",
        description:
          "React to any Slack message with the GAIA emoji or type a quick command to capture it as a Todoist task. GAIA preserves the message text, sender, channel, and a permalink so you always know where the task originated.",
      },
      {
        title: "Receive task deadline reminders in Slack",
        description:
          "GAIA posts a Slack DM when a Todoist task is approaching its due date, keeping you accountable for commitments even when you're not actively checking Todoist throughout the day.",
      },
      {
        title: "Share task completions to team channels",
        description:
          "When you complete a Todoist task that originated from a Slack message, GAIA can post a brief completion notice back to the original channel or thread so the requester knows it's done without a follow-up ping.",
      },
      {
        title: "Daily task summary to Slack",
        description:
          "Each morning GAIA posts a personalized summary of your Todoist tasks due today directly to your Slack DM, giving you a heads-up on the day's obligations before the channel noise begins.",
      },
      {
        title: "Capture standup action items from Slack",
        description:
          "During your team's Slack-based standup, GAIA monitors the standup channel and automatically creates Todoist tasks for any blockers or action items you call out, turning the async standup into a structured to-do list.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Slack to GAIA",
        description:
          "Install the GAIA app in your Slack workspace and authenticate your Todoist account. GAIA requests only the Slack scopes needed to read messages you explicitly trigger and post to the channels you authorize.",
      },
      {
        step: "Define capture triggers and notification preferences",
        description:
          "Choose how you want to trigger task creation — emoji reaction, slash command, or keyword mention — and set which Todoist project new Slack-sourced tasks should land in. Configure which task completions should post back to Slack.",
      },
      {
        step: "GAIA captures and closes the loop automatically",
        description:
          "GAIA handles task creation, reminder delivery, and completion notifications so the Slack-to-Todoist loop is fully automated. You stay in Slack for communication and Todoist for execution without manual bridging.",
      },
    ],
    faqs: [
      {
        question:
          "Can I create a Todoist task from a Slack message without leaving Slack?",
        answer:
          "Yes. You can use a Slack shortcut, emoji reaction, or slash command directly within Slack to trigger GAIA. GAIA will confirm the task was created with a brief ephemeral message visible only to you.",
      },
      {
        question:
          "Which Todoist project do Slack-captured tasks go to by default?",
        answer:
          "You can set a default Todoist project for Slack captures during setup. You can also override the destination project per capture using a quick inline command, for example specifying a project name in your trigger message.",
      },
      {
        question:
          "Can GAIA post to a specific Slack channel when a task is completed?",
        answer:
          "Yes. You can configure completion notifications to post to the channel where the original message was captured, to a specific team channel, or only to your Slack DM if you prefer a quieter workflow.",
      },
    ],
  },

  "todoist-drive": {
    slug: "todoist-drive",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach Drive files to Todoist tasks and create tasks from Drive activity automatically",
    metaTitle:
      "Todoist + Google Drive Integration - Tasks Linked to Docs and Files | GAIA",
    metaDescription:
      "Connect Todoist and Google Drive with GAIA. Attach Drive documents to Todoist tasks, create tasks when Drive files need review, and keep your document-related work organized in your personal task manager.",
    keywords: [
      "Todoist Google Drive integration",
      "Todoist Drive automation",
      "attach Drive file to Todoist task",
      "Google Drive task creation",
      "Todoist Drive sync",
      "document task management Todoist",
    ],
    intro:
      "Google Drive holds your documents, spreadsheets, and presentations, but knowing which files need attention and by when is a constant challenge. Todoist holds your tasks, but tasks without document context require you to hunt down the right file every time you sit down to work. The result is wasted time re-locating files and a disconnect between what you need to do and the materials you need to do it with.\n\nGAIA bridges Todoist and Google Drive so file-related work stays connected to your task list. When a Google Doc is shared with you for review, GAIA can create a Todoist task with a direct link to the document and a suggested due date. When you create a Todoist task that references a file, GAIA can search Drive and attach the relevant document automatically. You can also ask GAIA to create a new Drive document and link it to an existing task in one command.\n\nThis integration is invaluable for knowledge workers who frequently review, edit, or produce documents as part of their workflow, and for anyone who wants their task list to serve as the single entry point for all work, including document-centric tasks.",
    useCases: [
      {
        title: "Create Todoist tasks when Drive files are shared with you",
        description:
          "When a Google Doc, Sheet, or Slide is shared with you in Drive, GAIA automatically creates a Todoist task with the document title, sharer's name, and a direct link so review items always surface in your task inbox.",
      },
      {
        title: "Attach Drive files to existing Todoist tasks",
        description:
          "Tell GAIA to find and attach a Drive document to a Todoist task by name or keyword. GAIA searches your Drive, confirms the match, and appends the link to the task description so the file is always one click away.",
      },
      {
        title: "Create Drive docs from Todoist tasks",
        description:
          "When a Todoist task involves creating a new document, GAIA can generate a blank Google Doc or from a template in the appropriate Drive folder and link it back to the Todoist task, giving you a head start without leaving your task manager.",
      },
      {
        title: "Review deadline reminders for shared documents",
        description:
          "If a shared Drive document includes a comment asking for feedback by a specific date, GAIA extracts that deadline and sets the due date on the linked Todoist task so you never miss a document review request.",
      },
      {
        title: "Archive Drive-linked tasks on document completion",
        description:
          "When you mark a Todoist task done that is linked to a Drive document, GAIA can move the document to an archive folder in Drive, keeping your working Drive clean and aligned with your task completion status.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Google Drive to GAIA",
        description:
          "Authorize Todoist and Google Drive in GAIA's integration settings via OAuth. GAIA only accesses files shared with you or in folders you explicitly grant access to.",
      },
      {
        step: "Set up Drive activity triggers and attachment preferences",
        description:
          "Tell GAIA which Drive events should create Todoist tasks — new shares, comments requesting review, or file edits — and which Todoist project those tasks should land in.",
      },
      {
        step: "GAIA creates tasks, attaches files, and keeps both in sync",
        description:
          "GAIA monitors Drive activity and Todoist task changes, creating tasks from Drive events and attaching Drive links to tasks on demand. You can also ask GAIA to audit which tasks are missing document links.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA search all of my Google Drive or only specific folders?",
        answer:
          "You can grant GAIA access to your full Drive or restrict it to specific folders during setup. Restricting to work folders is recommended to keep personal Drive content out of the integration.",
      },
      {
        question: "Does GAIA support Shared Drives in addition to My Drive?",
        answer:
          "Yes. GAIA can monitor Shared Drives that you have access to, creating Todoist tasks from file shares and comment requests within those shared workspaces.",
      },
      {
        question: "What types of Drive files trigger task creation?",
        answer:
          "By default GAIA creates tasks for Google Docs, Sheets, Slides, and PDFs shared with you. You can expand or restrict this to specific file types and MIME types in your integration settings.",
      },
    ],
  },

  "todoist-discord": {
    slug: "todoist-discord",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline:
      "Share task progress in Discord and create Todoist tasks from Discord messages",
    metaTitle:
      "Todoist + Discord Integration - Task Management for Discord Communities | GAIA",
    metaDescription:
      "Connect Todoist and Discord with GAIA. Create Todoist tasks from Discord messages, share task completions to Discord channels, and keep community or team action items organized in your personal task manager.",
    keywords: [
      "Todoist Discord integration",
      "Discord to Todoist task",
      "create task from Discord message",
      "Todoist Discord automation",
      "Discord task management",
      "Todoist Discord workflow",
    ],
    intro:
      "Discord has evolved far beyond gaming into a platform where dev communities, open-source projects, and distributed teams coordinate daily. Action items, decisions, and commitments regularly surface in Discord conversations, but they're ephemeral — buried by the next message within minutes. Todoist is where those action items need to land, but manually copying from Discord to Todoist is friction that rarely happens consistently.\n\nGAIA connects the two so that capturing a Discord message as a Todoist task takes a single command or reaction. Whether you're in a project planning channel, a support server, or a team voice chat follow-up thread, GAIA can extract the relevant content, create a structured Todoist task, and confirm the capture without disrupting the conversation. Completed tasks can be posted back to the Discord channel as a brief update so community members or teammates know what's been resolved.\n\nThis integration is especially useful for open-source maintainers tracking community issues from Discord, community managers juggling action items across multiple servers, and remote teams who use Discord as their primary communication platform.",
    useCases: [
      {
        title: "Capture Discord messages as Todoist tasks",
        description:
          "React to any Discord message or use a slash command to tell GAIA to capture it as a Todoist task. GAIA saves the message content, author, channel, and a link so you always know the origin of the task.",
      },
      {
        title: "Post task completion updates to Discord channels",
        description:
          "When you complete a Todoist task that originated from a Discord message, GAIA can post a brief update to the original channel or thread so community members or teammates are automatically informed.",
      },
      {
        title: "Daily task digest posted to Discord",
        description:
          "GAIA posts a morning summary of your Todoist tasks due today to a private Discord channel or DM, giving you a structured start-of-day overview in the tool you're already monitoring.",
      },
      {
        title: "Community issue tracking",
        description:
          "For open-source maintainers, GAIA monitors designated Discord support channels for common issue patterns and creates Todoist tasks for recurring problems, helping you prioritize community-reported issues for your development backlog.",
      },
      {
        title: "Standup action items from Discord voice or text",
        description:
          "After a team standup in Discord, paste the summary or let GAIA listen to the follow-up text channel and automatically generate Todoist tasks for each action item called out, assigning due dates based on the discussion.",
      },
    ],
    howItWorks: [
      {
        step: "Add GAIA to your Discord server and connect Todoist",
        description:
          "Invite the GAIA bot to your Discord server and authorize your Todoist account in GAIA's integration settings. You choose which channels GAIA can read and respond in.",
      },
      {
        step: "Set up capture commands and notification channels",
        description:
          "Configure how task capture is triggered in Discord — slash command, bot mention, or emoji reaction — and which Todoist project captures land in. Set which Todoist task events should post back to Discord and to which channel.",
      },
      {
        step: "GAIA bridges Discord conversations and Todoist tasks",
        description:
          "GAIA listens in the channels you've authorized, creates tasks on demand, and posts completion updates automatically. You can also query GAIA from Discord to check on task status or add sub-tasks.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA monitor Discord channels automatically or only on command?",
        answer:
          "Both modes are available. GAIA can be configured to automatically create tasks from messages matching certain keywords or patterns in specific channels, or to only act when explicitly triggered by a command or emoji reaction.",
      },
      {
        question: "Which Discord server roles can trigger GAIA task creation?",
        answer:
          "You can restrict GAIA task creation to specific Discord roles during setup. This prevents unintended task creation from general community members while allowing moderators or team members to use the integration freely.",
      },
      {
        question:
          "Does GAIA support multiple Discord servers connected to one Todoist account?",
        answer:
          "Yes. GAIA can connect multiple Discord servers to a single Todoist account, with separate Todoist project mappings per server so tasks from different communities or teams stay organized.",
      },
    ],
  },

  "todoist-hubspot": {
    slug: "todoist-hubspot",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Create Todoist follow-up tasks from HubSpot CRM activities and sync deal tasks automatically",
    metaTitle:
      "Todoist + HubSpot Integration - CRM Activities Into Personal Tasks | GAIA",
    metaDescription:
      "Connect Todoist and HubSpot with GAIA. Automatically create Todoist follow-up tasks from HubSpot deal stages and contact activities, and push completed tasks back to HubSpot as logged activities.",
    keywords: [
      "Todoist HubSpot integration",
      "HubSpot Todoist automation",
      "CRM tasks Todoist",
      "HubSpot follow-up tasks",
      "Todoist HubSpot sync",
      "sales task management Todoist",
    ],
    intro:
      "HubSpot tracks every deal, contact interaction, and pipeline stage, but turning those CRM events into personal action items requires constant manual translation. Sales reps and account managers often rely on a personal task manager like Todoist to stay on top of their follow-ups, but keeping Todoist in sync with what's happening in HubSpot is a full-time job in itself.\n\nGAIA automates this translation layer. When a deal moves to a new stage in HubSpot that requires a follow-up, GAIA creates a Todoist task with the deal name, company, stage, and due date pre-filled. When a contact opens a proposal or a meeting is logged, GAIA can trigger a follow-up task in Todoist automatically. Completed Todoist tasks are logged back to HubSpot as activities so your CRM stays accurate without double entry.\n\nThis integration is built for sales reps, account executives, and customer success managers who want to use Todoist for their personal workflow discipline while keeping HubSpot as the authoritative system of record for all customer interactions.",
    useCases: [
      {
        title: "Create follow-up tasks from deal stage changes",
        description:
          "When a HubSpot deal advances to a new pipeline stage, GAIA creates a Todoist follow-up task with the deal name, contact, company, and a suggested follow-up due date so no deal progresses without a next action.",
      },
      {
        title: "Task creation from contact activity",
        description:
          "When a HubSpot contact opens an email, visits a key page, or submits a form, GAIA creates a timely Todoist follow-up task so you can strike while engagement is highest without manually monitoring HubSpot activity feeds.",
      },
      {
        title: "Log completed Todoist tasks back to HubSpot",
        description:
          "When you complete a Todoist task linked to a HubSpot deal or contact, GAIA logs the activity back to HubSpot with a timestamp and note, keeping your CRM records accurate without requiring you to open HubSpot.",
      },
      {
        title: "Meeting prep task generation",
        description:
          "The day before a scheduled HubSpot meeting, GAIA creates a Todoist preparation task with the contact name, company, deal stage, and recent activity summary so you're always ready without last-minute scrambling.",
      },
      {
        title: "Overdue deal follow-up alerts",
        description:
          "GAIA monitors HubSpot for deals that haven't had activity in a defined period and creates urgent Todoist tasks for the responsible rep, ensuring stalled deals get proactive attention before they go cold.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and HubSpot to GAIA",
        description:
          "Authorize Todoist and your HubSpot portal in GAIA's integration settings. GAIA uses HubSpot's private app tokens and Todoist's OAuth to access only the pipelines, deals, and contacts you specify.",
      },
      {
        step: "Define HubSpot triggers and task templates",
        description:
          "Choose which HubSpot events create Todoist tasks — deal stage changes, email opens, meeting completions, or form submissions — and define the task template including due date rules and Todoist project destination.",
      },
      {
        step: "GAIA automates the CRM-to-task and task-to-CRM loop",
        description:
          "GAIA monitors HubSpot in real time for trigger events and creates Todoist tasks automatically. When those tasks are completed, GAIA logs the activity back to HubSpot so both systems stay current.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA work with custom HubSpot pipelines and deal stages?",
        answer:
          "Yes. During setup GAIA reads your HubSpot portal's custom pipelines and deal stages so you can configure triggers and task templates for any stage in any pipeline, not just the default ones.",
      },
      {
        question:
          "Does GAIA support HubSpot contacts and companies in addition to deals?",
        answer:
          "Yes. GAIA can create Todoist tasks from contact activity events such as email opens, form submissions, and lifecycle stage changes, in addition to deal-based triggers.",
      },
      {
        question: "How does GAIA log completed tasks back to HubSpot?",
        answer:
          "GAIA creates a HubSpot activity note associated with the relevant deal or contact when a linked Todoist task is marked complete. The note includes the task title, completion timestamp, and any notes you added to the Todoist task.",
      },
    ],
  },

  "google-calendar-jira": {
    slug: "google-calendar-jira",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Schedule sprint ceremonies from Jira milestones and add events from Jira directly to your calendar",
    metaTitle:
      "Google Calendar + Jira Integration - Jira Milestones on Your Calendar | GAIA",
    metaDescription:
      "Connect Google Calendar and Jira with GAIA. Automatically schedule sprint events from Jira, add milestone due dates to your calendar, and ensure your engineering schedule reflects your Jira project timeline.",
    keywords: [
      "Google Calendar Jira integration",
      "Jira Google Calendar sync",
      "Jira sprint calendar",
      "Jira milestone calendar event",
      "Google Calendar Jira automation",
      "engineering schedule Jira calendar",
    ],
    intro:
      "Jira holds your team's sprint plans, milestones, and release dates, but those dates rarely appear automatically in the calendar tool your entire organization uses to schedule meetings and block time. Engineers and project managers end up manually creating calendar events for sprint ceremonies, release dates, and milestone reviews — work that is error-prone and quickly goes stale when Jira dates change.\n\nGAIA connects Google Calendar and Jira so your project timeline is always reflected in your calendar. Sprint start and end dates become calendar events automatically. Milestone due dates appear as all-day events with the right context. Release dates block time in the relevant engineers' calendars. When a sprint date changes in Jira, GAIA updates the corresponding calendar event so everyone stays aligned without manual re-entry.\n\nThis integration is essential for engineering teams who use Google Calendar as their primary scheduling tool and Jira as their project management source of truth, particularly where coordination with non-engineering stakeholders requires calendar visibility of development milestones.",
    useCases: [
      {
        title: "Auto-schedule sprint ceremonies from Jira",
        description:
          "GAIA reads your Jira sprint dates and automatically creates Google Calendar events for sprint planning, daily standups, sprint review, and retrospective on the correct days with the right attendees.",
      },
      {
        title: "Add Jira milestone due dates to Google Calendar",
        description:
          "When a Jira milestone or version release date is set, GAIA creates an all-day calendar event so the milestone is visible to everyone in the organization who relies on Google Calendar for scheduling.",
      },
      {
        title: "Update calendar events when Jira dates change",
        description:
          "If a sprint is extended or a milestone is rescheduled in Jira, GAIA automatically updates the corresponding Google Calendar events and notifies attendees so your calendar stays accurate without manual correction.",
      },
      {
        title: "Block focus time around release dates",
        description:
          "GAIA detects upcoming Jira release dates and blocks focus time in engineers' Google Calendars in the days before the release, protecting time for final testing and bug fixes without requiring a manual calendar update.",
      },
      {
        title: "Create Jira issues from calendar events",
        description:
          "When a planning meeting or design review is added to Google Calendar, GAIA can create a linked Jira epic or story to capture the deliverables discussed, connecting your scheduling tool to your project tracking system.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Jira to GAIA",
        description:
          "Authorize Google Calendar and your Jira workspace in GAIA's integration settings. GAIA uses OAuth for Calendar and Jira's REST API to access the projects and calendars you specify.",
      },
      {
        step: "Choose which Jira projects and event types to sync",
        description:
          "Select the Jira projects whose sprint dates and milestones should appear on Google Calendar. Configure which Google Calendar to use for each project and how far in advance events should be created.",
      },
      {
        step: "GAIA creates and maintains calendar events from Jira data",
        description:
          "GAIA monitors Jira for sprint and milestone date changes and keeps the corresponding Google Calendar events in sync automatically. You can also query GAIA to generate a calendar view of any Jira project's upcoming dates.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync Jira's two-week sprint cycle to repeating Google Calendar events?",
        answer:
          "Yes. GAIA can create recurring Google Calendar events that match your Jira sprint cadence. When a sprint's actual dates deviate from the recurrence, GAIA updates the specific instance without affecting the broader series.",
      },
      {
        question:
          "Does GAIA support Jira Software and Jira Service Management?",
        answer:
          "GAIA supports Jira Software's sprint and milestone syncing natively. Jira Service Management SLA-based calendar events are also supported, creating calendar reminders for key SLA milestones.",
      },
      {
        question:
          "Can I sync Jira dates to a shared team calendar instead of personal calendars?",
        answer:
          "Yes. You can configure GAIA to write Jira-sourced events to a shared Google Calendar that the whole team has access to, providing a single team calendar that always reflects the current Jira project timeline.",
      },
    ],
  },

  "google-calendar-clickup": {
    slug: "google-calendar-clickup",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline:
      "Sync ClickUp task deadlines to Google Calendar and create tasks from calendar events",
    metaTitle:
      "Google Calendar + ClickUp Integration - Deadlines on Your Calendar | GAIA",
    metaDescription:
      "Connect Google Calendar and ClickUp with GAIA. Automatically sync ClickUp task due dates to Google Calendar, create ClickUp tasks from calendar events, and keep your schedule and project management aligned.",
    keywords: [
      "Google Calendar ClickUp integration",
      "ClickUp Google Calendar sync",
      "ClickUp deadlines calendar",
      "Google Calendar ClickUp automation",
      "ClickUp task due date calendar",
      "ClickUp schedule Google Calendar",
    ],
    intro:
      "ClickUp is your team's project hub, packed with tasks, deadlines, and dependencies across multiple spaces and lists. Google Calendar is where you and your stakeholders manage time. The problem is that ClickUp task deadlines rarely make it onto anyone's calendar unless someone manually creates an event — which means important deadlines are invisible to anyone not actively checking ClickUp.\n\nGAIA bridges Google Calendar and ClickUp so deadlines are always calendar-visible. Task due dates from the ClickUp lists you care about appear automatically as Google Calendar events, giving you and your team a deadline view alongside your meetings and appointments. When a calendar event represents a deliverable, GAIA can create the corresponding ClickUp task so your project management stays in sync with your schedule.\n\nThis integration helps project managers who review schedules in Google Calendar but manage work in ClickUp, and individual contributors who want their ClickUp task deadlines surfaced in the calendar tool they already live in.",
    useCases: [
      {
        title: "Sync ClickUp task due dates to Google Calendar",
        description:
          "GAIA monitors ClickUp for tasks assigned to you and creates corresponding Google Calendar events at the due date, giving you a timeline view of upcoming deadlines alongside your meetings.",
      },
      {
        title: "Create ClickUp tasks from calendar events",
        description:
          "When you add a calendar event that represents a deliverable — a client presentation, a product demo, or a project kickoff — GAIA creates a linked ClickUp task in the appropriate space and list so the work gets tracked.",
      },
      {
        title: "Update calendar events when ClickUp deadlines shift",
        description:
          "If a ClickUp task's due date is changed, GAIA updates the corresponding Google Calendar event automatically so your calendar view always reflects the current project timeline without manual correction.",
      },
      {
        title: "Visualize ClickUp project milestones on a team calendar",
        description:
          "GAIA aggregates key ClickUp milestone tasks across your team's spaces and publishes them to a shared Google Calendar, giving non-ClickUp users a clear view of project delivery dates in the tool they already use.",
      },
      {
        title: "Time-block for ClickUp tasks",
        description:
          "GAIA can automatically create time-blocked Google Calendar slots for high-priority ClickUp tasks before their due date, protecting focus time in your calendar so deep work gets scheduled, not just listed.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and ClickUp to GAIA",
        description:
          "Authorize your Google Calendar and ClickUp workspace in GAIA's integration settings using OAuth. You select which ClickUp spaces, folders, and lists participate in the sync.",
      },
      {
        step: "Configure deadline sync and task creation rules",
        description:
          "Set which ClickUp task properties trigger calendar event creation — assignee, priority, list membership, or custom field values. Define which Google Calendar receives ClickUp-sourced events.",
      },
      {
        step: "GAIA maintains the deadline-to-calendar pipeline automatically",
        description:
          "GAIA watches ClickUp for new and updated tasks and keeps Google Calendar in sync. When calendar events are created manually that match ClickUp task templates, GAIA can create the corresponding ClickUp tasks too.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync ClickUp start dates as well as due dates to Google Calendar?",
        answer:
          "Yes. GAIA can create multi-day Google Calendar events that span from the ClickUp task's start date to its due date, giving you a visual duration view of each task in your calendar.",
      },
      {
        question:
          "Does GAIA support ClickUp's recurring tasks when syncing to Google Calendar?",
        answer:
          "Yes. GAIA maps ClickUp recurring task schedules to Google Calendar recurring events. When the recurrence pattern changes in ClickUp, GAIA updates the calendar recurrence rule accordingly.",
      },
      {
        question:
          "Can GAIA sync tasks from multiple ClickUp workspaces to one Google Calendar?",
        answer:
          "Yes. GAIA supports multiple ClickUp workspaces and can route events from different workspaces to separate Google Calendars or consolidate them into one, depending on your preference.",
      },
    ],
  },

  "google-calendar-trello": {
    slug: "google-calendar-trello",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Add Trello card due dates to Google Calendar and create cards from calendar events",
    metaTitle:
      "Google Calendar + Trello Integration - Trello Deadlines on Your Calendar | GAIA",
    metaDescription:
      "Connect Google Calendar and Trello with GAIA. Automatically create Google Calendar events from Trello card due dates, generate Trello cards from calendar events, and keep your board and schedule in sync.",
    keywords: [
      "Google Calendar Trello integration",
      "Trello Google Calendar sync",
      "Trello due dates calendar",
      "Google Calendar Trello automation",
      "Trello card deadline calendar",
      "Trello schedule Google Calendar",
    ],
    intro:
      "Trello boards give your team a visual overview of project work, but the due dates on Trello cards are only visible to people actively looking at the board. Google Calendar is where everyone — including stakeholders who never log into Trello — checks schedules and deadlines. The disconnect means that delivery dates set in Trello are invisible in the place where people make time commitments.\n\nGAIA connects Google Calendar and Trello so Trello card due dates appear as calendar events automatically. When a card's due date is set or changed, the calendar event updates in real time. When a meeting or event in Google Calendar represents a deliverable, GAIA can create the corresponding Trello card in the right board and list so the work gets tracked. Both tools stay synchronized without any manual duplication.\n\nThis is particularly valuable for small teams that use Trello for project tracking and Google Calendar for scheduling and client-facing commitments, and for project managers who need to give non-Trello stakeholders visibility into delivery timelines.",
    useCases: [
      {
        title: "Create calendar events from Trello card due dates",
        description:
          "GAIA monitors the Trello boards you care about and creates Google Calendar events for card due dates, giving you and your team a deadline view in the calendar alongside meetings and other commitments.",
      },
      {
        title: "Generate Trello cards from calendar events",
        description:
          "When you create a calendar event for a client presentation or project review, GAIA can create a Trello card in the relevant board so the deliverable is tracked and assigned in your team's workflow tool.",
      },
      {
        title: "Keep calendar events updated when Trello due dates change",
        description:
          "If a card's due date is moved in Trello, GAIA updates the Google Calendar event immediately so your schedule view always reflects the latest project timeline without anyone needing to update the calendar manually.",
      },
      {
        title: "Stakeholder deadline calendar",
        description:
          "GAIA can publish key Trello card due dates to a shared Google Calendar that stakeholders who don't have Trello access can subscribe to, giving them delivery date visibility in a tool they already use.",
      },
      {
        title: "Overdue card alerts via calendar",
        description:
          "When a Trello card passes its due date without being completed, GAIA creates a Google Calendar alert for the card owner so the overdue item appears prominently in their schedule view and gets addressed.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Trello to GAIA",
        description:
          "Authorize Google Calendar and Trello in GAIA's integration settings. You select which Trello boards GAIA monitors and which Google Calendar receives the resulting events.",
      },
      {
        step: "Set due date sync and card creation rules",
        description:
          "Configure which Trello lists and card labels trigger calendar event creation, and define the event format. Set rules for which calendar event types should generate Trello cards when created manually.",
      },
      {
        step: "GAIA keeps Trello due dates and calendar events synchronized",
        description:
          "GAIA uses Trello webhooks to detect due date changes and updates calendar events in real time. It also monitors Google Calendar for new events that match card-creation templates.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync Trello checklist item due dates as well as card due dates?",
        answer:
          "Card-level due dates are synced by default. Checklist item due date syncing is configurable for teams that use Trello checklists as sub-task milestones and need those granular dates on their calendar.",
      },
      {
        question:
          "Does GAIA support multiple Trello boards synced to separate Google Calendars?",
        answer:
          "Yes. You can map individual Trello boards to specific Google Calendars — for example, routing a client board's due dates to a shared client calendar while keeping internal board dates on a team-only calendar.",
      },
      {
        question:
          "What happens in Google Calendar when a Trello card is archived or deleted?",
        answer:
          "When a Trello card is archived or deleted, GAIA removes or cancels the corresponding Google Calendar event and notifies any attendees if the event had been shared, keeping your calendar free of orphaned events.",
      },
    ],
  },

  "google-calendar-hubspot": {
    slug: "google-calendar-hubspot",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Sync meeting invites with HubSpot contacts and log calls to your CRM automatically",
    metaTitle:
      "Google Calendar + HubSpot Integration - CRM-Connected Meetings | GAIA",
    metaDescription:
      "Connect Google Calendar and HubSpot with GAIA. Automatically log Google Calendar meetings to HubSpot, sync contact details to calendar invites, and ensure every client interaction is captured in your CRM.",
    keywords: [
      "Google Calendar HubSpot integration",
      "HubSpot Google Calendar sync",
      "log meeting HubSpot calendar",
      "Google Calendar HubSpot CRM",
      "meeting CRM automation",
      "HubSpot calendar event sync",
    ],
    intro:
      "Sales and customer success teams live between two critical tools: Google Calendar for scheduling client meetings and HubSpot for managing the CRM records of those same clients. The problem is that these two systems rarely talk to each other. Meetings happen in Google Calendar but are manually logged in HubSpot — or worse, never logged at all. Contact details in HubSpot aren't visible in calendar invites. The result is a CRM that is perpetually behind and a team that wastes time on manual data entry.\n\nGAIA bridges Google Calendar and HubSpot so that client meetings are automatically enriched with CRM data and automatically logged as activities. When you schedule a meeting with a known HubSpot contact, GAIA adds their company, deal stage, and recent activity to the calendar event description so you're prepared. When the meeting ends, GAIA logs it as a HubSpot activity with attendees, duration, and any notes you add, keeping your CRM accurate without any manual entry.\n\nThis integration is essential for sales reps, account executives, and customer success managers who need their meeting and CRM records to stay in perfect alignment without the overhead of double data entry.",
    useCases: [
      {
        title: "Enrich calendar invites with HubSpot contact data",
        description:
          "When you schedule a Google Calendar event with a HubSpot contact's email, GAIA automatically adds their company, title, deal stage, and last interaction date to the event description so you walk into every meeting prepared.",
      },
      {
        title: "Auto-log completed meetings to HubSpot",
        description:
          "When a Google Calendar event with a HubSpot contact ends, GAIA logs it as a meeting activity in HubSpot with attendees, duration, and the event description, keeping your CRM up to date without manual logging.",
      },
      {
        title: "Create HubSpot follow-up tasks from calendar events",
        description:
          "After a meeting is logged, GAIA automatically creates a HubSpot follow-up task for the rep with a suggested due date so the next step is always captured and the deal keeps moving forward.",
      },
      {
        title: "Surface HubSpot deal context before meetings",
        description:
          "The day before a client meeting, GAIA sends you a briefing with the HubSpot deal status, recent email activity, open tasks, and any notes from previous meetings so you're fully prepared without opening HubSpot.",
      },
      {
        title: "Sync HubSpot meeting links to calendar invites",
        description:
          "When HubSpot Meetings is used to schedule calls, GAIA syncs those bookings to Google Calendar with full event details, ensuring your personal calendar reflects every client-scheduled meeting automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and HubSpot to GAIA",
        description:
          "Authorize Google Calendar and your HubSpot portal in GAIA's integration settings. GAIA matches calendar attendees to HubSpot contacts by email address to enrich and log events accurately.",
      },
      {
        step: "Configure enrichment, logging, and follow-up rules",
        description:
          "Set which HubSpot contact and deal fields should appear in calendar event descriptions, which completed event types should be auto-logged to HubSpot, and whether follow-up tasks should be created automatically.",
      },
      {
        step: "GAIA enriches meetings and logs them to HubSpot automatically",
        description:
          "Before each meeting GAIA enriches the calendar event with CRM context. After the meeting ends, GAIA logs the activity to HubSpot and creates follow-up tasks, completing the full sales activity loop.",
      },
    ],
    faqs: [
      {
        question: "What if a meeting attendee is not in HubSpot?",
        answer:
          "GAIA can automatically create a new HubSpot contact when a meeting is logged with an attendee email that doesn't match an existing contact, or it can flag the attendee for manual review depending on your preference.",
      },
      {
        question: "Can GAIA log internal meetings or only client-facing ones?",
        answer:
          "You can configure GAIA to log all meetings, only meetings with external attendees, or only meetings where attendees match known HubSpot contacts. This keeps your HubSpot activity log focused on customer interactions.",
      },
      {
        question:
          "Does GAIA support HubSpot deal associations when logging meetings?",
        answer:
          "Yes. When logging a meeting, GAIA associates the activity with the relevant HubSpot deal or deals linked to the attendee contacts, so the meeting appears in the deal timeline and not just the contact record.",
      },
    ],
  },

  "google-calendar-stripe": {
    slug: "google-calendar-stripe",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline:
      "Schedule billing cycle events and payment reminder deadlines directly from Stripe",
    metaTitle:
      "Google Calendar + Stripe Integration - Billing Cycles on Your Calendar | GAIA",
    metaDescription:
      "Connect Google Calendar and Stripe with GAIA. Automatically create calendar events for Stripe subscription renewals, failed payment follow-ups, and invoice due dates so your billing schedule is always visible.",
    keywords: [
      "Google Calendar Stripe integration",
      "Stripe billing calendar",
      "Stripe subscription renewal calendar",
      "Google Calendar Stripe automation",
      "payment reminder calendar event",
      "Stripe invoice due date calendar",
    ],
    intro:
      "Stripe manages your subscription billing, invoice schedules, and payment processing, but those financial events rarely appear in your team's calendar. Finance and operations teams need to know when major renewals are due, when trial periods end, and when significant invoices need follow-up — but this visibility currently requires logging into Stripe or running manual reports. Important billing events are invisible to the people who need to act on them.\n\nGAIA bridges Google Calendar and Stripe so your billing timeline becomes a first-class part of your team's schedule. Subscription renewal dates appear as calendar events with customer name and MRR value so account managers can reach out proactively. Failed payment follow-up reminders appear automatically after a charge fails. Invoice due dates become calendar events for your finance team so collections efforts are timely and organized.\n\nThis integration is particularly valuable for SaaS businesses where subscription renewals, churn prevention, and collections are operational priorities that deserve calendar visibility alongside other team activities.",
    useCases: [
      {
        title: "Subscription renewal events on the team calendar",
        description:
          "GAIA creates Google Calendar events for upcoming Stripe subscription renewals, including the customer name, plan, and MRR value, so account managers have advance notice for proactive check-ins before renewal dates.",
      },
      {
        title: "Failed payment follow-up reminders",
        description:
          "When a Stripe charge fails, GAIA creates a Google Calendar task or event for the responsible team member with the customer name, failed amount, and a suggested follow-up timeline to maximize recovery chances.",
      },
      {
        title: "Invoice due date calendar events",
        description:
          "GAIA syncs Stripe invoice due dates to Google Calendar so your finance team has a clear visual timeline of expected payments alongside other operational commitments.",
      },
      {
        title: "Trial expiration alerts",
        description:
          "When a Stripe trial period is approaching its end, GAIA creates a Google Calendar event for the account or sales team so they can engage the customer before the trial expires and influence the conversion decision.",
      },
      {
        title: "Monthly revenue review scheduling",
        description:
          "GAIA reads your Stripe billing cycle and automatically schedules monthly or quarterly revenue review meetings in Google Calendar aligned with your subscription billing dates so financial reviews happen at the right time.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Stripe to GAIA",
        description:
          "Authorize Google Calendar and your Stripe account in GAIA's integration settings using restricted API keys for Stripe. GAIA only reads billing event data and never writes to Stripe.",
      },
      {
        step: "Configure billing event types and calendar routing",
        description:
          "Select which Stripe events should create calendar events — renewals, failed payments, invoice due dates, trial expirations — and which Google Calendar should receive each event type.",
      },
      {
        step: "GAIA keeps your billing calendar current automatically",
        description:
          "GAIA listens to Stripe webhooks and creates or updates Google Calendar events as billing events occur. Your team has a live view of the billing schedule in their calendar without any manual data entry.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA filter Stripe subscription events by plan or MRR threshold?",
        answer:
          "Yes. You can configure GAIA to only create calendar events for renewals above a certain MRR value or for specific Stripe subscription plans, focusing calendar visibility on the customers that matter most.",
      },
      {
        question:
          "Does GAIA expose sensitive customer payment data in calendar event descriptions?",
        answer:
          "GAIA allows you to configure exactly which fields appear in calendar event descriptions. By default it includes customer name and renewal amount. Full payment details, card numbers, and sensitive data are never included.",
      },
      {
        question: "Can GAIA handle Stripe's metered billing invoices?",
        answer:
          "Yes. GAIA supports metered billing invoice events from Stripe. Invoice finalization and due dates for metered billing create calendar events with the estimated invoice amount based on usage data available at the time.",
      },
    ],
  },

  "google-calendar-teams": {
    slug: "google-calendar-teams",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Microsoft Teams",
    toolBSlug: "microsoft-teams",
    tagline:
      "Sync Microsoft Teams meetings to Google Calendar so your schedule is always complete",
    metaTitle:
      "Google Calendar + Microsoft Teams Integration - One Complete Schedule | GAIA",
    metaDescription:
      "Connect Google Calendar and Microsoft Teams with GAIA. Automatically sync Teams meeting invites to Google Calendar, create Teams meetings from Google Calendar events, and maintain a single unified schedule.",
    keywords: [
      "Google Calendar Microsoft Teams integration",
      "Teams Google Calendar sync",
      "Microsoft Teams calendar sync",
      "Google Calendar Teams meeting",
      "Teams meeting Google Calendar",
      "unified calendar Teams Google",
    ],
    intro:
      "Many organizations operate across both Google Workspace and Microsoft 365, with some teams using Google Calendar while others schedule via Microsoft Teams. The result is a fragmented scheduling landscape: Teams meeting invites don't appear in Google Calendar, and vice versa. Employees who work across both ecosystems maintain two separate calendars, miss cross-platform invites, and lose visibility into their full schedule.\n\nGAIA bridges Google Calendar and Microsoft Teams so that every meeting appears in a single unified view. Teams meeting invites sync to Google Calendar with the meeting link intact. Google Calendar events can generate Teams meetings automatically so organizers don't need to manage both tools. Availability blocks in one calendar are respected in the other so scheduling conflicts across platforms are eliminated.\n\nThis integration is essential for hybrid organizations using both Google Workspace and Microsoft 365, for consultants and contractors who work across client environments using different calendar systems, and for enterprise teams undergoing a migration between platforms who need both systems to operate together during the transition.",
    useCases: [
      {
        title: "Sync Teams meeting invites to Google Calendar",
        description:
          "GAIA automatically imports Microsoft Teams meeting invites into Google Calendar with the meeting join link, attendee list, and agenda so your Google Calendar shows your complete schedule including all Teams meetings.",
      },
      {
        title: "Create Teams meetings from Google Calendar events",
        description:
          "When you add a meeting to Google Calendar, GAIA can generate a Microsoft Teams meeting link and add it to the event description, so attendees who use Teams as their primary tool receive a proper Teams invite.",
      },
      {
        title: "Keep availability consistent across both platforms",
        description:
          "GAIA ensures that busy blocks from Teams meetings appear in Google Calendar and vice versa, so your availability is always accurate regardless of which scheduling tool a meeting organizer uses.",
      },
      {
        title: "Unified daily agenda across both calendars",
        description:
          "Each morning GAIA delivers a consolidated daily agenda that merges your Google Calendar events and Teams meetings into a single ordered list, so you always know your full schedule without checking two platforms.",
      },
      {
        title: "Meeting recording links in Google Calendar",
        description:
          "After a Teams meeting ends, GAIA updates the corresponding Google Calendar event with the Teams meeting recording link so participants who use Google Calendar can access the recording directly from their calendar event.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Microsoft Teams to GAIA",
        description:
          "Authorize Google Calendar via Google OAuth and Microsoft Teams via Microsoft OAuth in GAIA's integration settings. GAIA accesses your calendar data and Teams meeting schedule with read and limited write permissions.",
      },
      {
        step: "Configure sync direction and meeting creation preferences",
        description:
          "Choose whether sync is bidirectional or one-way, which event types generate Teams meetings from Google Calendar, and how far in advance future events should be imported.",
      },
      {
        step: "GAIA maintains a unified schedule across both platforms",
        description:
          "GAIA monitors both calendars for new and updated events and propagates changes in near real-time, ensuring your schedule is always complete and consistent in whichever calendar tool you prefer.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA duplicate events that are already in both calendars?",
        answer:
          "GAIA uses meeting ID and attendee matching to detect events that already exist in both calendars before creating a sync copy. Detected duplicates are flagged for review rather than blindly duplicated.",
      },
      {
        question:
          "Can GAIA handle recurring Teams meetings synced to Google Calendar?",
        answer:
          "Yes. Recurring Teams meeting series are imported as recurring Google Calendar events. When the Teams series is updated or cancelled, GAIA updates the entire Google Calendar series accordingly.",
      },
      {
        question:
          "Does GAIA work if my organization uses both Google Workspace and Microsoft 365?",
        answer:
          "Yes. This is the primary use case GAIA is designed for. GAIA acts as the neutral bridge between both platforms without requiring IT-level federation or directory sync between your Google and Microsoft tenants.",
      },
    ],
  },

  "google-calendar-discord": {
    slug: "google-calendar-discord",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline:
      "Post Google Calendar event reminders to Discord channels automatically",
    metaTitle:
      "Google Calendar + Discord Integration - Event Reminders in Discord | GAIA",
    metaDescription:
      "Connect Google Calendar and Discord with GAIA. Automatically post event reminders and schedule announcements to Discord channels, and create calendar events from Discord community discussions.",
    keywords: [
      "Google Calendar Discord integration",
      "Discord calendar reminders",
      "post event Discord Google Calendar",
      "Google Calendar Discord automation",
      "Discord event announcement calendar",
      "community calendar Discord",
    ],
    intro:
      "Discord communities, gaming groups, and remote teams rely on Discord as their primary communication platform, but event reminders and schedule announcements still require someone to manually post in the right channel at the right time. Google Calendar holds the events, but Discord is where the audience is. Without a bridge, event organizers spend time crafting manual announcements and followers miss events they would have attended.\n\nGAIA connects Google Calendar and Discord so that event reminders are posted to the right Discord channels automatically. When an event on your calendar is approaching, GAIA posts a formatted reminder to your designated Discord channel with the event name, time, and any relevant details. When community members discuss an event in Discord, GAIA can create the corresponding Google Calendar entry and share the invite link back to the channel.\n\nThis integration is ideal for Discord community managers who run regular events and want automated reminders, for game development teams using Discord as their primary coordination tool, and for any remote team that has adopted Discord for voice and text communication and wants their meeting schedule surfaced where their team already spends time.",
    useCases: [
      {
        title: "Automated event reminders to Discord channels",
        description:
          "GAIA posts formatted event reminders to designated Discord channels before upcoming Google Calendar events, including the event name, start time, agenda, and any join links so community members are always informed.",
      },
      {
        title: "Create calendar events from Discord discussions",
        description:
          "When an event, game night, or team meeting is discussed in Discord, tell GAIA to create the corresponding Google Calendar event and share the invite link back to the channel so participants can add it to their calendars.",
      },
      {
        title: "Daily schedule digest in Discord",
        description:
          "GAIA posts a morning schedule summary to a designated Discord channel listing the day's events so your community or team knows what's happening without anyone needing to check a calendar.",
      },
      {
        title: "Event cancellation and rescheduling announcements",
        description:
          "When a Google Calendar event is cancelled or rescheduled, GAIA automatically posts an update to the relevant Discord channel so attendees are informed immediately without a manual announcement.",
      },
      {
        title: "Community event RSVP tracking",
        description:
          "GAIA posts event announcements to Discord with RSVP reaction buttons. Reactions are tracked and summarized back in Google Calendar as expected attendance, giving organizers headcount visibility without a separate RSVP tool.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Discord to GAIA",
        description:
          "Authorize Google Calendar in GAIA's integration settings and invite the GAIA bot to your Discord server. You select which Google Calendars to monitor and which Discord channels receive event notifications.",
      },
      {
        step: "Configure reminder timing and notification format",
        description:
          "Set how far in advance GAIA posts reminders — for example, 24 hours and 1 hour before — and customize the message format including which event details to include and how mentions should be used.",
      },
      {
        step: "GAIA posts reminders and manages announcements automatically",
        description:
          "GAIA monitors your Google Calendars and posts reminders to Discord on schedule. It also handles updates and cancellations automatically so your Discord community always has current event information.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA post reminders to multiple Discord channels for different calendars?",
        answer:
          "Yes. You can map different Google Calendars to different Discord channels. For example, your community events calendar might post to a public announcements channel while a team calendar posts to a private staff channel.",
      },
      {
        question:
          "Can GAIA mention specific Discord roles when posting event reminders?",
        answer:
          "Yes. You can configure GAIA to mention specific Discord roles in event reminder posts — for example, mentioning the @everyone or @team role for different event types — to ensure the right people are notified.",
      },
      {
        question:
          "Does GAIA support Discord's native Events feature in addition to channel posts?",
        answer:
          "Yes. GAIA can create Discord scheduled events from Google Calendar entries in addition to posting text reminders, giving your community a native Discord event to express interest in and receive Discord's own reminder notifications.",
      },
    ],
  },

  "google-calendar-drive": {
    slug: "google-calendar-drive",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach Drive docs to calendar events and create event notes in Drive automatically",
    metaTitle:
      "Google Calendar + Google Drive Integration - Meetings Linked to Documents | GAIA",
    metaDescription:
      "Connect Google Calendar and Google Drive with GAIA. Automatically attach relevant Drive documents to calendar events, create meeting notes docs for upcoming meetings, and organize Drive files by meeting context.",
    keywords: [
      "Google Calendar Google Drive integration",
      "Google Drive calendar automation",
      "meeting notes Google Drive",
      "attach Drive file calendar event",
      "Google Calendar Drive sync",
      "document meeting calendar Google",
    ],
    intro:
      "Every meeting on your Google Calendar has documents associated with it — agendas, presentation decks, reference materials, and notes — but those files live in Google Drive disconnected from the calendar event. You spend the minutes before each meeting hunting through Drive for the right document, and after meetings, notes end up scattered in random Drive folders with no connection to the calendar entry that generated them.\n\nGAIA connects Google Calendar and Google Drive so meetings and documents are always linked. Before a scheduled meeting, GAIA identifies relevant Drive documents by project name, attendee, or keyword and attaches them to the calendar event so everything you need is one click away. After each meeting, GAIA creates a structured notes document in the right Drive folder, pre-filled with the attendee list, agenda, and action item template, ready for you to fill in during the call.\n\nThis integration is invaluable for professionals who run frequent meetings and need instant document access, for project managers who need meeting notes consistently organized in Drive, and for teams who want their calendar to serve as the single entry point for all meeting-related material.",
    useCases: [
      {
        title: "Auto-attach relevant Drive docs to calendar events",
        description:
          "GAIA searches Google Drive for documents related to each calendar event by project name, attendee emails, and keywords, then attaches the most relevant files to the event description so you always have your materials ready.",
      },
      {
        title: "Create meeting notes docs before each meeting",
        description:
          "GAIA generates a structured Google Doc for each upcoming meeting and links it to the calendar event. The doc is pre-filled with the meeting title, attendees, agenda from the event description, and an action items template.",
      },
      {
        title: "Organize Drive files by meeting context",
        description:
          "GAIA creates a Drive folder for each recurring meeting series and saves related documents — agendas, notes, presentations — to that folder automatically, building an organized archive of meeting materials over time.",
      },
      {
        title: "Share Drive docs with all calendar attendees",
        description:
          "GAIA can automatically grant view or comment access to Drive documents attached to a calendar event to all event attendees, ensuring everyone has access to meeting materials without manual sharing.",
      },
      {
        title: "Post-meeting follow-up doc distribution",
        description:
          "After a meeting ends, GAIA updates the meeting notes doc with a finalized header and shares it with all attendees via email and Google Drive, ensuring everyone has a copy of the notes without requiring manual distribution.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Google Drive to GAIA",
        description:
          "Authorize Google Calendar and Google Drive in GAIA's integration settings using Google OAuth. Both services are part of the same Google Workspace so a single authorization covers both for most users.",
      },
      {
        step: "Configure document matching and notes template preferences",
        description:
          "Define how GAIA should search for relevant Drive documents — by folder, shared owner, keyword match, or project label. Choose your preferred meeting notes template and the Drive folder structure for meeting archives.",
      },
      {
        step: "GAIA links documents to meetings and manages the notes lifecycle",
        description:
          "GAIA runs before each meeting to attach relevant documents and create notes docs, then after meetings to finalize and distribute notes. You can also query GAIA to find all Drive documents associated with any past meeting.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA decide which Drive documents are relevant to a calendar event?",
        answer:
          "GAIA uses the event title, attendee list, and event description keywords to search Drive. It ranks results by recency, sharing overlap with attendees, and keyword match strength, then attaches the top matches.",
      },
      {
        question:
          "Can GAIA create meeting notes in a specific Drive folder structure?",
        answer:
          "Yes. You can define a folder structure template — for example, by year, month, and project — and GAIA will create each meeting notes doc in the correct folder automatically, building a consistent archive over time.",
      },
      {
        question:
          "Does GAIA modify existing calendar events to add Drive links?",
        answer:
          "Yes. GAIA appends Drive document links to the event description or uses Google Calendar's attachment field where available. It never removes existing event content and only appends to existing descriptions.",
      },
    ],
  },

  "google-calendar-figma": {
    slug: "google-calendar-figma",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Schedule design reviews from Figma milestones and create calendar events from Figma project timelines",
    metaTitle:
      "Google Calendar + Figma Integration - Design Reviews on Your Calendar | GAIA",
    metaDescription:
      "Connect Google Calendar and Figma with GAIA. Automatically schedule design review meetings from Figma project milestones, link Figma files to calendar events, and keep your design timeline visible on your calendar.",
    keywords: [
      "Google Calendar Figma integration",
      "Figma Google Calendar sync",
      "Figma design review calendar",
      "Figma milestone calendar event",
      "Google Calendar Figma automation",
      "design schedule Figma calendar",
    ],
    intro:
      "Figma is where design work happens: wireframes, high-fidelity mockups, and design system components live in Figma projects with their own version history and comment threads. Google Calendar is where design reviews, handoff meetings, and feedback sessions get scheduled. The gap between them means design milestones rarely appear on anyone's calendar, review meetings lack direct links to the Figma files being reviewed, and the design timeline is invisible to stakeholders who rely on Google Calendar.\n\nGAIA bridges Google Calendar and Figma so that design milestones become calendar events and calendar events become linked to the right Figma files. When a Figma project milestone or version tag is created, GAIA can schedule a design review meeting automatically with the relevant stakeholders and a direct link to the Figma frame. When a design review is added to Google Calendar, GAIA can search Figma for the relevant file and attach the link so reviewers have instant access.\n\nThis integration is built for product designers and design leads who want their design schedule surfaced in the broader organization's calendar, and for product managers who need design milestone visibility alongside engineering and marketing timelines.",
    useCases: [
      {
        title: "Schedule design review meetings from Figma milestones",
        description:
          "When a Figma project version is tagged or a milestone comment is added, GAIA schedules a Google Calendar design review event with the right stakeholders, a direct Figma link, and an agenda pre-populated with the milestone details.",
      },
      {
        title: "Attach Figma file links to design review calendar events",
        description:
          "When a design review or feedback session is added to Google Calendar, GAIA searches Figma for the relevant project file and appends the direct link to the event description so reviewers can open Figma before the meeting.",
      },
      {
        title: "Design handoff events with Figma inspect links",
        description:
          "When a Figma design is marked ready for development handoff, GAIA creates a Google Calendar handoff meeting invite for the design and engineering team with a link directly to the Figma inspect view.",
      },
      {
        title: "Design deadline calendar events from Figma project dates",
        description:
          "GAIA reads project timeline information from Figma and creates all-day deadline events in Google Calendar for each design deliverable, giving the broader team visibility into the design schedule in the tool they use for planning.",
      },
      {
        title: "Figma comment review reminders on calendar",
        description:
          "When a Figma file accumulates unresolved comments older than a configurable threshold, GAIA creates a Google Calendar task for the responsible designer to schedule a comment review session, keeping design feedback loops from stalling.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Figma to GAIA",
        description:
          "Authorize Google Calendar via Google OAuth and your Figma account via Figma's OAuth in GAIA's integration settings. You select which Figma teams and projects GAIA monitors for milestone events.",
      },
      {
        step: "Configure milestone triggers and calendar event templates",
        description:
          "Define which Figma events create calendar events — version tags, milestone comments, handoff status changes — and set the calendar event template including attendees, duration, and agenda format.",
      },
      {
        step: "GAIA links design milestones to your calendar automatically",
        description:
          "GAIA monitors Figma for milestone activity and creates Google Calendar events automatically. It also watches for new design review calendar events and attaches the relevant Figma file links proactively.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA link to a specific Figma frame or page rather than the whole file?",
        answer:
          "Yes. GAIA can generate direct links to specific Figma frames, pages, or components when creating calendar events, allowing reviewers to open exactly the section under review rather than navigating the full file.",
      },
      {
        question:
          "Does GAIA support Figma's branching feature when syncing to calendar?",
        answer:
          "Yes. GAIA can detect Figma branch merge events and create design review calendar events for the merged changes, supporting design teams that use branching for parallel workstreams.",
      },
      {
        question:
          "Can GAIA notify Figma collaborators when a design review calendar event is created?",
        answer:
          "Yes. GAIA can post a comment in the relevant Figma file notifying collaborators that a review meeting has been scheduled and include the Google Calendar event link, keeping the design and calendar systems connected bidirectionally.",
      },
    ],
  },

  "todoist-google-calendar": {
    slug: "todoist-google-calendar",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline: "Turn tasks into calendar events and deadlines into time blocks",
    metaTitle:
      "Todoist + Google Calendar Automation - Sync Tasks and Events | GAIA",
    metaDescription:
      "Automate Todoist and Google Calendar with GAIA. Convert tasks with due dates into calendar events, block time for high-priority work, and keep your schedule aligned with your to-do list automatically.",
    keywords: [
      "Todoist Google Calendar integration",
      "Todoist Google Calendar sync",
      "task to calendar event",
      "Todoist deadline sync",
      "time blocking automation",
      "connect Todoist and Google Calendar",
    ],
    intro:
      "Todoist captures everything you need to do, and Google Calendar structures when you will do it — but without a connection between them, tasks pile up without time allocated and calendar events get created without linking back to the underlying work. The result is a schedule that doesn't reflect reality and a task list that never shrinks.\n\nGAIA connects Todoist and Google Calendar so your commitments and your time stay in sync. When you add a task with a due date in Todoist, GAIA can automatically create a corresponding Google Calendar event and block the time needed to complete it. When a meeting ends and action items emerge, GAIA can capture them as Todoist tasks with deadlines derived from the calendar event details.\n\nThis integration is particularly valuable for individuals who plan projects in Todoist but struggle to protect calendar time for deep work, and for teams who want every project deadline reflected on a shared calendar so capacity is visible at a glance.",
    useCases: [
      {
        title: "Auto-create calendar events from Todoist due dates",
        description:
          "Whenever you set a due date on a Todoist task, GAIA creates a matching Google Calendar event, letting you see your workload alongside meetings without manual duplication.",
      },
      {
        title: "Time-block high-priority tasks",
        description:
          "GAIA scans your Todoist inbox for priority-1 tasks and reserves focused work blocks on Google Calendar, protecting uninterrupted time before your day fills up with meetings.",
      },
      {
        title: "Capture meeting action items as Todoist tasks",
        description:
          "After a Google Calendar event ends, GAIA prompts you to log action items and creates them as Todoist tasks assigned to the relevant project with the agreed deadline.",
      },
      {
        title: "Daily planning digest",
        description:
          "Each morning GAIA cross-references your Todoist due-today list with your Google Calendar schedule and sends a combined briefing so you can re-prioritize before the day starts.",
      },
      {
        title: "Project deadline milestones on shared calendar",
        description:
          "GAIA mirrors Todoist project milestones onto a shared Google Calendar so every team member can see upcoming deadlines without needing access to the Todoist project.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Google Calendar to GAIA",
        description:
          "Authenticate both accounts in GAIA's integration settings using OAuth. GAIA only requests the scopes it needs — task read/write for Todoist and event read/write for Google Calendar.",
      },
      {
        step: "Configure your sync preferences",
        description:
          "Tell GAIA which Todoist projects to watch, how much time to block per task priority, and which Google Calendar to write events to. Use plain language to describe your rules.",
      },
      {
        step: "GAIA keeps tasks and calendar in sync automatically",
        description:
          "From that point on, GAIA monitors both platforms in real time — creating events when tasks are added, updating times when deadlines shift, and flagging conflicts before they become problems.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA create duplicate events if I update a Todoist task's due date?",
        answer:
          "No. GAIA tracks the link between each Todoist task and its Google Calendar event. When a due date changes, GAIA updates the existing event rather than creating a new one.",
      },
      {
        question:
          "Can I choose which Todoist projects sync to Google Calendar?",
        answer:
          "Yes. During setup you specify exactly which projects or labels trigger calendar event creation. Personal errands and work projects can sync to different calendars.",
      },
      {
        question:
          "What happens to the Google Calendar event if I complete the Todoist task early?",
        answer:
          "GAIA can optionally mark the calendar event as cancelled or delete it when the linked task is checked off, keeping your calendar free of completed work.",
      },
      {
        question: "Does this work with recurring Todoist tasks?",
        answer:
          "Yes. GAIA recognises recurring tasks and creates recurring Google Calendar events with the same frequency, so weekly reviews and regular check-ins appear on your calendar automatically.",
      },
    ],
  },

  "todoist-salesforce": {
    slug: "todoist-salesforce",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Surface Salesforce action items in Todoist and log work back automatically",
    metaTitle:
      "Todoist + Salesforce Automation - Bridge CRM Tasks and Personal Planning | GAIA",
    metaDescription:
      "Connect Todoist and Salesforce with GAIA. Create Todoist tasks from Salesforce opportunities, log activity back to CRM records, and keep your sales workflow on track without switching tools.",
    keywords: [
      "Todoist Salesforce integration",
      "Todoist Salesforce automation",
      "Salesforce task sync",
      "CRM personal task manager",
      "Salesforce opportunity follow-up",
      "connect Todoist and Salesforce",
    ],
    intro:
      "Salesforce is the system of record for enterprise sales teams, but its task management interface is rarely where reps do their best planning. Most high-performing account executives maintain a parallel personal task list — often in Todoist — to actually run their day. The problem is that keeping two systems in sync requires manual updates that eat into selling time and almost inevitably lead to one system falling behind.\n\nGAIA automates the bridge between Todoist and Salesforce so your personal planner and your CRM tell the same story. When a Salesforce opportunity reaches a critical stage or a task is due, GAIA creates the corresponding Todoist item so it appears in your daily plan. When you complete that task, GAIA logs the activity back in Salesforce against the right opportunity, contact, or account so the CRM record stays current without you ever opening Salesforce just to log a note.\n\nThis integration suits enterprise account executives who manage complex deals in Salesforce but plan their days in Todoist, and sales operations teams who want activity compliance across the organization without forcing reps to change their personal workflow.",
    useCases: [
      {
        title: "Create Todoist tasks from Salesforce opportunity stages",
        description:
          "When an opportunity moves to Proposal or Negotiation, GAIA creates a Todoist task with the follow-up action, contact name, and deal value so nothing gets missed in a large pipeline.",
      },
      {
        title: "Log Todoist completions as Salesforce activities",
        description:
          "Completing a sales-related Todoist task triggers GAIA to log a completed activity on the linked Salesforce record, maintaining CRM hygiene without manual data entry.",
      },
      {
        title: "Stalled opportunity alerts",
        description:
          "GAIA detects Salesforce opportunities with no activity updates in a configurable window and creates urgent Todoist tasks to re-engage before the opportunity goes cold.",
      },
      {
        title: "Contract renewal reminders",
        description:
          "GAIA reads renewal dates from Salesforce and creates Todoist tasks 90, 60, and 30 days ahead, ensuring renewal conversations start early enough to protect revenue.",
      },
      {
        title: "Post-meeting follow-up workflow",
        description:
          "After logging a Salesforce meeting, GAIA creates a set of standard follow-up tasks in Todoist — send recap email, update opportunity stage, schedule next call — so every meeting leads to clear next actions.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Salesforce to GAIA",
        description:
          "Authenticate your Todoist account and Salesforce org in GAIA's settings. GAIA uses Salesforce Connected App OAuth so your admin can approve the connection with the right permission set.",
      },
      {
        step: "Define your opportunity-to-task triggers",
        description:
          "Map Salesforce stages, record types, and field changes to Todoist task templates. Specify due date offsets, priority levels, and which Todoist project receives each type of task.",
      },
      {
        step: "GAIA keeps CRM and personal planner in sync",
        description:
          "GAIA monitors Salesforce for trigger conditions and Todoist for task completions, creating items and logging activities automatically so both systems stay accurate.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA require a Salesforce admin to set up?",
        answer:
          "For individual rep use, a standard Salesforce user with API access is sufficient. For org-wide deployment, an admin may need to approve the Connected App.",
      },
      {
        question: "Which Salesforce objects does GAIA interact with?",
        answer:
          "GAIA works with Opportunities, Contacts, Accounts, Tasks, and Events. Activity logging creates Task records against the relevant Opportunity or Contact.",
      },
      {
        question:
          "Can I use this with Salesforce Sales Cloud and Service Cloud?",
        answer:
          "Yes. GAIA supports both Sales Cloud and Service Cloud objects, so account managers and support reps can each configure workflows suited to their use case.",
      },
      {
        question: "Will Todoist task notes be preserved in Salesforce?",
        answer:
          "Yes. Notes added to a Todoist task are included in the Salesforce activity description when GAIA logs the completed task, preserving context in the CRM.",
      },
    ],
  },

  "todoist-zoom": {
    slug: "todoist-zoom",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline: "Turn Zoom meeting outcomes into Todoist tasks automatically",
    metaTitle:
      "Todoist + Zoom Automation - Capture Meeting Action Items as Tasks | GAIA",
    metaDescription:
      "Connect Todoist and Zoom with GAIA. Automatically create Todoist tasks from Zoom meeting action items, get pre-meeting task reminders, and ensure every meeting leads to tracked follow-ups.",
    keywords: [
      "Todoist Zoom integration",
      "Todoist Zoom automation",
      "Zoom meeting action items",
      "meeting to task automation",
      "post-meeting follow-up tasks",
      "connect Todoist and Zoom",
    ],
    intro:
      "Zoom meetings generate commitments — someone agrees to send a document, another person will follow up with a client, a decision is made that requires someone to update the project plan. But without a reliable system for capturing these commitments the moment they're made, action items evaporate as quickly as the meeting window closes.\n\nGAIA connects Zoom and Todoist so meeting outcomes flow directly into your task manager. When a Zoom meeting ends, GAIA can process the transcript to identify action items and create Todoist tasks for each, assigned to the right person with a realistic due date. Before a meeting starts, GAIA checks your Todoist list for tasks related to that meeting's attendees or project and surfaces them as a pre-meeting briefing so you walk in prepared.\n\nThis integration is essential for anyone who runs or participates in regular meetings and wants to close the gap between what gets committed in a call and what actually gets tracked and executed. It is particularly powerful for team leads, project managers, and client-facing professionals who have multiple meetings per day.",
    useCases: [
      {
        title: "Auto-extract action items from Zoom transcripts",
        description:
          "After a Zoom meeting, GAIA analyses the transcript for commitments and action items, creates Todoist tasks for each, and assigns them to the relevant team member with a suggested due date.",
      },
      {
        title: "Pre-meeting task briefing",
        description:
          "Fifteen minutes before a Zoom call, GAIA surfaces any open Todoist tasks related to the meeting's attendees or project so you can review outstanding items before the call starts.",
      },
      {
        title: "Meeting summary to Todoist project",
        description:
          "GAIA generates a structured meeting summary from the Zoom transcript and adds it as a comment to the relevant Todoist project, giving team members who missed the call a quick catch-up.",
      },
      {
        title: "Recurring meeting task reset",
        description:
          "For recurring Zoom meetings, GAIA recreates the standard preparation checklist in Todoist before each occurrence so weekly syncs always start with the same level of preparation.",
      },
      {
        title: "Follow-up deadline tracking",
        description:
          "When action items are captured from a Zoom meeting, GAIA sets due dates based on what was said — 'by end of week' becomes Friday, 'tomorrow' becomes the next business day — and alerts you if they are not completed in time.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Zoom to GAIA",
        description:
          "Authenticate your Todoist account and connect your Zoom account via OAuth. Enable Zoom cloud recording and transcript generation so GAIA can process meeting content.",
      },
      {
        step: "Set your meeting-to-task preferences",
        description:
          "Configure which Zoom meetings should trigger task creation, which Todoist project receives the tasks, and whether action items should be auto-assigned or reviewed before saving.",
      },
      {
        step: "GAIA processes meetings and creates tasks automatically",
        description:
          "After each qualifying Zoom meeting, GAIA processes the transcript, extracts action items, and creates Todoist tasks — all within minutes of the meeting ending.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA require Zoom cloud recording to extract action items?",
        answer:
          "Cloud recording with auto-transcription is the most reliable method, but GAIA can also process meeting notes you paste manually if cloud transcripts are not available.",
      },
      {
        question:
          "Can GAIA assign action items to other team members' Todoist accounts?",
        answer:
          "If team members have also connected their Todoist accounts to GAIA, it can assign tasks to them directly. Otherwise, it assigns tasks to you with the responsible person noted in the task description.",
      },
      {
        question: "How accurate is the action item extraction?",
        answer:
          "GAIA uses language model analysis on the Zoom transcript to identify commitment patterns. You can configure a review step where extracted tasks are presented for approval before being saved.",
      },
      {
        question: "Does this work with Zoom Webinars as well as Zoom Meetings?",
        answer:
          "Yes. GAIA supports both Zoom Meetings and Zoom Webinars, making it useful for post-webinar follow-up task creation as well as internal meeting action items.",
      },
    ],
  },

  "todoist-teams": {
    slug: "todoist-teams",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Microsoft Teams",
    toolBSlug: "teams",
    tagline:
      "Surface Todoist tasks in Teams and capture action items from chats",
    metaTitle:
      "Todoist + Microsoft Teams Automation - Tasks and Chat in Sync | GAIA",
    metaDescription:
      "Connect Todoist and Microsoft Teams with GAIA. Get task reminders in Teams channels, capture action items from Teams conversations, and keep your personal task list visible where your team collaborates.",
    keywords: [
      "Todoist Microsoft Teams integration",
      "Todoist Teams automation",
      "Teams task reminders",
      "capture action items Teams",
      "Todoist Teams workflow",
      "connect Todoist and Teams",
    ],
    intro:
      "Microsoft Teams is the communication backbone of millions of organizations, hosting everything from quick chat messages to full project discussions. But the action items that emerge from those conversations routinely disappear into the chat history, never making it to a task manager. Todoist users who rely on it for personal planning find themselves manually transcribing chat commitments into tasks — a slow, error-prone process that means many follow-ups simply never get captured.\n\nGAIA bridges Todoist and Microsoft Teams so your task manager and your team chat reinforce each other. Task reminders and deadline alerts surface as Teams notifications in the channels where your team is active. Conversely, when an action item surfaces in a Teams message or meeting chat, GAIA can capture it as a Todoist task with one command, preserving the original message as context.\n\nThis integration is particularly powerful in organizations that run on Microsoft 365, where Teams is the daily hub but individual contributors want the simplicity of Todoist for personal planning. It removes the friction of switching between platforms while ensuring commitments made in chat always make it to the task list.",
    useCases: [
      {
        title: "Task due-date alerts in Teams channels",
        description:
          "GAIA sends a Teams message to the relevant channel when a Todoist task deadline approaches, tagging the responsible person so the team is never surprised by a missed deadline.",
      },
      {
        title: "Capture Teams messages as Todoist tasks",
        description:
          "Reply to any Teams message with a GAIA command or use a message action to instantly convert it into a Todoist task with the message content, sender, and channel context preserved.",
      },
      {
        title: "Morning briefing in Teams",
        description:
          "GAIA posts your Todoist due-today list as a personal Teams message each morning so your day's priorities are visible right when you open your collaboration hub.",
      },
      {
        title: "Teams meeting action item capture",
        description:
          "After a Teams meeting, GAIA processes the meeting transcript or chat log to identify action items and creates Todoist tasks for each commitment made during the call.",
      },
      {
        title: "Project progress updates",
        description:
          "When a Todoist project reaches a completion milestone, GAIA posts a progress update to the designated Teams channel so stakeholders are informed without a manual status message.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Microsoft Teams to GAIA",
        description:
          "Authenticate your Todoist account and add the GAIA app to your Microsoft Teams workspace. Your Microsoft 365 admin may need to approve the app installation.",
      },
      {
        step: "Configure channels and notification rules",
        description:
          "Map Todoist projects to Teams channels, set reminder lead times, and enable the message capture command so team members can start converting chat messages to tasks.",
      },
      {
        step: "GAIA keeps tasks and chat aligned",
        description:
          "GAIA monitors Todoist for upcoming deadlines and Teams for capture triggers, posting alerts and creating tasks automatically so both systems stay current.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA require a Microsoft 365 admin to install?",
        answer:
          "Individual users can install GAIA as a personal Teams app without admin approval. For organization-wide deployment, an admin may need to approve the app in the Teams admin center.",
      },
      {
        question: "Can GAIA post to both Teams channels and personal chats?",
        answer:
          "Yes. GAIA can send task alerts to shared channels for team-visible deadlines and to personal chats for private reminders.",
      },
      {
        question: "Will GAIA capture tasks from Teams meeting chats?",
        answer:
          "Yes. GAIA monitors Teams meeting chat threads and can extract action items from in-meeting messages, creating Todoist tasks after the meeting ends.",
      },
      {
        question: "Does this work with Teams on mobile?",
        answer:
          "Yes. Since both Todoist and Teams have mobile apps and GAIA operates server-side, the integration works regardless of which device you use to access Teams.",
      },
    ],
  },

  "todoist-figma": {
    slug: "todoist-figma",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline: "Connect design work in Figma with task tracking in Todoist",
    metaTitle:
      "Todoist + Figma Automation - Link Design Tasks and Figma Files | GAIA",
    metaDescription:
      "Connect Todoist and Figma with GAIA. Create Todoist tasks from Figma comments and feedback, link design files to tasks, and track design work progress without leaving your task manager.",
    keywords: [
      "Todoist Figma integration",
      "Todoist Figma automation",
      "Figma comment to task",
      "design task management",
      "link Figma files to tasks",
      "connect Todoist and Figma",
    ],
    intro:
      "Design work lives in Figma — components, prototypes, and iterations accumulate across files and projects. But the feedback, revisions, and handoff tasks that design work generates need to be tracked somewhere more structured than Figma comments, which get buried as the file evolves. Designers often end up with a long list of revision requests scattered across Figma comment threads that are difficult to prioritize and even harder to mark as complete.\n\nGAIA connects Figma and Todoist so design feedback becomes actionable tasks and tracked work stays linked to the files it relates to. When a stakeholder leaves a comment on a Figma file, GAIA can capture it as a Todoist task assigned to the designer responsible for that component. When a Todoist task is linked to a Figma frame, GAIA surfaces the file link in the task so designers can jump directly to the relevant canvas without hunting through projects.\n\nThis integration is valuable for product designers managing feedback from multiple stakeholders across several files, for design teams using Todoist to coordinate shared work, and for design leads who want visibility into revision backlogs without subscribing to Figma comment notifications that overwhelm the inbox.",
    useCases: [
      {
        title: "Convert Figma comments to Todoist tasks",
        description:
          "When a stakeholder leaves a revision comment on a Figma file, GAIA creates a Todoist task with the comment text, the file and frame link, and the commenter name so nothing slips through.",
      },
      {
        title: "Link Figma frames to Todoist design tasks",
        description:
          "GAIA attaches the relevant Figma frame URL to Todoist design tasks so designers can open the exact frame that needs work with one click rather than navigating through the file.",
      },
      {
        title: "Design handoff checklist",
        description:
          "When a Figma file is marked ready for development, GAIA creates a handoff checklist in Todoist — export assets, update component documentation, notify the engineering team — so handoffs are consistent.",
      },
      {
        title: "Revision round tracking",
        description:
          "GAIA tracks open Figma comments and their linked Todoist tasks, alerting the designer when revision tasks are overdue so feedback does not age unaddressed.",
      },
      {
        title: "Component audit task generation",
        description:
          "When a Figma library component is updated, GAIA creates Todoist tasks to review screens that use the component, ensuring all affected designs are updated as part of the library change.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Figma to GAIA",
        description:
          "Authenticate your Todoist account and your Figma account in GAIA's settings. Select the Figma projects and files you want GAIA to monitor for comments and changes.",
      },
      {
        step: "Configure comment and task rules",
        description:
          "Specify which comment types should create Todoist tasks, which Todoist project receives design tasks, and whether all comments or only those with specific tags trigger task creation.",
      },
      {
        step: "GAIA bridges design feedback and task management",
        description:
          "GAIA monitors Figma for new comments and task-relevant activity, creates Todoist tasks automatically, and maintains the link between tasks and frames throughout the revision cycle.",
      },
    ],
    faqs: [
      {
        question:
          "Will GAIA create a task for every Figma comment or only specific ones?",
        answer:
          "You can configure GAIA to capture all comments or only those that meet criteria such as containing specific tags, being left by certain people, or being unresolved after a set time.",
      },
      {
        question:
          "Can GAIA resolve the Figma comment when the Todoist task is completed?",
        answer:
          "Yes. When you mark the linked Todoist task complete, GAIA can automatically resolve the corresponding Figma comment so your comment thread stays clean.",
      },
      {
        question: "Does GAIA work with Figma's branching feature?",
        answer:
          "GAIA monitors both main files and branches. Tasks created from branch comments are linked to the branch frame URL and tagged to distinguish them from main file tasks.",
      },
      {
        question: "Can multiple designers on a team use this integration?",
        answer:
          "Yes. Each designer connects their own accounts and GAIA routes Figma comment tasks to the designer assigned to the relevant frame or component.",
      },
    ],
  },

  "todoist-stripe": {
    slug: "todoist-stripe",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline: "Turn Stripe payment events into actionable tasks automatically",
    metaTitle: "Todoist + Stripe Automation - Payment Events to Tasks | GAIA",
    metaDescription:
      "Connect Todoist and Stripe with GAIA. Create Todoist tasks from Stripe payment failures, subscription events, and churn signals so your team acts on revenue-critical moments immediately.",
    keywords: [
      "Todoist Stripe integration",
      "Todoist Stripe automation",
      "Stripe payment task",
      "payment failure follow-up",
      "subscription churn task",
      "connect Todoist and Stripe",
    ],
    intro:
      "Stripe processes the revenue events that keep a business running, but the human follow-up those events require — reaching out after a failed payment, welcoming a new subscriber, investigating a dispute — has to happen in a separate tool. Without a direct connection between Stripe's event stream and your task manager, critical follow-ups depend on someone monitoring the Stripe dashboard and manually creating tasks, a process that is slow, inconsistent, and easy to neglect during busy periods.\n\nGAIA connects Stripe and Todoist so revenue-critical events automatically generate the right follow-up tasks. A failed payment creates an outreach task for your billing team. A subscription cancellation triggers a win-back checklist. A new enterprise signup kicks off the onboarding task sequence. Your team responds to every important Stripe event as a structured, tracked task rather than an email notification that gets buried.\n\nThis integration is particularly valuable for SaaS companies, subscription businesses, and e-commerce operators who want to minimize churn and maximize revenue recovery without building custom automation or relying on engineers to write webhook handlers.",
    useCases: [
      {
        title: "Failed payment follow-up tasks",
        description:
          "When Stripe reports a failed payment, GAIA creates a Todoist task to contact the customer with the payment amount, customer name, and failure reason included so your billing team has full context.",
      },
      {
        title: "Subscription cancellation win-back workflow",
        description:
          "When a Stripe subscription is cancelled, GAIA creates a win-back task checklist — send retention offer, log cancellation reason, update CRM — so every cancellation gets a structured response.",
      },
      {
        title: "New subscriber onboarding tasks",
        description:
          "When a new Stripe subscription is created, GAIA triggers a Todoist onboarding checklist — welcome email, account setup verification, first check-in call — so every new customer is handled consistently.",
      },
      {
        title: "Dispute and chargeback response",
        description:
          "When Stripe logs a dispute, GAIA creates an urgent Todoist task with the dispute details and deadline so your team responds within Stripe's evidence submission window.",
      },
      {
        title: "Monthly revenue reconciliation reminder",
        description:
          "GAIA creates a recurring Todoist task at month-end to reconcile Stripe payouts with your accounting records so revenue reporting stays accurate.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Stripe to GAIA",
        description:
          "Authenticate your Todoist account and connect your Stripe account to GAIA. GAIA uses Stripe webhooks to receive event notifications in real time.",
      },
      {
        step: "Map Stripe events to Todoist task templates",
        description:
          "Configure which Stripe event types create tasks, what the task title and description templates look like, and which Todoist project and assignee receives each event type.",
      },
      {
        step: "GAIA creates tasks the moment events fire",
        description:
          "When Stripe fires a configured event, GAIA creates the corresponding Todoist task within seconds so your team can act on payment and subscription events immediately.",
      },
    ],
    faqs: [
      {
        question: "Which Stripe events can trigger Todoist task creation?",
        answer:
          "GAIA supports all standard Stripe webhook events including payment_intent.payment_failed, customer.subscription.deleted, charge.dispute.created, invoice.paid, and customer.created.",
      },
      {
        question: "Can I include Stripe customer data in the task description?",
        answer:
          "Yes. GAIA pulls relevant Stripe event data — customer name, email, amount, subscription plan — and inserts it into the task description template so tasks have full context.",
      },
      {
        question: "Is this safe for production Stripe accounts?",
        answer:
          "Yes. GAIA uses read-only webhook listeners for Stripe events and does not modify any Stripe data. It only writes tasks in Todoist.",
      },
      {
        question: "Can different event types go to different Todoist projects?",
        answer:
          "Yes. You can route failed payments to a billing project, cancellations to a customer success project, and disputes to a finance project so tasks reach the right team.",
      },
    ],
  },

  "todoist-airtable": {
    slug: "todoist-airtable",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline:
      "Sync Airtable records with Todoist tasks for structured project tracking",
    metaTitle:
      "Todoist + Airtable Automation - Connect Records and Tasks | GAIA",
    metaDescription:
      "Connect Todoist and Airtable with GAIA. Create Todoist tasks from Airtable records, sync task status back to your database, and keep your project database and personal task list aligned automatically.",
    keywords: [
      "Todoist Airtable integration",
      "Todoist Airtable automation",
      "Airtable record to task",
      "sync Airtable and Todoist",
      "database task management",
      "connect Todoist and Airtable",
    ],
    intro:
      "Airtable is the flexible database that teams use to track projects, content calendars, client lists, and operational workflows. Todoist is where individuals plan and execute their daily work. When a row in an Airtable base represents work that someone needs to do, there is an inevitable gap: the Airtable record captures the data but the individual's Todoist task list is where the actual planning happens. Without a bridge, records and tasks diverge and accountability suffers.\n\nGAIA connects Airtable and Todoist so database records and personal tasks stay synchronized. When an Airtable record is assigned to you or its status changes to In Progress, GAIA creates the corresponding Todoist task so your personal planner reflects your assigned database work. When you complete the Todoist task, GAIA updates the Airtable record status so the shared database reflects real-world progress.\n\nThis integration is ideal for content teams using Airtable as an editorial calendar and Todoist for individual writing tasks, for operations teams where Airtable rows represent deliverables assigned to team members, and for project managers who want a single personal task view that includes both Todoist items and Airtable-tracked responsibilities.",
    useCases: [
      {
        title: "Create Todoist tasks from assigned Airtable records",
        description:
          "When an Airtable record is assigned to you or a status field changes to a trigger value, GAIA creates a Todoist task with the record name, due date, and a link back to the Airtable row.",
      },
      {
        title: "Sync Todoist task completion back to Airtable",
        description:
          "When you mark a linked Todoist task complete, GAIA updates the corresponding Airtable record status to Done so the shared database reflects actual work completion in real time.",
      },
      {
        title: "Editorial calendar task generation",
        description:
          "For content teams with an Airtable publishing calendar, GAIA creates Todoist writing and editing tasks from calendar rows as their scheduled dates approach, complete with deadlines and brief links.",
      },
      {
        title: "Project database milestone tracking",
        description:
          "When an Airtable project record reaches its planned milestone date without a completion status, GAIA creates an overdue alert task in Todoist and flags the record in the base.",
      },
      {
        title: "New record assignment notifications",
        description:
          "When a new row is added to an Airtable base and assigned to a team member, GAIA creates a Todoist task for that person immediately so new work is captured before it is forgotten.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Airtable to GAIA",
        description:
          "Authenticate your Todoist account and connect your Airtable workspace to GAIA. Select the specific bases and views that GAIA should monitor for trigger conditions.",
      },
      {
        step: "Map Airtable fields to Todoist task properties",
        description:
          "Tell GAIA which Airtable field maps to the task title, which date field becomes the Todoist due date, and which status values trigger task creation or completion.",
      },
      {
        step: "GAIA keeps records and tasks synchronized",
        description:
          "GAIA monitors your Airtable base for qualifying record changes and Todoist for task completions, propagating updates between both systems automatically.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA work with multiple Airtable bases simultaneously?",
        answer:
          "Yes. You can connect multiple Airtable bases and map each to a different Todoist project so work from different databases lands in the right task list.",
      },
      {
        question: "Will GAIA sync all records or only those assigned to me?",
        answer:
          "By default GAIA only creates tasks for records assigned to your account. You can optionally configure it to watch an entire view regardless of assignee.",
      },
      {
        question: "Does GAIA support Airtable linked record fields?",
        answer:
          "GAIA can read values from linked record fields and include them in the Todoist task description, but it does not currently create tasks from linked records automatically.",
      },
      {
        question:
          "What happens to the Todoist task if an Airtable record is deleted?",
        answer:
          "GAIA detects the deletion and marks the linked Todoist task as cancelled so your active task list stays clean.",
      },
    ],
  },

  "todoist-loom": {
    slug: "todoist-loom",
    toolA: "Todoist",
    toolASlug: "todoist",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Turn Loom video feedback into Todoist tasks and attach videos to work items",
    metaTitle: "Todoist + Loom Automation - Video Feedback to Tasks | GAIA",
    metaDescription:
      "Connect Todoist and Loom with GAIA. Convert Loom video feedback and comments into Todoist tasks, attach Loom videos to tasks for context, and keep async video reviews tracked and actionable.",
    keywords: [
      "Todoist Loom integration",
      "Todoist Loom automation",
      "Loom feedback to task",
      "video review task tracking",
      "async feedback automation",
      "connect Todoist and Loom",
    ],
    intro:
      "Loom has transformed how teams share feedback and instructions — a short video conveys nuance that a written comment never could. But Loom videos that contain actionable feedback present a tracking challenge: the reviewer records the video, the recipient watches it, and then the specific action items in the video need to make their way into a task manager. Without automation, this handoff requires the viewer to manually create tasks from what they heard, a step that gets skipped when things get busy.\n\nGAIA connects Loom and Todoist to make video feedback automatically actionable. When a Loom video is shared with you, GAIA can transcribe it, extract the action items mentioned, and create Todoist tasks for each. When you create a Todoist task for a piece of work, GAIA can attach the relevant Loom video link so whoever picks up the task has the full video context alongside the task description.\n\nThis integration is particularly useful for design reviewers and product managers who share Loom walkthroughs with action items, for managers who use Loom to delegate work asynchronously, and for teams where async-first communication is the norm and video feedback needs to translate reliably into tracked tasks.",
    useCases: [
      {
        title: "Extract Todoist tasks from Loom video transcripts",
        description:
          "When a Loom video is shared with you, GAIA transcribes it and identifies action items mentioned by the reviewer, creating Todoist tasks for each with the video timestamp referenced.",
      },
      {
        title: "Attach Loom videos to Todoist tasks",
        description:
          "When a Loom video is created for a specific task or project, GAIA attaches the video link to the relevant Todoist task so context is always one click away when work begins.",
      },
      {
        title: "Video review completion tracking",
        description:
          "When a Loom video requires a review response, GAIA creates a Todoist task to watch and respond, with the video link and a deadline based on the review due date.",
      },
      {
        title: "Async delegation follow-up",
        description:
          "When a manager shares a Loom video delegating work, GAIA creates a Todoist task for the recipient with the video link and a suggested due date, ensuring delegated work is formally captured.",
      },
      {
        title: "Design walkthrough action items",
        description:
          "Product managers recording Loom walkthroughs of new features can mention actions by name and GAIA will capture each as a Todoist task assigned to the relevant team member.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Todoist and Loom to GAIA",
        description:
          "Authenticate your Todoist account and connect your Loom workspace to GAIA. Grant GAIA access to your Loom library so it can read shared videos and transcripts.",
      },
      {
        step: "Set your video-to-task rules",
        description:
          "Configure which Loom videos trigger task extraction — all shared videos, only those in specific workspaces, or videos with specific tags. Choose the Todoist project where tasks are created.",
      },
      {
        step: "GAIA turns video feedback into tracked tasks",
        description:
          "When a qualifying Loom video is shared, GAIA processes the transcript, creates tasks for each action item, and attaches the video link so every piece of feedback becomes a trackable work item.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA transcribe Loom videos itself or use Loom's built-in transcription?",
        answer:
          "GAIA uses Loom's built-in auto-transcription when available, falling back to its own transcription for older videos or workspaces without transcription enabled.",
      },
      {
        question:
          "How accurate is the action item extraction from Loom transcripts?",
        answer:
          "GAIA uses language model analysis to identify action items and commitments in transcripts. You can enable a review step where extracted tasks are shown before being saved to Todoist.",
      },
      {
        question:
          "Can GAIA handle Loom videos sent via email links rather than direct shares?",
        answer:
          "Yes. If you forward a Loom video link to GAIA or paste it in a GAIA command, it can process the video and create tasks regardless of how the link was shared.",
      },
      {
        question:
          "Will GAIA create tasks from Loom comments as well as the video content?",
        answer:
          "Yes. GAIA can also read Loom video comments and create Todoist tasks from comment threads, which is useful when reviewers add text feedback alongside the video.",
      },
    ],
  },

  "google-calendar-salesforce": {
    slug: "google-calendar-salesforce",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Sync sales meetings with Salesforce and auto-log CRM activity from your calendar",
    metaTitle:
      "Google Calendar + Salesforce Automation - Sync Meetings and CRM | GAIA",
    metaDescription:
      "Connect Google Calendar and Salesforce with GAIA. Automatically log calendar meetings as Salesforce activities, create follow-up tasks from sales calls, and keep your CRM timeline accurate without manual entry.",
    keywords: [
      "Google Calendar Salesforce integration",
      "Google Calendar Salesforce sync",
      "sales meeting CRM logging",
      "Salesforce activity automation",
      "calendar to CRM sync",
      "connect Google Calendar and Salesforce",
    ],
    intro:
      "Every sales call on your Google Calendar should have a corresponding activity record in Salesforce — but manually logging each meeting after it happens is one of the most resisted tasks in the sales profession. Reps log calls inconsistently, details get forgotten by end of day, and managers lose the pipeline visibility they need to coach effectively. The CRM timeline becomes a fiction rather than an accurate record.\n\nGAIA connects Google Calendar and Salesforce to make CRM logging automatic. When a sales meeting appears on your calendar, GAIA links it to the relevant Salesforce opportunity, contact, or account. When the meeting ends, GAIA creates the activity record with attendees, duration, and a summary derived from any notes you've added. Follow-up tasks from the call land in Salesforce Tasks automatically so the next step is always recorded.\n\nThis integration is designed for account executives who want accurate CRM records without the administrative friction, for sales managers who need consistent pipeline activity data across the team, and for RevOps teams who build reporting on top of Salesforce activity logs that are currently incomplete.",
    useCases: [
      {
        title: "Auto-log calendar meetings as Salesforce activities",
        description:
          "When a Google Calendar meeting with a known contact ends, GAIA creates a Salesforce activity record with the meeting details, duration, and attendees automatically.",
      },
      {
        title: "Pre-meeting Salesforce briefing",
        description:
          "Fifteen minutes before a sales call on Google Calendar, GAIA pulls the contact's recent Salesforce activity, open opportunities, and last interaction date so you walk in fully prepared.",
      },
      {
        title: "Follow-up task creation from sales calls",
        description:
          "After a calendar meeting linked to a Salesforce opportunity, GAIA creates follow-up tasks in Salesforce — send proposal, update stage, schedule next call — based on a configurable template.",
      },
      {
        title: "Opportunity next step updates",
        description:
          "GAIA updates the Next Step field on the linked Salesforce opportunity after each calendar meeting, recording the agreed action so pipeline reviews reflect the latest discussion.",
      },
      {
        title: "Meeting cadence monitoring",
        description:
          "GAIA detects Salesforce opportunities where no Google Calendar meeting has been scheduled in the past 14 days and creates a task to re-engage, preventing deals from stalling silently.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Salesforce to GAIA",
        description:
          "Authenticate your Google account and Salesforce org in GAIA's settings. GAIA uses Salesforce Connected App OAuth and Google Calendar API to read and write both systems.",
      },
      {
        step: "Configure meeting matching and logging rules",
        description:
          "Tell GAIA how to match calendar attendees to Salesforce contacts, which calendar event types should create activity records, and what follow-up task templates to apply.",
      },
      {
        step: "GAIA logs activities and tasks automatically",
        description:
          "After each qualifying calendar event, GAIA creates the Salesforce activity record and any follow-up tasks within minutes of the meeting ending, keeping your CRM current.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA match calendar attendees to Salesforce contacts?",
        answer:
          "GAIA matches by email address. If an attendee's email matches a Salesforce contact or lead record, GAIA links the activity to that record. Unmatched attendees are flagged for manual review.",
      },
      {
        question:
          "Will GAIA log internal meetings as well as external sales calls?",
        answer:
          "You can configure GAIA to log only meetings with external domains, only meetings where a Salesforce contact is an attendee, or all meetings. Internal-only meetings can be excluded.",
      },
      {
        question: "Does this require Salesforce admin access?",
        answer:
          "Individual reps need standard user access with API permissions enabled. For org-wide deployment, a Salesforce admin needs to set up the Connected App.",
      },
      {
        question:
          "Can GAIA update the Salesforce opportunity stage based on the meeting?",
        answer:
          "GAIA can update the stage if you configure a rule — for example, a meeting tagged as 'Demo' advances the opportunity to Demonstration. Stage changes require your approval before they are applied.",
      },
    ],
  },

  "google-calendar-airtable": {
    slug: "google-calendar-airtable",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline:
      "Keep your Airtable project database in sync with Google Calendar events",
    metaTitle:
      "Google Calendar + Airtable Automation - Sync Events and Records | GAIA",
    metaDescription:
      "Connect Google Calendar and Airtable with GAIA. Create Airtable records from calendar events, update event dates when database records change, and keep your project database and schedule aligned.",
    keywords: [
      "Google Calendar Airtable integration",
      "Google Calendar Airtable sync",
      "calendar event to Airtable record",
      "sync Airtable and calendar",
      "project scheduling automation",
      "connect Google Calendar and Airtable",
    ],
    intro:
      "Airtable is a powerful project database, but its built-in calendar view and Google Calendar are two separate things — changes in one don't automatically reflect in the other. Teams end up maintaining dates in both places, leading to scheduling conflicts, missed deadlines, and the constant question of which system has the correct date when they disagree.\n\nGAIA keeps Google Calendar and Airtable synchronized so your project database and your schedule are always telling the same story. When a date field changes in an Airtable record, GAIA updates the corresponding Google Calendar event. When you create a new Google Calendar event for a project milestone, GAIA creates or updates the Airtable record to match. The two systems become a single source of truth for when things happen.\n\nThis integration is particularly useful for content teams who plan publishing schedules in Airtable but need deliverable dates on Google Calendar, for project managers who track milestones in Airtable and want them on a shared calendar for stakeholder visibility, and for event planners who maintain detailed event records in Airtable alongside operational Google Calendar schedules.",
    useCases: [
      {
        title: "Sync Airtable date fields to Google Calendar events",
        description:
          "When a date field in an Airtable record is set or updated, GAIA creates or updates a Google Calendar event so the schedule reflects the latest database values without manual calendar editing.",
      },
      {
        title: "Create Airtable records from Google Calendar events",
        description:
          "When you create a Google Calendar event tagged for a specific project, GAIA creates a corresponding Airtable record with the event title, date, and attendees so the database stays complete.",
      },
      {
        title: "Content publishing schedule sync",
        description:
          "For editorial teams with a content calendar in Airtable, GAIA syncs publish dates to Google Calendar so writers, editors, and social media managers all see deadlines on their shared calendar.",
      },
      {
        title: "Project milestone visibility",
        description:
          "GAIA mirrors Airtable project milestone dates onto a shared Google Calendar so stakeholders who don't use Airtable can see upcoming deliverables in the calendar they already check.",
      },
      {
        title: "Event prep record creation",
        description:
          "When a new event is added to Google Calendar, GAIA creates an Airtable record in your event planning base, pre-filled with event name, date, and attendee count, ready for the team to add logistics details.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Airtable to GAIA",
        description:
          "Authenticate your Google account and Airtable workspace in GAIA's settings. Select the Airtable bases and Google Calendars you want to keep in sync.",
      },
      {
        step: "Map Airtable fields to calendar event properties",
        description:
          "Define which Airtable date fields correspond to event start times, which text fields become event titles, and which views or tables GAIA should monitor for changes.",
      },
      {
        step: "GAIA keeps database and calendar synchronized",
        description:
          "GAIA monitors both platforms for changes and propagates updates in real time, ensuring Airtable dates and Google Calendar events always match.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync multiple Airtable tables to different Google Calendars?",
        answer:
          "Yes. You can map each Airtable table or view to a different Google Calendar — marketing milestones to the marketing calendar, product releases to the engineering calendar.",
      },
      {
        question:
          "What happens if I delete a Google Calendar event that was created from Airtable?",
        answer:
          "GAIA detects the deletion and can either clear the date field in the Airtable record or create a note flagging that the calendar event was removed, depending on your preference.",
      },
      {
        question:
          "Does GAIA sync recurring Airtable records to recurring calendar events?",
        answer:
          "GAIA can create individual calendar events for each recurring record instance. True Google Calendar recurrence rules require a one-time setup rather than automatic conversion.",
      },
      {
        question:
          "Can Airtable form submissions automatically create calendar events?",
        answer:
          "Yes. If an Airtable form submission creates a record with a date field, GAIA can pick up that record and create the corresponding Google Calendar event immediately.",
      },
    ],
  },

  "google-calendar-loom": {
    slug: "google-calendar-loom",
    toolA: "Google Calendar",
    toolASlug: "google-calendar",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Record Loom video briefs for upcoming meetings and share recaps automatically",
    metaTitle:
      "Google Calendar + Loom Automation - Meeting Briefs and Video Recaps | GAIA",
    metaDescription:
      "Connect Google Calendar and Loom with GAIA. Get reminded to record Loom pre-meeting briefs, automatically share post-meeting Loom recaps with attendees, and reduce synchronous meeting load.",
    keywords: [
      "Google Calendar Loom integration",
      "Google Calendar Loom automation",
      "pre-meeting video brief",
      "meeting recap Loom",
      "async meeting workflow",
      "connect Google Calendar and Loom",
    ],
    intro:
      "The best meetings start with shared context and end with a clear record — but most meetings do neither. Attendees arrive without reviewing relevant background, and decisions made during the call are poorly documented afterward. Loom offers a simple way to record context-setting briefs before meetings and concise recaps after them, but without automation, creating and sharing those videos requires discipline that's hard to maintain across a full calendar.\n\nGAIA connects Google Calendar and Loom to build async context into every meeting automatically. When a meeting appears on your calendar, GAIA can remind you to record a Loom brief so attendees arrive informed. After the meeting, GAIA prompts you to record a recap and then shares the Loom link with all attendees directly, creating a searchable async record without manual distribution.\n\nThis integration is particularly valuable for distributed teams across time zones where pre-read context reduces the need for long synchronous meetings, for managers who run recurring check-ins where a brief async update could replace a full meeting, and for teams committed to async-first communication who want their calendar workflows to reflect that principle.",
    useCases: [
      {
        title: "Pre-meeting Loom brief reminders",
        description:
          "The day before a scheduled Google Calendar meeting, GAIA reminds you to record a short Loom brief with the agenda and context so attendees can prepare and the meeting itself can focus on decisions.",
      },
      {
        title: "Post-meeting recap video prompts",
        description:
          "Within minutes of a Google Calendar meeting ending, GAIA prompts you to record a brief Loom recap summarizing decisions and next steps, while the discussion is still fresh.",
      },
      {
        title: "Auto-share Loom recaps with attendees",
        description:
          "Once a post-meeting Loom is recorded, GAIA shares the video link with all Google Calendar attendees via email or calendar event comment so the record reaches everyone automatically.",
      },
      {
        title: "Replace recurring meetings with async Loom updates",
        description:
          "For recurring Google Calendar meetings, GAIA can suggest replacing selected occurrences with a Loom update when the agenda doesn't require live discussion, reducing meeting load.",
      },
      {
        title: "Onboarding video library from calendar events",
        description:
          "GAIA tracks Loom videos recorded for recurring training or onboarding calendar events and organizes them into a Loom folder so new team members can access the full video library.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Google Calendar and Loom to GAIA",
        description:
          "Authenticate your Google account and your Loom workspace in GAIA's settings. Grant GAIA calendar read access and Loom library access so it can track events and videos.",
      },
      {
        step: "Set your meeting brief and recap preferences",
        description:
          "Configure which calendar events should trigger brief reminders and recap prompts, how far in advance to send the reminder, and where recorded Looms should be filed.",
      },
      {
        step: "GAIA automates the async meeting loop",
        description:
          "GAIA monitors your calendar for upcoming and completed meetings, sends reminders at the right time, and shares recorded Loom videos with attendees automatically.",
      },
    ],
    faqs: [
      {
        question: "Can I choose which meeting types trigger Loom reminders?",
        answer:
          "Yes. You can configure GAIA to trigger reminders only for external meetings, only for meetings above a certain duration, or only for events with specific keywords in the title.",
      },
      {
        question:
          "Does GAIA share the Loom link via calendar event updates or email?",
        answer:
          "You can choose either method. GAIA can add the Loom link as a comment to the Google Calendar event, send it via email to attendees, or both.",
      },
      {
        question: "What if I don't record a Loom after a meeting?",
        answer:
          "GAIA sends one reminder prompt and then stops. It does not send repeated reminders for the same meeting if you choose not to record.",
      },
      {
        question:
          "Can GAIA help schedule a meeting to replace a Loom that needs live discussion?",
        answer:
          "Yes. If you record a Loom that prompts follow-up questions requiring a live call, you can ask GAIA to find a time on Google Calendar and schedule a meeting with the relevant attendees.",
      },
    ],
  },
};
