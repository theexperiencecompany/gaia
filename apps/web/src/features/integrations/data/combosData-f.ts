import type { IntegrationCombo } from "./combosData";

export const combosBatchF: Record<string, IntegrationCombo> = {
  "asana-clickup": {
    slug: "asana-clickup",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline: "Bridge Asana and ClickUp when teams use both platforms",
    metaTitle:
      "Asana + ClickUp Automation - Sync Tasks Across Both Platforms | GAIA",
    metaDescription:
      "Stop duplicating work across Asana and ClickUp. GAIA keeps tasks, statuses, and deadlines in sync so every team member sees accurate project data regardless of which tool they prefer.",
    keywords: [
      "Asana ClickUp integration",
      "Asana ClickUp sync",
      "connect Asana and ClickUp",
      "Asana ClickUp automation",
      "cross-platform project management",
      "task sync Asana ClickUp",
    ],
    intro:
      "Many growing organizations run Asana and ClickUp simultaneously — one team adopted Asana early, another migrated to ClickUp, and now both coexist without talking to each other. The result is duplicated task entry, mismatched statuses, and project leads who spend hours reconciling two separate sources of truth.\n\nGAIA eliminates the manual overhead of managing projects across both platforms. When a task is created or updated in Asana, GAIA mirrors the change in ClickUp and vice versa, keeping assignees, due dates, and completion statuses consistent. Teams can continue using their preferred tool while leadership gets a consolidated view of project health.\n\nThis integration is especially valuable during platform migrations, when departments have different tool preferences, or when client-facing projects need to live in one system while internal execution happens in another.",
    useCases: [
      {
        title: "Mirror task creation across platforms",
        description:
          "When a new task is created in Asana with an assigned team member and due date, GAIA automatically creates a corresponding task in ClickUp so both platforms reflect the same work without manual duplication.",
      },
      {
        title: "Sync task completion status bidirectionally",
        description:
          "When a task is marked complete in either Asana or ClickUp, GAIA updates the counterpart record immediately, preventing stale open items from cluttering project views in either tool.",
      },
      {
        title: "Unified cross-team reporting",
        description:
          "GAIA aggregates task data from both Asana and ClickUp to generate a single weekly status report, giving leadership consistent project visibility without requiring everyone to switch tools.",
      },
      {
        title: "Escalate blockers between systems",
        description:
          "When a task in ClickUp is flagged as blocked, GAIA creates a dependency flag on the linked Asana task so project managers in both systems are aware and can intervene quickly.",
      },
      {
        title: "Deadline drift alerts",
        description:
          "GAIA monitors due dates across both platforms and alerts the team when a task's deadline in one system does not match the other, preventing schedule confusion before it becomes a delivery issue.",
      },
    ],
    howItWorks: [
      {
        step: "Connect both workspaces to GAIA",
        description:
          "Authorize GAIA to access your Asana workspace and your ClickUp workspace. GAIA maps projects and lists between the two platforms so it knows which items correspond to each other.",
      },
      {
        step: "Define sync rules and field mappings",
        description:
          "Tell GAIA which Asana projects should sync with which ClickUp lists, and configure how fields map between them — assignees, priorities, due dates, and custom fields.",
      },
      {
        step: "GAIA keeps both platforms current",
        description:
          "GAIA monitors both systems for changes and propagates updates bidirectionally so teams in each platform always see current, accurate task data.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA handle a one-time migration from Asana to ClickUp?",
        answer:
          "Yes. GAIA can bulk-read all tasks from an Asana project and create corresponding tasks in a ClickUp list, preserving titles, descriptions, assignees, and due dates. After migration you can turn off the sync or keep it active for a transition period.",
      },
      {
        question:
          "What happens if a task is edited in both platforms simultaneously?",
        answer:
          "GAIA applies a last-write-wins rule by default and flags the conflict in a designated Slack channel or email digest so a human can review. You can also configure one platform to always be the system of record.",
      },
      {
        question:
          "Do custom fields in ClickUp sync with custom fields in Asana?",
        answer:
          "GAIA supports mapping custom fields by name or type. If field names differ between platforms, you can define explicit mappings during setup. Fields without a counterpart are logged but not discarded.",
      },
    ],
  },

  "asana-trello": {
    slug: "asana-trello",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline: "Migrate or sync tasks between Asana projects and Trello boards",
    metaTitle:
      "Asana + Trello Automation - Sync Tasks and Boards Effortlessly | GAIA",
    metaDescription:
      "Connect Asana projects and Trello boards with GAIA. Automatically sync tasks, move cards when statuses change, and keep both platforms up to date without manual data entry.",
    keywords: [
      "Asana Trello integration",
      "Asana Trello sync",
      "migrate Asana to Trello",
      "connect Asana and Trello",
      "Asana Trello automation",
      "task management sync",
    ],
    intro:
      "Asana and Trello approach project management differently — Asana with structured task hierarchies and timelines, Trello with visual Kanban boards — but many teams rely on both. Client-facing work might live in Trello for its simplicity while internal project tracking uses Asana's more powerful features. Without automation, teams must update both tools manually, creating delays and inconsistencies.\n\nGAIA connects Asana and Trello so tasks flow between them automatically. New Asana tasks can become Trello cards, Trello card movements can update Asana task statuses, and deadlines stay consistent across both platforms. Teams can collaborate in their preferred interface while the underlying data stays unified.\n\nThis integration is ideal for agencies managing client boards in Trello while tracking internal project timelines in Asana, and for teams transitioning between the two tools who need a reliable migration path.",
    useCases: [
      {
        title: "Create Trello cards from new Asana tasks",
        description:
          "When a task is added to an Asana project, GAIA automatically creates a corresponding Trello card in the appropriate list, complete with the task title, description, due date, and assignee.",
      },
      {
        title: "Sync Trello card moves back to Asana",
        description:
          "When a Trello card moves from In Progress to Done, GAIA marks the linked Asana task as complete, keeping both tools consistent without requiring team members to update two systems.",
      },
      {
        title: "Bulk migrate projects from Asana to Trello",
        description:
          "GAIA reads all tasks in an Asana project and creates a fully populated Trello board with lists mapped to Asana sections, making platform transitions seamless and data-complete.",
      },
      {
        title: "Deadline synchronization",
        description:
          "GAIA monitors due dates in both platforms and alerts the team when dates diverge, ensuring that deadline changes made in one tool are reflected in the other before they cause scheduling conflicts.",
      },
      {
        title: "Client board updates from internal tracking",
        description:
          "When internal Asana milestones are reached, GAIA updates the corresponding Trello card in the client-facing board, giving clients real-time progress visibility without exposing internal project details.",
      },
    ],
    howItWorks: [
      {
        step: "Authorize Asana and Trello in GAIA",
        description:
          "Connect your Asana workspace and Trello account to GAIA. GAIA maps Asana projects to Trello boards and Asana sections to Trello lists based on your configuration.",
      },
      {
        step: "Set sync direction and field mappings",
        description:
          "Choose whether to sync one-way or bidirectionally. Configure which fields carry over — title, description, due date, assignee, labels — between the two platforms.",
      },
      {
        step: "GAIA automates the rest",
        description:
          "Once configured, GAIA monitors both platforms and propagates changes automatically, keeping tasks and cards consistent so your team always works from accurate data.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync Asana subtasks to Trello checklists?",
        answer:
          "Yes. GAIA can convert Asana subtasks into Trello card checklists, preserving the hierarchical structure of your work items even though Trello's data model differs from Asana's.",
      },
      {
        question: "What happens to Asana custom fields when syncing to Trello?",
        answer:
          "Asana custom fields that have a Trello equivalent are mapped automatically. Fields without a direct counterpart are appended to the Trello card description so no information is lost.",
      },
      {
        question:
          "Is this suitable for a permanent sync or just a one-time migration?",
        answer:
          "Both. GAIA supports ongoing bidirectional sync for teams running both platforms in parallel, as well as one-time migration jobs for teams moving from Asana to Trello or vice versa.",
      },
    ],
  },

  "asana-linear": {
    slug: "asana-linear",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline:
      "Sync product management in Asana with engineering execution in Linear",
    metaTitle:
      "Asana + Linear Automation - Bridge Product and Engineering | GAIA",
    metaDescription:
      "Keep product and engineering aligned with GAIA. Sync Asana project milestones to Linear issues, reflect engineering progress back to Asana, and eliminate status meetings spent reconciling two tools.",
    keywords: [
      "Asana Linear integration",
      "Asana Linear sync",
      "product engineering alignment",
      "connect Asana and Linear",
      "Asana Linear automation",
      "project management engineering sync",
    ],
    intro:
      "Product teams often live in Asana for its project planning capabilities while engineering teams prefer Linear for its speed and developer-centric workflow. The gap between the two creates a constant synchronization problem — product managers manually copy specs into Linear issues, engineers close Linear issues but Asana still shows tasks as open, and leadership lacks a unified view of what is shipped versus what is planned.\n\nGAIA bridges Asana and Linear so product decisions automatically flow into engineering backlogs and engineering progress automatically surfaces in product timelines. When a product manager marks an Asana task as ready for engineering, GAIA creates the corresponding Linear issue with full context. When engineers close a Linear issue, GAIA updates the Asana task status so the product roadmap stays accurate.\n\nThis integration is built for product-engineering teams who want to keep their preferred tools while eliminating the coordination overhead that comes from running two disconnected systems.",
    useCases: [
      {
        title: "Create Linear issues from Asana tasks",
        description:
          "When a product manager marks an Asana task as Ready for Engineering, GAIA automatically creates a Linear issue in the appropriate team's backlog with the task title, description, and any attached specs.",
      },
      {
        title: "Reflect engineering progress in product timelines",
        description:
          "When a Linear issue moves to In Progress or Done, GAIA updates the corresponding Asana task status so product managers see accurate engineering progress without needing to check Linear directly.",
      },
      {
        title: "Sync sprint cycles to Asana milestones",
        description:
          "GAIA maps Linear sprint timelines to Asana milestone dates, giving the product team visibility into engineering cadences and ensuring release planning reflects what engineering can realistically deliver.",
      },
      {
        title: "Bug escalation from Linear to Asana",
        description:
          "When a high-priority bug is filed in Linear, GAIA creates a corresponding Asana task for the product team, prompting them to assess customer impact and reprioritize the roadmap if necessary.",
      },
      {
        title: "Blocked issue alerts across teams",
        description:
          "When a Linear issue is blocked waiting on product decisions, GAIA creates an Asana task for the responsible product manager with context and a deadline, preventing engineering from stalling silently.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and Linear to GAIA",
        description:
          "Authorize GAIA to access your Asana workspace and Linear organization. Configure which Asana projects map to which Linear teams and how statuses correspond between the two systems.",
      },
      {
        step: "Define trigger conditions and field mappings",
        description:
          "Set the conditions that trigger syncs — such as an Asana task reaching a specific section or a Linear issue changing state — and map fields like priority, assignee, and description between platforms.",
      },
      {
        step: "GAIA keeps product and engineering aligned",
        description:
          "GAIA monitors both platforms continuously and propagates changes in real time, so product managers and engineers always work from a shared, accurate understanding of project status.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync Asana project sections to Linear cycles?",
        answer:
          "Yes. GAIA can map Asana project sections to Linear cycles or projects, and update issue assignments as tasks move through your Asana workflow stages.",
      },
      {
        question:
          "What if the same feature is tracked differently in each tool?",
        answer:
          "You can define explicit mappings between Asana tasks and Linear issues by linking them manually the first time. After that, GAIA maintains the link and syncs updates automatically.",
      },
      {
        question: "Does GAIA sync Linear comments back to Asana?",
        answer:
          "GAIA can append a summary of Linear comment activity to the Asana task description or post it as a task comment, keeping product managers informed of engineering discussions without requiring Linear access.",
      },
    ],
  },

  "asana-figma": {
    slug: "asana-figma",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline: "Link Figma design deliverables directly to Asana project tasks",
    metaTitle:
      "Asana + Figma Automation - Connect Design Deliverables to Project Tasks | GAIA",
    metaDescription:
      "Bridge design and project management with GAIA. Automatically attach Figma files to Asana tasks, notify teams when designs are ready for review, and track design approval status without leaving Asana.",
    keywords: [
      "Asana Figma integration",
      "Asana Figma automation",
      "design project management",
      "connect Asana and Figma",
      "Figma design handoff Asana",
      "design review workflow automation",
    ],
    intro:
      "Design and project management workflows are tightly coupled but typically tracked in separate tools. Designers work in Figma while project managers track deliverables in Asana, and the handoff between them involves manual Figma link sharing, copy-pasted feedback, and status updates communicated through Slack threads or email chains.\n\nGAIA connects Asana and Figma so design progress and project timelines stay synchronized. When a designer marks a Figma file ready for review, GAIA can automatically update the linked Asana task and notify the relevant stakeholders. When an Asana task enters the design phase, GAIA can create a Figma file stub and link it back to the task so there is always a single source of truth for design deliverables.\n\nThis integration reduces coordination overhead between design and product teams, accelerates feedback loops, and ensures that design handoffs happen at the right stage of the project rather than after deadlines have already slipped.",
    useCases: [
      {
        title: "Auto-attach Figma files to Asana tasks",
        description:
          "When a new Figma file is created for a project, GAIA automatically attaches the Figma link to the corresponding Asana task so team members always know where to find the latest design assets.",
      },
      {
        title: "Design-ready notifications in Asana",
        description:
          "When a designer updates a Figma file to a Ready for Review status, GAIA updates the linked Asana task stage and notifies the assigned reviewer so feedback begins without a separate Slack message.",
      },
      {
        title: "Track design approval status",
        description:
          "GAIA monitors Figma comment activity and reflects approval or revision requests as Asana task comments, giving project managers a complete view of the design review lifecycle within their existing tool.",
      },
      {
        title: "Trigger design tasks from Asana milestones",
        description:
          "When an Asana milestone is reached — such as a feature spec being approved — GAIA creates the corresponding design task in Asana and initializes a Figma file, ensuring design work begins at the right moment.",
      },
      {
        title: "Design handoff to development",
        description:
          "When a Figma design is marked approved, GAIA transitions the Asana task to a development-ready section and notifies the engineering assignee with the Figma link, making handoffs automatic and traceable.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and Figma to GAIA",
        description:
          "Authorize GAIA to access your Asana workspace and Figma account. Configure which Asana projects correspond to which Figma teams or projects.",
      },
      {
        step: "Map design stages to Asana task sections",
        description:
          "Define how Figma file statuses — In Progress, Ready for Review, Approved — map to Asana task sections or custom fields so status changes flow automatically.",
      },
      {
        step: "GAIA links design and project work",
        description:
          "GAIA monitors both platforms and propagates status changes, file links, and notifications in real time, so design progress is always visible within Asana.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA attach specific Figma frames rather than entire files?",
        answer:
          "Yes. You can configure GAIA to attach specific Figma frame or component links to Asana tasks, making it easier for reviewers to navigate directly to the relevant part of a complex design file.",
      },
      {
        question: "Does GAIA sync Figma comments to Asana?",
        answer:
          "GAIA can summarize Figma comment threads and post them as Asana task comments, giving project managers visibility into design feedback without requiring a Figma account.",
      },
      {
        question:
          "What happens when a Figma file is updated after the design is approved?",
        answer:
          "GAIA can detect Figma file edits after approval and reopen the Asana review task or notify the team, ensuring that post-approval changes are not silently deployed without another review cycle.",
      },
    ],
  },

  "asana-discord": {
    slug: "asana-discord",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline: "Post Asana task updates to Discord team channels automatically",
    metaTitle:
      "Asana + Discord Automation - Project Updates in Your Discord Server | GAIA",
    metaDescription:
      "Keep your Discord community and team informed with GAIA. Automatically post Asana task completions, new assignments, and milestone updates to Discord channels so everyone stays aligned.",
    keywords: [
      "Asana Discord integration",
      "Asana Discord automation",
      "project updates Discord",
      "connect Asana and Discord",
      "Asana Discord notifications",
      "team project management Discord",
    ],
    intro:
      "Teams that collaborate on Discord need project updates to come to them rather than requiring constant tab-switching to Asana. When task completions, new assignments, and missed deadlines live only inside Asana, Discord-first teams miss critical context and fall out of sync with project progress.\n\nGAIA connects Asana and Discord so the project events that matter most are automatically surfaced in the right Discord channels. Task completions appear in team channels, new assignments notify individuals in DMs, and milestone achievements trigger announcements to the whole server. Teams that live in Discord can stay fully informed about Asana project health without leaving their primary communication platform.\n\nThis integration works especially well for developer communities, gaming studios, and remote-first companies that use Discord as their primary team hub and Asana for structured project management.",
    useCases: [
      {
        title: "Post task completions to team channels",
        description:
          "When a task is marked complete in Asana, GAIA posts a formatted update to the designated Discord channel, keeping the team informed of progress and giving completions the visibility they deserve.",
      },
      {
        title: "Notify assignees of new tasks via Discord DM",
        description:
          "When a task is assigned in Asana, GAIA sends a direct message to the assignee on Discord with the task title, description, due date, and a link to Asana, ensuring immediate awareness without email.",
      },
      {
        title: "Announce project milestones",
        description:
          "When an Asana milestone is reached, GAIA posts a milestone announcement to the relevant Discord channel or server announcement channel, giving the whole team visibility into major project achievements.",
      },
      {
        title: "Overdue task alerts",
        description:
          "GAIA checks Asana daily for overdue tasks and posts a digest to the project manager's Discord DM or a dedicated alerts channel, ensuring nothing slips through without notice.",
      },
      {
        title: "Daily standup digest",
        description:
          "Each morning GAIA posts a structured standup digest to a Discord channel listing tasks due today, tasks completed yesterday, and any blockers flagged in Asana, replacing manual standup preparation.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and Discord to GAIA",
        description:
          "Authorize GAIA to access your Asana workspace and your Discord server. Configure which Asana projects or teams map to which Discord channels.",
      },
      {
        step: "Choose which events trigger Discord messages",
        description:
          "Select the Asana events — task creation, assignment, completion, overdue, milestone — that should generate Discord notifications, and specify the target channel or user for each event type.",
      },
      {
        step: "GAIA delivers real-time project updates",
        description:
          "GAIA monitors Asana continuously and posts formatted notifications to Discord as events occur, keeping your team informed without anyone checking Asana manually.",
      },
    ],
    faqs: [
      {
        question: "Can I create Asana tasks from Discord messages?",
        answer:
          "Yes. You can mention GAIA in a Discord message and ask it to create an Asana task with a specific title, assignee, and due date. GAIA will confirm the task creation and post the Asana link back to the channel.",
      },
      {
        question:
          "Can GAIA post to multiple Discord channels for different Asana projects?",
        answer:
          "Yes. You can configure per-project channel mappings so that updates from different Asana projects route to different Discord channels, keeping notifications organized and relevant.",
      },
      {
        question: "Will GAIA create noise by posting every small Asana update?",
        answer:
          "No. You have full control over which event types generate Discord posts. Most teams configure GAIA to post only completions, milestone events, and overdue alerts to keep channels signal-rich.",
      },
    ],
  },

  "asana-drive": {
    slug: "asana-drive",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach Drive documents to Asana tasks and organize deliverables automatically",
    metaTitle:
      "Asana + Google Drive Automation - Link Documents to Project Tasks | GAIA",
    metaDescription:
      "Connect Asana and Google Drive with GAIA. Automatically attach Drive files to Asana tasks, create project folders when projects launch, and keep all deliverables organized and accessible.",
    keywords: [
      "Asana Google Drive integration",
      "Asana Drive automation",
      "attach files Asana tasks",
      "connect Asana and Google Drive",
      "project document management",
      "Asana Drive workflow",
    ],
    intro:
      "Project tasks in Asana rarely exist in isolation — they reference briefs, specs, reports, and deliverables stored in Google Drive. Without automation, team members spend time hunting through Drive folders for the right document, or they attach stale file versions to Asana tasks because the link was shared months ago and the file has since moved.\n\nGAIA connects Asana and Google Drive so documents are always where you expect them. When a new Asana project launches, GAIA creates a corresponding Drive folder with the right structure. As tasks progress, GAIA attaches the relevant Drive documents automatically. When a deliverable is updated in Drive, GAIA notifies the Asana task assignee so reviews happen promptly.\n\nThis integration is essential for content teams, marketing agencies, and operations departments that rely on Google Drive as their document store and Asana as their project management layer.",
    useCases: [
      {
        title: "Create Drive project folders from Asana projects",
        description:
          "When a new project is created in Asana, GAIA automatically creates a structured Google Drive folder with subfolders for briefs, deliverables, and references, and attaches the folder link to the Asana project.",
      },
      {
        title: "Auto-attach Drive files to Asana tasks",
        description:
          "When a file is added to a project folder in Drive, GAIA attaches it to the corresponding Asana task based on naming conventions or folder structure, eliminating manual link sharing.",
      },
      {
        title: "Notify assignees when deliverables are updated",
        description:
          "When a Drive document linked to an Asana task is edited, GAIA posts a comment on the Asana task notifying the assignee that the file has been updated, prompting timely review.",
      },
      {
        title: "Archive completed project documents",
        description:
          "When an Asana project is marked complete, GAIA moves the associated Drive files to an archive folder and records the final document links in the Asana project description for future reference.",
      },
      {
        title: "Generate task briefs from Drive templates",
        description:
          "When an Asana task is created for a recurring deliverable type, GAIA creates a Drive document from the appropriate template, pre-fills it with task metadata, and attaches it to the task automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Authorize Asana and Google Drive in GAIA",
        description:
          "Connect your Asana workspace and Google Drive account to GAIA. Specify the root Drive folder where project folders should be created and the Asana projects to monitor.",
      },
      {
        step: "Configure folder structure and attachment rules",
        description:
          "Define the Drive folder template for new projects and the rules GAIA uses to match Drive files to Asana tasks — by file name pattern, subfolder, or task custom field.",
      },
      {
        step: "GAIA manages document organization automatically",
        description:
          "GAIA monitors both Asana and Drive for changes, creating folders, attaching files, and posting notifications so your team always finds the right document attached to the right task.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA attach a specific Drive file to an Asana task on demand?",
        answer:
          "Yes. Ask GAIA to find a specific Drive file by name and attach it to an Asana task. GAIA searches Drive, retrieves the file, and adds the attachment to the task.",
      },
      {
        question:
          "Does GAIA create one Drive folder per Asana project or per task?",
        answer:
          "By default, GAIA creates one Drive folder per Asana project with subfolders for major task groups. You can also configure per-task document creation for high-volume or template-driven workflows.",
      },
      {
        question: "What happens to Drive files if an Asana project is deleted?",
        answer:
          "GAIA does not delete Drive files when an Asana project is removed. It can optionally move the files to an archive folder and log the action so documents are preserved for compliance or reference purposes.",
      },
    ],
  },

  "asana-zoom": {
    slug: "asana-zoom",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline:
      "Schedule project kickoffs from Asana milestones and post Zoom summaries to tasks",
    metaTitle:
      "Asana + Zoom Automation - Connect Project Milestones to Video Meetings | GAIA",
    metaDescription:
      "Automate Asana and Zoom with GAIA. Schedule Zoom calls when Asana milestones are reached, post meeting summaries to tasks, and create follow-up action items without leaving your project management tool.",
    keywords: [
      "Asana Zoom integration",
      "Asana Zoom automation",
      "project meeting automation",
      "connect Asana and Zoom",
      "Zoom meeting Asana tasks",
      "project kickoff scheduling",
    ],
    intro:
      "Project milestones in Asana often trigger the need for a team meeting — a kickoff call when a project launches, a review meeting when a phase completes, or a retrospective when a milestone is missed. Scheduling these meetings manually, then manually copying action items from the Zoom call back into Asana, creates friction and delays that compound across every project.\n\nGAIA connects Asana and Zoom so project events automatically trigger the right meetings and meeting outcomes automatically flow back into project tasks. When an Asana milestone is reached, GAIA schedules the appropriate Zoom call and invites the right participants. When the call ends, GAIA posts the meeting summary and extracts action items as new Asana tasks, keeping your project moving without manual follow-up.\n\nThis integration is valuable for project managers who run recurring milestone reviews and for teams that rely on Zoom for collaboration but need meeting outcomes to live inside Asana where work actually gets tracked.",
    useCases: [
      {
        title: "Auto-schedule kickoff calls from project creation",
        description:
          "When a new Asana project is created, GAIA schedules a Zoom kickoff call with all project members, sends calendar invites, and attaches the meeting link to the Asana project for easy access.",
      },
      {
        title: "Trigger milestone review meetings automatically",
        description:
          "When an Asana milestone is marked complete, GAIA schedules a Zoom review meeting with the relevant stakeholders within a configurable window, ensuring reviews happen promptly without manual scheduling.",
      },
      {
        title: "Post Zoom meeting summaries to Asana tasks",
        description:
          "After a Zoom call linked to an Asana project, GAIA generates a meeting summary and posts it as a comment on the relevant Asana task or project, creating a permanent record of what was discussed.",
      },
      {
        title: "Create Asana tasks from Zoom action items",
        description:
          "GAIA analyzes Zoom meeting transcripts for action items and automatically creates corresponding Asana tasks with assignees, descriptions, and due dates derived from what was agreed during the call.",
      },
      {
        title: "Overdue project escalation calls",
        description:
          "When a project in Asana is overdue by a configurable threshold, GAIA automatically schedules an urgent Zoom call with the project manager and key stakeholders to diagnose and resolve the delay.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and Zoom to GAIA",
        description:
          "Authorize GAIA to access your Asana workspace and Zoom account. Link your calendar so GAIA can schedule meetings at times that work for all participants.",
      },
      {
        step: "Configure milestone-to-meeting triggers",
        description:
          "Define which Asana milestones or project events should trigger Zoom meetings, who should be invited, and how soon after the milestone the meeting should be scheduled.",
      },
      {
        step: "GAIA schedules meetings and captures outcomes",
        description:
          "GAIA monitors Asana for milestone events, schedules the appropriate Zoom calls, and after each meeting posts summaries and action items back to Asana automatically.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA schedule Zoom calls from Asana task comments?",
        answer:
          "Yes. Mention GAIA in an Asana task comment and ask it to schedule a Zoom meeting for the task assignees. GAIA checks availability and sends calendar invites with the Zoom link.",
      },
      {
        question:
          "Does GAIA require Zoom transcription to be enabled for meeting summaries?",
        answer:
          "Yes. Zoom meeting summaries rely on Zoom's transcription feature. GAIA accesses the transcript after the meeting ends and generates a structured summary posted to the relevant Asana task.",
      },
      {
        question:
          "Can GAIA create recurring Zoom meetings for ongoing Asana projects?",
        answer:
          "Yes. For long-running projects, GAIA can schedule recurring Zoom standups or review meetings based on Asana sprint cycles or project phase timelines, with participants updated as the team changes.",
      },
    ],
  },

  "asana-salesforce": {
    slug: "asana-salesforce",
    toolA: "Asana",
    toolASlug: "asana",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Link client project tasks in Asana to Salesforce opportunities and accounts",
    metaTitle:
      "Asana + Salesforce Automation - Connect Project Delivery to CRM | GAIA",
    metaDescription:
      "Bridge project management and sales with GAIA. Automatically create Asana projects from Salesforce opportunities, sync delivery milestones to CRM records, and give account teams full visibility into project health.",
    keywords: [
      "Asana Salesforce integration",
      "Asana Salesforce automation",
      "CRM project management integration",
      "connect Asana and Salesforce",
      "Salesforce Asana sync",
      "client project CRM automation",
    ],
    intro:
      "Sales teams close deals in Salesforce while delivery teams execute projects in Asana, but the two systems rarely communicate. Account managers lack visibility into project delivery status without asking the delivery team directly. Delivery teams lack the account context that lives in Salesforce. The result is a gap between what was sold and what is being delivered, with both teams working from incomplete information.\n\nGAIA bridges Asana and Salesforce so project delivery and client relationship management work together seamlessly. When a Salesforce opportunity closes, GAIA automatically creates an Asana project with the right structure and assigns the delivery team. As project milestones are reached, GAIA updates the Salesforce account record so account managers always know where delivery stands without interrupting the project team.\n\nThis integration is critical for professional services firms, SaaS companies with implementation teams, and agencies that need tight alignment between sales commitments and project delivery.",
    useCases: [
      {
        title: "Create Asana projects from closed Salesforce opportunities",
        description:
          "When a Salesforce opportunity reaches Closed Won, GAIA automatically creates a corresponding Asana project, assigns the delivery team, and populates tasks based on the contracted scope of work.",
      },
      {
        title: "Sync project milestones to Salesforce account records",
        description:
          "When Asana milestones are completed, GAIA updates the associated Salesforce account with delivery status notes, giving account managers real-time project health visibility inside their CRM.",
      },
      {
        title: "Escalate at-risk projects to account owners",
        description:
          "When a project in Asana is flagged as at-risk or significantly overdue, GAIA creates a Salesforce task for the account owner to initiate a client conversation before the relationship is affected.",
      },
      {
        title: "Log delivery milestones as Salesforce activities",
        description:
          "Key Asana project events — phase completions, go-live milestones, issue resolutions — are automatically logged as Salesforce activity records, building a complete client history without manual data entry.",
      },
      {
        title: "Upsell triggers from project completion",
        description:
          "When an Asana project is marked complete, GAIA creates a Salesforce follow-up task for the account manager to explore renewal or upsell opportunities while the client relationship is at its strongest.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Asana and Salesforce to GAIA",
        description:
          "Authorize GAIA to access your Asana workspace and Salesforce organization. Map Salesforce opportunity fields to Asana project fields so data flows accurately between systems.",
      },
      {
        step: "Configure triggers and account mappings",
        description:
          "Define which Salesforce opportunity stages trigger Asana project creation, which Asana milestone events update Salesforce records, and how accounts are linked to projects.",
      },
      {
        step: "GAIA keeps delivery and CRM in sync",
        description:
          "GAIA monitors both platforms and propagates relevant events bidirectionally, ensuring sales and delivery teams always share an accurate, up-to-date view of each client engagement.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create different Asana project templates based on Salesforce opportunity type?",
        answer:
          "Yes. You can configure GAIA to select Asana project templates based on Salesforce fields such as product line, contract value, or opportunity type, ensuring each project starts with the right task structure.",
      },
      {
        question:
          "How does GAIA handle Salesforce accounts with multiple active projects?",
        answer:
          "GAIA links each Asana project to the specific Salesforce opportunity that generated it. Account-level summaries aggregate all linked projects so account managers see a complete delivery picture.",
      },
      {
        question:
          "Can GAIA sync Asana project budgets to Salesforce opportunity values?",
        answer:
          "GAIA can read contract value from Salesforce and populate a custom Asana project field for budget tracking. Actual-versus-planned budget analysis requires connecting your financial data source as well.",
      },
    ],
  },

  "trello-notion": {
    slug: "trello-notion",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline:
      "Embed Trello boards in Notion and sync cards to Notion databases automatically",
    metaTitle:
      "Trello + Notion Automation - Connect Boards to Your Knowledge Base | GAIA",
    metaDescription:
      "Bridge Trello and Notion with GAIA. Sync Trello cards to Notion databases, embed board status in Notion project pages, and keep your knowledge base and task management in perfect alignment.",
    keywords: [
      "Trello Notion integration",
      "Trello Notion sync",
      "connect Trello and Notion",
      "Trello Notion automation",
      "Kanban Notion database sync",
      "project management knowledge base",
    ],
    intro:
      "Trello and Notion serve complementary purposes — Trello for visual task management and Notion for documentation, wikis, and project knowledge bases. But when teams run both, Trello cards and Notion pages diverge quickly. A Trello card gets completed but the Notion project page still shows it as in progress. A Notion database entry is created but no Trello card exists to track the actual work.\n\nGAIA connects Trello and Notion so task management and documentation stay aligned. Trello card updates flow into Notion database entries, Notion project pages pull live Trello board status, and new Notion items trigger Trello card creation. Teams get the visual workflow benefits of Trello with the rich documentation capabilities of Notion, connected rather than siloed.\n\nThis integration is ideal for teams that use Notion as their company wiki while managing day-to-day tasks in Trello, and for project managers who need project documentation and task status to live in the same place.",
    useCases: [
      {
        title: "Sync Trello cards to a Notion database",
        description:
          "When a card is added to a Trello board, GAIA creates a corresponding entry in a Notion database with the card title, description, due date, and list status, keeping documentation in sync with execution.",
      },
      {
        title: "Update Notion entries when Trello cards move",
        description:
          "When a Trello card moves between lists — from Backlog to In Progress to Done — GAIA updates the status field on the linked Notion database entry, keeping the Notion project database accurate.",
      },
      {
        title: "Create Trello cards from Notion database entries",
        description:
          "When a new task is added to a Notion project database, GAIA creates the corresponding Trello card in the right list, ensuring every documented task has an actionable card for execution.",
      },
      {
        title: "Embed Trello board summaries in Notion project pages",
        description:
          "GAIA generates a structured Trello board status summary and appends it to the linked Notion project page on a scheduled basis, giving readers an accurate view of task progress without leaving Notion.",
      },
      {
        title: "Archive completed cards to Notion",
        description:
          "When a Trello card is completed and archived, GAIA appends a completion record to the Notion project page, building a running log of completed work that serves as project history and documentation.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and Notion to GAIA",
        description:
          "Authorize GAIA to access your Trello boards and your Notion workspace. Map specific Trello boards to Notion databases and define which fields correspond between the two platforms.",
      },
      {
        step: "Set sync direction and trigger events",
        description:
          "Choose whether to sync from Trello to Notion, Notion to Trello, or both. Configure which card events — creation, list movement, due date change, completion — trigger Notion updates.",
      },
      {
        step: "GAIA keeps boards and databases aligned",
        description:
          "GAIA monitors both platforms and propagates changes automatically so your Trello boards and Notion databases always reflect the same task state without manual data entry.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync Trello card labels to Notion tags?",
        answer:
          "Yes. GAIA maps Trello card labels to Notion multi-select or tag fields. When a label is added or removed from a Trello card, GAIA updates the corresponding Notion entry field to match.",
      },
      {
        question:
          "What happens to Notion entries when Trello cards are deleted?",
        answer:
          "By default, GAIA marks the Notion entry as archived rather than deleting it, preserving project history. You can configure GAIA to delete entries instead if your workflow requires a clean database.",
      },
      {
        question:
          "Can GAIA create a Trello board from a Notion project template?",
        answer:
          "Yes. When a new project page is created in Notion from a template, GAIA can read the task list from the template and create a fully structured Trello board with lists and initial cards automatically.",
      },
    ],
  },

  "trello-slack": {
    slug: "trello-slack",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline:
      "Post Trello card updates to Slack and create cards directly from Slack messages",
    metaTitle:
      "Trello + Slack Automation - Real-Time Board Updates in Slack | GAIA",
    metaDescription:
      "Connect Trello and Slack with GAIA. Get notified in Slack when Trello cards move, create new cards from Slack messages, and keep your team aligned without switching between tools.",
    keywords: [
      "Trello Slack integration",
      "Trello Slack automation",
      "Trello notifications Slack",
      "create Trello cards from Slack",
      "connect Trello and Slack",
      "Kanban Slack workflow",
    ],
    intro:
      "Trello boards track work visually but only for people who are actively watching them. Team members in Slack miss card movements, due date changes, and completion events unless they check Trello directly. Conversely, important tasks discussed and agreed upon in Slack never make it into Trello because someone always has to manually create the card.\n\nGAIA connects Trello and Slack so neither side has to change their habits. Trello events surface automatically in the right Slack channels, and tasks identified in Slack are captured in Trello without requiring anyone to leave the conversation. Teams that live in Slack stay informed about project progress, and tasks discussed in chat become trackable cards automatically.\n\nThis integration is particularly valuable for agile teams running sprints in Trello, customer support teams routing issues through Slack, and remote teams who use Slack as their digital office and Trello as their project board.",
    useCases: [
      {
        title: "Post card completion updates to Slack channels",
        description:
          "When a Trello card moves to the Done list, GAIA posts a formatted update to the designated Slack channel, celebrating progress and keeping the team informed without anyone checking the board manually.",
      },
      {
        title: "Create Trello cards from Slack messages",
        description:
          "When a task is identified in a Slack message, mention GAIA or react with a specific emoji and GAIA will create a Trello card from the message content, assign it to the right person, and confirm creation in the thread.",
      },
      {
        title: "Daily board digest in Slack",
        description:
          "GAIA posts a morning digest to a Slack channel listing all Trello cards due today, cards moved yesterday, and any overdue items, giving the team a quick project health snapshot without opening Trello.",
      },
      {
        title: "Overdue card alerts",
        description:
          "When a Trello card passes its due date without being completed, GAIA sends a Slack DM to the card's assigned member and a summary alert to the project channel so nothing slips through unnoticed.",
      },
      {
        title: "New card assignment notifications",
        description:
          "When a Trello card is assigned to a team member, GAIA sends them a Slack DM with the card title, description, due date, and board link, ensuring immediate awareness of new responsibilities.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and Slack to GAIA",
        description:
          "Authorize GAIA to access your Trello boards and your Slack workspace. Map Trello boards to Slack channels so updates from each board route to the appropriate team channel.",
      },
      {
        step: "Configure which events post to Slack",
        description:
          "Choose the Trello events that trigger Slack messages — card creation, movement between lists, due date arrival, completion, or assignment — and set the target channel for each event type.",
      },
      {
        step: "GAIA bridges boards and chat in real time",
        description:
          "GAIA monitors Trello for board activity and posts structured notifications to Slack as events occur, while also listening in Slack for card creation requests so tasks move from conversation to execution instantly.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA post different Trello boards to different Slack channels?",
        answer:
          "Yes. You can configure per-board Slack channel mappings so that updates from your marketing board go to the marketing channel, engineering board updates go to the engineering channel, and so on.",
      },
      {
        question: "What format do Slack notifications from Trello take?",
        answer:
          "GAIA posts structured Slack messages with the card title, current list, assignee, due date, and a direct link to the Trello card. Digest messages include a formatted table of cards grouped by status.",
      },
      {
        question:
          "Can I create a Trello card from a Slack message without a bot command?",
        answer:
          "Yes. GAIA supports emoji-based card creation — react to any Slack message with a designated emoji and GAIA will create a Trello card from that message automatically.",
      },
    ],
  },

  "trello-github": {
    slug: "trello-github",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline:
      "Move Trello cards when PRs merge and link GitHub issues to Trello cards",
    metaTitle:
      "Trello + GitHub Automation - Connect Code Delivery to Project Boards | GAIA",
    metaDescription:
      "Link your GitHub development workflow to Trello with GAIA. Automatically move Trello cards when pull requests merge, create cards from GitHub issues, and keep engineering and project management perfectly aligned.",
    keywords: [
      "Trello GitHub integration",
      "Trello GitHub automation",
      "connect Trello and GitHub",
      "GitHub PR Trello card",
      "Trello GitHub workflow",
      "developer project management",
    ],
    intro:
      "Software teams using Trello for project management and GitHub for code often face a visibility gap — Trello cards sit in In Progress long after the code has merged, and GitHub issues get filed without corresponding Trello cards for the product team to track. The disconnect means project status in Trello rarely reflects the actual state of development in GitHub.\n\nGAIA connects Trello and GitHub so code events automatically update project boards and project cards trigger appropriate GitHub actions. When a pull request is merged, GAIA moves the linked Trello card to Done. When a GitHub issue is opened, GAIA can create the corresponding Trello card. The result is a Trello board that stays accurate without requiring engineers to manually update cards after every commit.\n\nThis integration is essential for small-to-medium development teams that use Trello for product planning and GitHub for all code activity, and for teams that need non-technical stakeholders to have accurate project visibility without access to GitHub.",
    useCases: [
      {
        title: "Move Trello cards when pull requests merge",
        description:
          "When a GitHub pull request linked to a Trello card is merged, GAIA automatically moves the card to the Done list, keeping the Trello board accurate without requiring manual updates from engineers.",
      },
      {
        title: "Create Trello cards from GitHub issues",
        description:
          "When a GitHub issue is opened with a specific label, GAIA creates a corresponding Trello card in the appropriate list, ensuring all engineering work items have a visible counterpart on the project board.",
      },
      {
        title: "Reflect PR review status on Trello cards",
        description:
          "When a pull request is submitted for review, GAIA moves the linked Trello card to a Review list and adds a comment with the PR link and reviewer list, giving the team visibility into the review stage.",
      },
      {
        title: "Bug report cards from GitHub issue labels",
        description:
          "When a GitHub issue is labeled as a bug, GAIA creates a Trello card in the bug triage list with the issue title, severity label, and GitHub link so the product team can prioritize the fix alongside other work.",
      },
      {
        title: "Sprint velocity reporting",
        description:
          "GAIA aggregates GitHub PR merge data and corresponding Trello card completions to generate sprint velocity reports, showing how many cards were completed and how long they spent in each list.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and GitHub to GAIA",
        description:
          "Authorize GAIA to access your Trello boards and your GitHub repositories. Configure which repositories trigger updates on which Trello boards.",
      },
      {
        step: "Link Trello cards to GitHub issues or PRs",
        description:
          "Reference Trello card IDs in GitHub PR descriptions or issue bodies, or use GAIA's automatic linking to match items by title and labels. GAIA maintains the link going forward.",
      },
      {
        step: "GAIA keeps boards and code in sync",
        description:
          "As GitHub events fire — issues opened, PRs submitted, PRs merged, issues closed — GAIA propagates the corresponding Trello card movements and updates automatically.",
      },
    ],
    faqs: [
      {
        question:
          "Do developers need to reference Trello card IDs in every PR?",
        answer:
          "Not necessarily. GAIA supports fuzzy matching between GitHub issues and Trello cards by title and label. Explicit card ID references give the most reliable links, but GAIA can infer matches for common workflows.",
      },
      {
        question:
          "Can GAIA handle multiple GitHub repositories mapped to a single Trello board?",
        answer:
          "Yes. You can map multiple repositories to a single Trello board, with per-repository label filters to control which issues and PRs create or update Trello cards.",
      },
      {
        question:
          "What happens when a GitHub issue is closed without merging a PR?",
        answer:
          "GAIA moves the linked Trello card to a Closed or Won't Do list based on your configuration, and adds a comment noting the issue was closed without a merge so the project team has the full context.",
      },
    ],
  },

  "trello-google-calendar": {
    slug: "trello-google-calendar",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Add Trello due dates to your calendar and create cards from calendar events",
    metaTitle:
      "Trello + Google Calendar Automation - Sync Task Deadlines with Your Calendar | GAIA",
    metaDescription:
      "Connect Trello and Google Calendar with GAIA. Automatically add Trello card due dates to your calendar, create Trello cards from calendar events, and never miss a project deadline again.",
    keywords: [
      "Trello Google Calendar integration",
      "Trello calendar sync",
      "Trello due dates calendar",
      "connect Trello and Google Calendar",
      "Trello Calendar automation",
      "project deadline calendar",
    ],
    intro:
      "Trello due dates live inside boards that require active checking, while deadlines and commitments are most useful when they appear in your calendar alongside everything else on your plate. Without a connection between the two, team members miss Trello deadlines because they were not checking their board, or they schedule meetings without knowing that a Trello card deadline falls on the same day.\n\nGAIA connects Trello and Google Calendar so due dates appear where people actually plan their time. Trello card due dates become calendar events with direct links back to the card. Calendar events for project reviews or client deliveries become Trello cards automatically. The result is a unified schedule that reflects both meetings and tasks without requiring manual entry in two places.\n\nThis integration is ideal for project managers who live in their calendar and freelancers who use Trello for client work but schedule everything through Google Calendar.",
    useCases: [
      {
        title: "Add Trello due dates to Google Calendar",
        description:
          "When a due date is set on a Trello card, GAIA creates a Google Calendar event at the due date and time, including the card title and a link back to the Trello card so the deadline is visible in your daily schedule.",
      },
      {
        title: "Create Trello cards from calendar events",
        description:
          "When a Google Calendar event is created with a specific keyword or in a designated project calendar, GAIA creates a Trello card with the event name, date, and description so the commitment is tracked in your project board.",
      },
      {
        title: "Multi-stage deadline reminders",
        description:
          "GAIA creates multi-stage Google Calendar reminders for Trello cards — a one-week warning, a two-day alert, and a same-day notification — so teams have sufficient lead time to complete work before deadlines.",
      },
      {
        title: "Sprint calendar from Trello board",
        description:
          "GAIA reads all due dates from a Trello sprint board and generates a Google Calendar sprint view, giving the team a time-based perspective on the sprint workload alongside their meeting schedule.",
      },
      {
        title: "Reschedule overdue items automatically",
        description:
          "When a Google Calendar event linked to a Trello card passes without the card being completed, GAIA moves the card to an Overdue list and reschedules the calendar event so the deadline gets a new target date.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and Google Calendar to GAIA",
        description:
          "Authorize GAIA to access your Trello boards and your Google Calendar. Select which boards and lists to monitor for due dates and which calendars to write events to.",
      },
      {
        step: "Configure deadline-to-event mapping",
        description:
          "Define how Trello card metadata maps to calendar event fields — title format, calendar selection, reminder timing, and what happens when a Trello due date changes.",
      },
      {
        step: "GAIA keeps deadlines visible across both tools",
        description:
          "GAIA monitors Trello for due date changes and Google Calendar for new events, synchronizing both systems so your schedule always reflects your actual project commitments.",
      },
    ],
    faqs: [
      {
        question:
          "What happens to the calendar event when a Trello due date is changed?",
        answer:
          "GAIA automatically updates the linked Google Calendar event to match the new due date, so your calendar always reflects the current Trello deadline without manual edits.",
      },
      {
        question:
          "Can GAIA create calendar events for an entire Trello board at once?",
        answer:
          "Yes. You can ask GAIA to bulk-create calendar events for all cards with due dates on a specific Trello board, populating your calendar with the full project schedule in one operation.",
      },
      {
        question: "Does GAIA sync Trello due times as well as dates?",
        answer:
          "Yes. When a due time is set in Trello, GAIA creates a timed calendar event. When only a date is set, GAIA creates an all-day event for that date.",
      },
    ],
  },

  "trello-drive": {
    slug: "trello-drive",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach Drive files to Trello cards and organize project assets automatically",
    metaTitle:
      "Trello + Google Drive Automation - Link Documents to Your Trello Cards | GAIA",
    metaDescription:
      "Connect Trello and Google Drive with GAIA. Automatically create Drive folders for Trello boards, attach relevant files to cards, and keep all project documents organized and accessible from your Kanban board.",
    keywords: [
      "Trello Google Drive integration",
      "Trello Drive automation",
      "attach files Trello cards",
      "connect Trello and Google Drive",
      "Trello document management",
      "project asset organization",
    ],
    intro:
      "Trello cards represent work, but the actual work product — briefs, drafts, designs, reports — lives in Google Drive. Without a connection between the two, team members spend time searching Drive for files mentioned in Trello cards, or they attach outdated file links to cards when the document has since been updated or moved.\n\nGAIA connects Trello and Google Drive so documents are organized around cards automatically. When a new Trello board is created, GAIA sets up the corresponding Drive folder structure. As cards progress through lists, GAIA attaches relevant files and notifies team members when documents are updated. The result is a Trello board where every card has immediate access to all related documents without manual file hunting.\n\nThis integration is especially useful for marketing teams managing campaigns in Trello, content teams tracking article production, and project managers who need all deliverables organized and accessible from a single card view.",
    useCases: [
      {
        title: "Create Drive folders for new Trello boards",
        description:
          "When a new Trello board is created, GAIA automatically creates a corresponding Google Drive folder with subfolders matching the board's lists, providing an organized document structure from day one.",
      },
      {
        title: "Auto-attach Drive files to Trello cards",
        description:
          "When a file is added to a Drive folder linked to a Trello board, GAIA attaches the file to the appropriate Trello card based on naming conventions or list-to-folder mappings, keeping files accessible directly from the card.",
      },
      {
        title: "Notify card members when files are updated",
        description:
          "When a Drive file attached to a Trello card is modified, GAIA posts a comment on the card notifying the assigned member, ensuring the latest version is reviewed rather than an outdated cached copy.",
      },
      {
        title: "Deliverable submission workflow",
        description:
          "When a team member adds a completed deliverable to a Drive folder, GAIA moves the linked Trello card to the Review list and attaches the file, triggering the review stage without any manual card updates.",
      },
      {
        title: "Archive project files when cards complete",
        description:
          "When a Trello card is moved to Done, GAIA moves associated Drive files to a completed deliverables subfolder, keeping the active project folder clean while preserving all final assets.",
      },
    ],
    howItWorks: [
      {
        step: "Authorize Trello and Google Drive in GAIA",
        description:
          "Connect your Trello account and Google Drive to GAIA. Specify the Drive root folder where board folders should be created and the Trello boards to monitor.",
      },
      {
        step: "Configure folder structure and attachment rules",
        description:
          "Define the Drive folder template for new boards and the rules GAIA uses to match Drive files to Trello cards — by file name pattern, subfolder, or card label.",
      },
      {
        step: "GAIA organizes documents around your cards",
        description:
          "GAIA monitors both Trello and Drive for changes, attaching files to cards, creating folders for new boards, and notifying team members when documents are updated.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA attach a Drive file to a specific Trello card on request?",
        answer:
          "Yes. Ask GAIA to find a specific Drive file by name and attach it to a Trello card by title or card ID. GAIA searches Drive, retrieves the file link, and adds it to the card.",
      },
      {
        question: "What happens to Drive files when a Trello card is deleted?",
        answer:
          "GAIA does not delete Drive files when a Trello card is removed. It can optionally move the files to an archive folder and log the card deletion so documents are preserved for reference.",
      },
      {
        question:
          "Can GAIA create a Drive document from a Trello card template?",
        answer:
          "Yes. You can configure GAIA to create a Drive document from a specified template when a Trello card is created in a specific list, pre-filling the document with card metadata such as title, assignee, and due date.",
      },
    ],
  },

  "trello-figma": {
    slug: "trello-figma",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Link Figma designs to Trello product cards and automate the design review workflow",
    metaTitle:
      "Trello + Figma Automation - Connect Design Files to Product Cards | GAIA",
    metaDescription:
      "Bridge design and product management with GAIA. Automatically attach Figma files to Trello cards, move cards when designs are approved, and keep your design review workflow on track without manual status updates.",
    keywords: [
      "Trello Figma integration",
      "Trello Figma automation",
      "design review Trello workflow",
      "connect Trello and Figma",
      "Figma Trello card",
      "product design workflow automation",
    ],
    intro:
      "Product teams managing work in Trello and design teams working in Figma face a recurring handoff problem. Designers share Figma links in Slack or email, but those links never make it onto the Trello card. Product managers check Trello to see if designs are ready but find no file attached and no status update. The result is a fragmented review process that delays development and creates confusion about which design version is current.\n\nGAIA connects Trello and Figma so design deliverables are always attached to the right card and design status changes automatically advance cards through the workflow. When a Figma file is updated for a project, GAIA attaches it to the linked Trello card. When designs are approved in Figma, GAIA moves the Trello card to the next stage. Teams stay in their preferred tools while the handoff happens automatically.\n\nThis integration is built for product and design teams that want to eliminate manual status updates and ensure design assets are always discoverable from the project board.",
    useCases: [
      {
        title: "Attach Figma files to Trello product cards",
        description:
          "When a Figma file is created or updated for a feature, GAIA automatically attaches the Figma link to the corresponding Trello card, ensuring the latest design is always accessible from the product board.",
      },
      {
        title: "Move cards when designs are ready for review",
        description:
          "When a Figma file status changes to Ready for Review, GAIA moves the linked Trello card to the Design Review list and notifies the reviewer, starting the feedback loop without a manual card update.",
      },
      {
        title: "Advance cards on design approval",
        description:
          "When a Figma design is approved in a comment or status field, GAIA moves the Trello card to the Development Ready list and notifies the engineering assignee, making the design-to-dev handoff instant and traceable.",
      },
      {
        title: "Flag revision requests on Trello cards",
        description:
          "When a Figma reviewer leaves revision feedback, GAIA posts a comment on the linked Trello card summarizing the requested changes and moves the card back to In Design, keeping status accurate.",
      },
      {
        title: "Design sprint tracking",
        description:
          "GAIA monitors all Figma files linked to a Trello sprint board and generates a weekly design progress report showing how many cards are in design, in review, approved, and delivered.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and Figma to GAIA",
        description:
          "Authorize GAIA to access your Trello boards and your Figma account. Map Figma projects to Trello boards and configure how design status changes map to Trello list movements.",
      },
      {
        step: "Link Figma files to Trello cards",
        description:
          "GAIA can auto-link files to cards by matching names, or you can explicitly link a Figma file to a Trello card on first reference. GAIA maintains the association going forward.",
      },
      {
        step: "GAIA manages the design review workflow",
        description:
          "As Figma file statuses change, GAIA moves Trello cards, attaches updated file links, and notifies the relevant team members, keeping the design review process on track automatically.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA attach specific Figma frames to Trello cards rather than the whole file?",
        answer:
          "Yes. You can configure GAIA to attach specific Figma frame links so reviewers navigate directly to the relevant design component rather than searching through a large file.",
      },
      {
        question:
          "What happens when a Figma design is revised after being approved?",
        answer:
          "GAIA detects the post-approval edit and can reopen the Trello review card or notify the product manager, ensuring revised designs get proper sign-off before development proceeds.",
      },
      {
        question: "Does GAIA work with Figma branching for design review?",
        answer:
          "Yes. GAIA can track Figma branches and attach branch links to Trello cards during review, then update the card to the main file link when the branch is merged after approval.",
      },
    ],
  },

  "trello-discord": {
    slug: "trello-discord",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline:
      "Post Trello board updates to Discord community channels automatically",
    metaTitle:
      "Trello + Discord Automation - Board Updates in Your Discord Server | GAIA",
    metaDescription:
      "Keep your Discord community informed with GAIA. Automatically post Trello card completions, new assignments, and board activity to Discord channels so your team always knows what's happening.",
    keywords: [
      "Trello Discord integration",
      "Trello Discord automation",
      "Trello notifications Discord",
      "connect Trello and Discord",
      "project updates Discord server",
      "community project management",
    ],
    intro:
      "Communities and teams that organize in Discord need project updates to surface in the platform where they already spend their time. When Trello board activity — card completions, new assignments, milestone achievements — stays locked inside Trello, Discord-first teams are left in the dark unless they actively check the board.\n\nGAIA connects Trello and Discord so board activity flows automatically into the right Discord channels. Card completions get posted to team channels, new cards notify assignees in DMs, and board summaries keep the broader community informed of project progress. Teams working on open-source projects, game development, or community initiatives can share project updates with their Discord audience without any manual copy-pasting.\n\nThis integration is particularly suited for open-source communities, gaming studios, creator collectives, and any team that runs its community on Discord while tracking project work in Trello.",
    useCases: [
      {
        title: "Post card completions to Discord channels",
        description:
          "When a Trello card moves to Done, GAIA posts a formatted message to the designated Discord channel with the card title, board, and assignee, keeping the community informed of progress milestones.",
      },
      {
        title: "Notify assignees via Discord DM",
        description:
          "When a Trello card is assigned to a team member, GAIA sends them a Discord direct message with the card details, due date, and board link so they are immediately aware of the new task.",
      },
      {
        title: "Weekly board digest in Discord",
        description:
          "GAIA posts a weekly Trello board summary to a Discord channel listing completed cards, in-progress items, and upcoming due dates, giving the community a regular project health update.",
      },
      {
        title: "Sprint completion announcements",
        description:
          "When all cards in a Trello sprint list are completed, GAIA posts a sprint completion announcement to the Discord server with a summary of what was accomplished, building team morale and community visibility.",
      },
      {
        title: "Create Trello cards from Discord messages",
        description:
          "Mention GAIA in a Discord message to create a Trello card directly from the conversation, ensuring that ideas and tasks raised in Discord channels are captured in the project board without context switching.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and Discord to GAIA",
        description:
          "Authorize GAIA to access your Trello boards and your Discord server. Configure which Trello boards map to which Discord channels for update notifications.",
      },
      {
        step: "Select events and notification format",
        description:
          "Choose which Trello events trigger Discord messages — card creation, movement, completion, assignment, or overdue — and customize the message format to match your community's style.",
      },
      {
        step: "GAIA keeps your community updated",
        description:
          "GAIA monitors Trello board activity and posts formatted notifications to Discord automatically, so your community and team are always informed without manual effort.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA post updates from multiple Trello boards to different Discord channels?",
        answer:
          "Yes. You can configure per-board channel mappings so that different project boards post to their respective Discord channels, keeping notifications organized and relevant to each audience.",
      },
      {
        question:
          "Can community members create Trello cards from Discord without board access?",
        answer:
          "Yes. GAIA can accept Trello card creation requests from Discord users who do not have direct Trello access, acting as the bridge between the community and the project board.",
      },
      {
        question:
          "Will every Trello card movement create a Discord notification?",
        answer:
          "Only the event types you configure will generate Discord messages. Most teams post only completions and major milestones to keep channels readable rather than notifying on every card move.",
      },
    ],
  },

  "trello-zoom": {
    slug: "trello-zoom",
    toolA: "Trello",
    toolASlug: "trello",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline:
      "Schedule Trello sprint calls and post Zoom meeting summaries back to cards",
    metaTitle:
      "Trello + Zoom Automation - Connect Sprint Meetings to Your Trello Board | GAIA",
    metaDescription:
      "Link Trello and Zoom with GAIA. Schedule sprint calls when boards move to new stages, post Zoom meeting summaries to Trello cards, and turn call action items into cards automatically.",
    keywords: [
      "Trello Zoom integration",
      "Trello Zoom automation",
      "sprint meeting Trello",
      "connect Trello and Zoom",
      "Zoom meeting Trello cards",
      "project meeting workflow",
    ],
    intro:
      "Trello sprint boards drive the rhythm of project work, but much of that work is coordinated in Zoom meetings — sprint planning calls, card review sessions, retrospectives. Without automation, teams manually schedule meetings that should be triggered by board events, and the action items discussed on those calls never find their way back into Trello cards without someone taking detailed notes and manually creating cards afterward.\n\nGAIA connects Trello and Zoom so meetings are scheduled automatically at the right board stage and meeting outcomes flow back into the board immediately after each call. When a Trello sprint list is fully populated and ready to start, GAIA schedules the sprint kickoff call. When the call ends, GAIA posts the meeting summary to the board and creates Trello cards from action items extracted from the transcript.\n\nThis integration is built for agile teams, project managers, and any group that runs structured board reviews on Zoom and needs meeting outcomes to live inside Trello where the actual work is tracked.",
    useCases: [
      {
        title: "Schedule sprint kickoff calls from board stage changes",
        description:
          "When a Trello board moves to a new sprint stage or a sprint list is populated, GAIA schedules a Zoom kickoff call with the team, sends calendar invites, and attaches the meeting link to the Trello board.",
      },
      {
        title: "Post Zoom meeting summaries to Trello cards",
        description:
          "After a Zoom call associated with a Trello board, GAIA generates a meeting summary from the transcript and posts it as a comment on the relevant card, creating a permanent discussion record.",
      },
      {
        title: "Create Trello cards from Zoom action items",
        description:
          "GAIA analyzes Zoom call transcripts for action items and creates corresponding Trello cards in the appropriate list, with the action item as the card title and the responsible person as the assignee.",
      },
      {
        title: "Sprint retrospective scheduling",
        description:
          "When all cards in a Trello sprint list are completed, GAIA schedules a retrospective Zoom call with the team and attaches a retrospective summary template to the Trello board for preparation.",
      },
      {
        title: "Card review sessions for blocked items",
        description:
          "When multiple Trello cards are flagged as blocked, GAIA schedules a Zoom unblocking session with the relevant card owners and posts a pre-meeting agenda to the board with all blocked cards listed.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Trello and Zoom to GAIA",
        description:
          "Authorize GAIA to access your Trello boards and Zoom account. Link your calendar so GAIA can schedule meetings that fit the team's availability.",
      },
      {
        step: "Configure board events that trigger meetings",
        description:
          "Define which Trello board states or list events should trigger Zoom meetings, who should be invited, and when the meeting should be scheduled relative to the board event.",
      },
      {
        step: "GAIA schedules calls and captures outcomes",
        description:
          "GAIA monitors Trello for trigger events, schedules Zoom meetings, and after each call posts summaries and action item cards back to the board automatically.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA schedule a Zoom call directly from a Trello card comment?",
        answer:
          "Yes. Mention GAIA in a Trello card comment asking for a meeting, and GAIA will schedule a Zoom call with the card members, check calendar availability, and post the meeting link back to the card.",
      },
      {
        question:
          "Does GAIA require Zoom cloud recording for meeting summaries?",
        answer:
          "Zoom transcription or cloud recording must be enabled on the meeting for GAIA to generate summaries. GAIA accesses the transcript after the meeting ends and generates a structured summary.",
      },
      {
        question:
          "Can GAIA create recurring sprint meetings based on Trello sprint cycles?",
        answer:
          "Yes. GAIA can schedule recurring Zoom sprint calls based on your Trello board's sprint cadence, automatically adding the meeting link to the board and updating the invite as team membership changes.",
      },
    ],
  },

  "hubspot-notion": {
    slug: "hubspot-notion",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline:
      "Sync HubSpot CRM data to Notion docs and document deals and customer research",
    metaTitle:
      "HubSpot + Notion Automation - Bring CRM Data into Your Knowledge Base | GAIA",
    metaDescription:
      "Connect HubSpot and Notion with GAIA. Automatically sync deal data to Notion databases, create account research pages from HubSpot contacts, and keep your CRM and knowledge base aligned.",
    keywords: [
      "HubSpot Notion integration",
      "HubSpot Notion sync",
      "CRM knowledge base integration",
      "connect HubSpot and Notion",
      "HubSpot Notion automation",
      "deal documentation Notion",
    ],
    intro:
      "Sales and revenue teams use HubSpot to track deals and contacts while using Notion for account research, meeting notes, and internal documentation. Without automation, CRM data has to be manually copied into Notion pages and Notion research stays disconnected from the HubSpot records it relates to. The result is duplicated effort and a knowledge base that rarely reflects the current state of the pipeline.\n\nGAIA connects HubSpot and Notion so CRM data flows into your knowledge base automatically. When a new deal is created in HubSpot, GAIA creates a corresponding Notion page with deal details, contact information, and a research template. As the deal progresses, GAIA updates the Notion page with stage changes and activity summaries so the account documentation stays current without manual input.\n\nThis integration is ideal for account executives who maintain detailed deal documentation, sales enablement teams building account playbooks, and revenue operations teams who want their knowledge base to reflect live CRM data.",
    useCases: [
      {
        title: "Create Notion deal pages from HubSpot opportunities",
        description:
          "When a new deal is created in HubSpot, GAIA automatically creates a Notion page with the deal name, value, stage, associated contacts, and a structured research template so account documentation starts immediately.",
      },
      {
        title: "Sync HubSpot contact data to Notion databases",
        description:
          "GAIA keeps a Notion database of HubSpot contacts synchronized with CRM data — company, title, deal stage, last activity — so team members can research accounts from Notion without switching to HubSpot.",
      },
      {
        title: "Document deal stage changes automatically",
        description:
          "When a HubSpot deal advances to a new pipeline stage, GAIA appends a stage change entry to the linked Notion deal page with the date and any notes from HubSpot, building a complete deal history.",
      },
      {
        title: "Pull HubSpot activity summaries into Notion",
        description:
          "GAIA aggregates recent HubSpot email, call, and meeting activity for an account and posts a weekly summary to the Notion account page, giving the team a consolidated view of customer engagement.",
      },
      {
        title: "Competitive research integration",
        description:
          "When a HubSpot deal is linked to a competitor, GAIA retrieves the relevant Notion competitive research page and attaches a link to the HubSpot deal record so reps can access battlecards from the CRM.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Notion to GAIA",
        description:
          "Authorize GAIA to access your HubSpot portal and Notion workspace. Map HubSpot deal pipelines and contact properties to Notion database fields.",
      },
      {
        step: "Configure page templates and sync triggers",
        description:
          "Define the Notion page template for new deals, choose which HubSpot events trigger Notion updates, and set the database where contact and deal records should be maintained.",
      },
      {
        step: "GAIA keeps CRM and knowledge base in sync",
        description:
          "GAIA monitors HubSpot for deal and contact changes and updates Notion automatically, so your knowledge base always reflects the current state of your pipeline without manual data entry.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync Notion meeting notes back to HubSpot?",
        answer:
          "Yes. When a meeting notes entry is added to a Notion deal page, GAIA can create a corresponding HubSpot activity note on the linked deal or contact, keeping the CRM timeline complete.",
      },
      {
        question: "Does GAIA create one Notion page per deal or per account?",
        answer:
          "You can configure either. GAIA supports per-deal pages for detailed opportunity tracking and per-account pages that aggregate all deals and contacts for a given company.",
      },
      {
        question:
          "Can GAIA sync HubSpot custom properties to Notion custom fields?",
        answer:
          "Yes. During setup, you map HubSpot custom properties to Notion database properties. GAIA maintains those mappings and syncs values as they change in HubSpot.",
      },
    ],
  },

  "hubspot-asana": {
    slug: "hubspot-asana",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline:
      "Create onboarding and delivery tasks in Asana from new HubSpot deals",
    metaTitle:
      "HubSpot + Asana Automation - Turn Closed Deals into Project Tasks | GAIA",
    metaDescription:
      "Bridge sales and delivery with GAIA. Automatically create Asana onboarding projects when HubSpot deals close, sync deal data to project tasks, and keep account managers and delivery teams aligned.",
    keywords: [
      "HubSpot Asana integration",
      "HubSpot Asana automation",
      "deal to project automation",
      "connect HubSpot and Asana",
      "sales to delivery workflow",
      "onboarding automation HubSpot Asana",
    ],
    intro:
      "Every closed deal in HubSpot represents a handoff that needs to happen — from sales to customer success, implementation, or delivery. Without automation, that handoff relies on a salesperson remembering to notify the right team, and the delivery team manually creating Asana tasks that should have been generated from the deal data already sitting in HubSpot.\n\nGAIA automates the sales-to-delivery handoff so nothing falls through the cracks. When a HubSpot deal closes, GAIA creates a structured Asana project or task list for the relevant delivery team, pre-populated with customer details from the CRM. As the onboarding progresses, GAIA can log Asana milestone completions back to HubSpot so account managers stay informed without interrupting the delivery team.\n\nThis integration is built for SaaS companies, professional services firms, and agencies where closing a deal immediately generates structured delivery work that needs to be tracked in Asana.",
    useCases: [
      {
        title: "Auto-create onboarding projects from closed deals",
        description:
          "When a HubSpot deal reaches Closed Won, GAIA creates a new Asana project from the appropriate onboarding template, pre-fills customer details, assigns the customer success team, and sets deadlines based on contract start date.",
      },
      {
        title: "Sync deal data to Asana project fields",
        description:
          "GAIA maps HubSpot deal fields — company name, contract value, product purchased, primary contact — to Asana project custom fields so the delivery team has full context without accessing HubSpot.",
      },
      {
        title: "Log Asana milestone completions in HubSpot",
        description:
          "When key Asana onboarding tasks are completed, GAIA logs the milestones as HubSpot deal activities, keeping account managers informed of onboarding progress directly in their CRM view.",
      },
      {
        title: "Escalate at-risk onboardings to HubSpot",
        description:
          "When an Asana onboarding project is overdue or flagged as at-risk, GAIA creates a HubSpot task for the account owner to reach out to the client proactively, preventing churn before it happens.",
      },
      {
        title: "Trigger HubSpot sequences from Asana completions",
        description:
          "When an Asana onboarding project is marked complete, GAIA enrolls the client in a HubSpot post-onboarding email sequence, initiating the customer success phase without any manual CRM action.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Asana to GAIA",
        description:
          "Authorize GAIA to access your HubSpot portal and Asana workspace. Map HubSpot pipeline stages and deal properties to Asana project templates and task fields.",
      },
      {
        step: "Define handoff rules and templates",
        description:
          "Configure which HubSpot deal stages or properties trigger Asana project creation, which Asana template to use for each deal type, and which fields to pre-populate from CRM data.",
      },
      {
        step: "GAIA bridges sales and delivery automatically",
        description:
          "GAIA monitors HubSpot for deal stage changes and creates Asana projects immediately, while also reporting Asana milestone progress back to HubSpot so both teams work from accurate, shared data.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create different Asana templates for different HubSpot deal types?",
        answer:
          "Yes. You can configure GAIA to select Asana project templates based on HubSpot deal properties such as product line, contract tier, or customer segment, ensuring the right task structure for each engagement.",
      },
      {
        question:
          "What happens in Asana if a HubSpot deal is reopened after being closed?",
        answer:
          "GAIA can detect deal stage reversals and notify the Asana project team, or optionally pause or archive the Asana project, depending on how your workflow handles deal reversals.",
      },
      {
        question:
          "Can sales reps see Asana onboarding progress without an Asana account?",
        answer:
          "Yes. GAIA logs Asana milestone completions as HubSpot activities so account managers see onboarding progress inside HubSpot without needing Asana access.",
      },
    ],
  },

  "hubspot-linear": {
    slug: "hubspot-linear",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Linear",
    toolBSlug: "linear",
    tagline:
      "Link customer feature requests in HubSpot to engineering issues in Linear",
    metaTitle:
      "HubSpot + Linear Automation - Connect Customer Feedback to Engineering | GAIA",
    metaDescription:
      "Bridge sales and engineering with GAIA. Automatically create Linear issues from HubSpot deal feature requests, track request status in CRM, and close the loop between customer feedback and product delivery.",
    keywords: [
      "HubSpot Linear integration",
      "HubSpot Linear automation",
      "customer feedback engineering",
      "connect HubSpot and Linear",
      "feature request CRM workflow",
      "sales engineering alignment",
    ],
    intro:
      "Sales teams capture customer feature requests in HubSpot notes and deal fields, but those requests rarely make it to the engineering team in a structured way. Engineers using Linear have no visibility into which customer asked for a feature or how many deals depend on it. Product decisions get made without the revenue context sitting in HubSpot, and customers wait for features without any feedback loop.\n\nGAIA connects HubSpot and Linear so customer requests drive engineering priorities with full context attached. When a sales rep logs a feature request in HubSpot, GAIA creates or links a Linear issue with the customer details, deal value, and request frequency. When the engineering team ships the feature, GAIA notifies the account owner in HubSpot so they can update the customer before the customer asks.\n\nThis integration is essential for product-led and sales-assisted SaaS companies that want feature development to be informed by real customer demand rather than internal guesswork.",
    useCases: [
      {
        title: "Create Linear issues from HubSpot feature requests",
        description:
          "When a sales rep logs a feature request on a HubSpot deal or contact, GAIA creates a corresponding Linear issue with the request details, customer name, deal value, and request frequency so engineering has full context.",
      },
      {
        title: "Track request popularity across deals",
        description:
          "GAIA aggregates HubSpot feature request notes across multiple deals and updates a Linear issue's description with a running count of requesting customers and combined deal value, helping engineering prioritize by revenue impact.",
      },
      {
        title: "Notify account owners when features ship",
        description:
          "When a Linear issue linked to a HubSpot feature request is marked Done, GAIA creates a HubSpot task for the account owner to reach out to requesting customers, closing the feedback loop before customers follow up.",
      },
      {
        title: "Link Linear issues to HubSpot deal records",
        description:
          "GAIA adds Linear issue links to HubSpot deal records so account managers can check engineering status on customer-requested features directly from the CRM without needing Linear access.",
      },
      {
        title: "Escalate high-value feature blockers",
        description:
          "When a HubSpot deal is blocked by a missing feature, GAIA escalates the linked Linear issue with a priority flag and deal value annotation, ensuring engineering leadership sees the revenue at stake.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Linear to GAIA",
        description:
          "Authorize GAIA to access your HubSpot portal and Linear organization. Configure which HubSpot properties indicate a feature request and which Linear team should receive the issues.",
      },
      {
        step: "Define request capture and linking rules",
        description:
          "Set the HubSpot deal or contact properties that GAIA monitors for feature requests, and configure how GAIA deduplicates requests — creating a new Linear issue or linking to an existing one.",
      },
      {
        step: "GAIA closes the loop between customers and engineering",
        description:
          "GAIA monitors HubSpot for new requests and Linear for issue completions, creating issues, updating request counts, and notifying account owners when requested features are shipped.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA deduplicate feature requests from multiple HubSpot deals?",
        answer:
          "Yes. GAIA matches requests by feature name or description and links multiple HubSpot records to a single Linear issue, updating the issue with a count of requesting customers rather than creating duplicates.",
      },
      {
        question: "Can account managers see Linear issue status from HubSpot?",
        answer:
          "Yes. GAIA adds the Linear issue link and current status to the HubSpot deal or contact record, so account managers can see whether a feature is backlogged, in progress, or shipped without accessing Linear.",
      },
      {
        question:
          "Does GAIA support HubSpot custom properties for feature request tracking?",
        answer:
          "Yes. You can configure GAIA to read feature request data from any HubSpot custom property on deal or contact records, not just standard fields, so it fits your existing CRM data model.",
      },
    ],
  },

  "hubspot-google-calendar": {
    slug: "hubspot-google-calendar",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Sync meeting invites with HubSpot contacts and log calls automatically",
    metaTitle:
      "HubSpot + Google Calendar Automation - Sync Sales Meetings with CRM | GAIA",
    metaDescription:
      "Connect HubSpot and Google Calendar with GAIA. Automatically log calendar meetings as HubSpot activities, create follow-up tasks from call outcomes, and keep your CRM timeline accurate without manual entry.",
    keywords: [
      "HubSpot Google Calendar integration",
      "HubSpot calendar sync",
      "sales meeting CRM automation",
      "connect HubSpot and Google Calendar",
      "HubSpot meeting logging",
      "calendar CRM workflow",
    ],
    intro:
      "Sales reps spend significant time in Google Calendar scheduling and attending client meetings, but those meetings rarely make it into HubSpot automatically. CRM activity timelines go stale, meeting notes get lost in calendar event descriptions instead of living on the contact record, and follow-up tasks get created late or not at all because the rep moved on to the next call.\n\nGAIA connects HubSpot and Google Calendar so every client meeting automatically appears in the CRM timeline without manual logging. When a Google Calendar meeting includes a HubSpot contact, GAIA creates the corresponding HubSpot meeting activity, attaches any pre-meeting notes, and after the meeting creates follow-up tasks based on the meeting outcome.\n\nThis integration is built for account executives, SDRs, and customer success managers who live in Google Calendar for scheduling but need their CRM to reflect every client touchpoint accurately.",
    useCases: [
      {
        title: "Log calendar meetings as HubSpot activities automatically",
        description:
          "When a Google Calendar event includes a HubSpot contact's email address, GAIA automatically creates a corresponding meeting activity on the HubSpot contact or deal record, keeping the CRM timeline accurate without manual logging.",
      },
      {
        title: "Create follow-up tasks from meeting outcomes",
        description:
          "After a meeting ends, GAIA creates a HubSpot follow-up task on the associated deal with a configurable due date, prompting the rep to send notes or take the next agreed action before moving on.",
      },
      {
        title: "Attach meeting notes to HubSpot records",
        description:
          "When a rep adds notes to a Google Calendar event before or after a meeting, GAIA copies those notes to the HubSpot contact or deal record as an activity note, ensuring meeting context lives in the CRM.",
      },
      {
        title: "Schedule HubSpot follow-up meetings from CRM tasks",
        description:
          "When a HubSpot task requires a follow-up call, GAIA checks the rep's Google Calendar availability and creates a calendar event with the contact's details, saving the rep the context-switching of scheduling manually.",
      },
      {
        title: "Pipeline stage updates from meeting cadence",
        description:
          "GAIA monitors meeting frequency between reps and HubSpot contacts and alerts the rep when a deal's meeting cadence drops below a threshold, prompting proactive outreach before a deal goes cold.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Google Calendar to GAIA",
        description:
          "Authorize GAIA to access your HubSpot portal and Google Calendar. GAIA matches calendar attendee email addresses to HubSpot contact records automatically.",
      },
      {
        step: "Configure logging rules and follow-up templates",
        description:
          "Define which calendar events should be logged to HubSpot — by calendar, attendee domain, or event keyword — and set the follow-up task template that GAIA creates after each meeting.",
      },
      {
        step: "GAIA keeps your CRM timeline complete",
        description:
          "GAIA monitors Google Calendar for client meetings and logs them to HubSpot automatically, creating follow-up tasks and syncing notes so your CRM reflects every touchpoint without manual effort.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA log internal meetings or only external client meetings?",
        answer:
          "You can configure GAIA to log only meetings with external email domains matched to HubSpot contacts, excluding internal team meetings from CRM logging to keep activity timelines relevant.",
      },
      {
        question: "What happens when a meeting is rescheduled or cancelled?",
        answer:
          "GAIA updates the linked HubSpot activity record when a Google Calendar event is rescheduled, and marks it as cancelled if the event is deleted, keeping the CRM timeline accurate.",
      },
      {
        question:
          "Can GAIA log meetings for multiple reps across a sales team?",
        answer:
          "Yes. GAIA supports team-level configurations so that calendar meetings for all reps in the sales team are automatically logged to their respective HubSpot contact and deal records.",
      },
    ],
  },

  "hubspot-drive": {
    slug: "hubspot-drive",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach Drive proposals and contracts to HubSpot deals automatically",
    metaTitle:
      "HubSpot + Google Drive Automation - Link Sales Documents to CRM Deals | GAIA",
    metaDescription:
      "Connect HubSpot and Google Drive with GAIA. Automatically attach Drive proposals, contracts, and case studies to HubSpot deals, organize sales assets by account, and keep documents accessible from your CRM.",
    keywords: [
      "HubSpot Google Drive integration",
      "HubSpot Drive automation",
      "sales document CRM",
      "connect HubSpot and Google Drive",
      "attach contracts HubSpot",
      "deal document management",
    ],
    intro:
      "Sales deals generate significant documentation — proposals, contracts, SOWs, case studies, presentations — that typically lives in Google Drive while the deal itself lives in HubSpot. Without a connection, reps waste time searching Drive for the right version of a proposal, or they share the wrong file because the Drive folder structure does not map to HubSpot deal records.\n\nGAIA connects HubSpot and Google Drive so the right documents are always attached to the right deal. When a new deal is created, GAIA creates a structured Drive folder for the account. As deal documents are created or updated in Drive, GAIA attaches them to the HubSpot deal record. When a contract is signed and moved to a signed folder, GAIA updates the HubSpot deal and creates the next-stage task automatically.\n\nThis integration is essential for sales teams that generate custom proposals, account executives managing complex deal cycles with multiple documents, and revenue operations teams that need document management to be automatic and auditable.",
    useCases: [
      {
        title: "Create Drive folders for new HubSpot deals",
        description:
          "When a new deal is created in HubSpot, GAIA creates a structured Google Drive folder for the account with subfolders for proposals, contracts, and supporting materials, and attaches the folder link to the deal record.",
      },
      {
        title: "Auto-attach proposals to HubSpot deals",
        description:
          "When a proposal document is created in a deal's Drive folder, GAIA automatically attaches the file to the linked HubSpot deal record so the document is accessible from the CRM without manual attachment.",
      },
      {
        title: "Notify reps when contracts are ready for review",
        description:
          "When a contract document is added to a deal's Drive folder, GAIA creates a HubSpot task for the rep to review and send it, ensuring contracts move through the approval process without sitting unnoticed in Drive.",
      },
      {
        title: "Log document activity on deal timeline",
        description:
          "When a proposal or contract in Drive is opened by the recipient, GAIA logs a document engagement activity on the HubSpot deal timeline so the rep knows when the prospect is reviewing materials.",
      },
      {
        title: "Advance deal stage when contracts are signed",
        description:
          "When a signed contract is added to a deal's Drive folder, GAIA advances the HubSpot deal to Closed Won, records the signed date, and creates the post-sale handoff task, closing the sales cycle automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Google Drive to GAIA",
        description:
          "Authorize GAIA to access your HubSpot portal and Google Drive. Specify the root Drive folder where account deal folders should be created and the HubSpot pipelines to monitor.",
      },
      {
        step: "Configure folder templates and attachment rules",
        description:
          "Define the Drive folder structure for new deals and the rules GAIA uses to attach files to HubSpot records — by file name, subfolder, or document type.",
      },
      {
        step: "GAIA keeps deal documents organized and linked",
        description:
          "GAIA monitors both HubSpot and Drive for changes, creating folders, attaching documents, and logging activity so your CRM always reflects the current state of your deal documentation.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA generate proposals from HubSpot deal data and save them to Drive?",
        answer:
          "Yes. GAIA can use a Drive document template and populate it with HubSpot deal fields — company name, contact, product, pricing — to generate a proposal draft, saving it to the deal's Drive folder automatically.",
      },
      {
        question: "Does GAIA support multiple document types per deal?",
        answer:
          "Yes. GAIA can manage multiple document types — proposals, NDAs, contracts, SOWs — each attached to the appropriate HubSpot deal section and organized in the correct Drive subfolder.",
      },
      {
        question:
          "Can GAIA detect when a shared Drive document has been viewed by the prospect?",
        answer:
          "GAIA can log when a shared Drive link is accessed if Google Drive sharing analytics are available. For detailed document engagement tracking, integrating a dedicated proposal tool provides richer data.",
      },
    ],
  },

  "hubspot-zoom": {
    slug: "hubspot-zoom",
    toolA: "HubSpot",
    toolASlug: "hubspot",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline:
      "Log Zoom calls to HubSpot and create follow-up tasks from call notes",
    metaTitle:
      "HubSpot + Zoom Automation - Log Sales Calls and Create Follow-Ups | GAIA",
    metaDescription:
      "Connect HubSpot and Zoom with GAIA. Automatically log Zoom calls as CRM activities, post call summaries to deal records, and create follow-up tasks from meeting transcripts so nothing falls through after a sales call.",
    keywords: [
      "HubSpot Zoom integration",
      "HubSpot Zoom automation",
      "log Zoom calls HubSpot",
      "sales call CRM automation",
      "connect HubSpot and Zoom",
      "Zoom meeting HubSpot activity",
    ],
    intro:
      "Sales reps conduct dozens of Zoom calls every week, but those calls rarely make it into HubSpot automatically. Activity timelines go stale, call notes sit in personal documents rather than the CRM, and follow-up commitments made on the call are forgotten because the rep moved straight to the next meeting without logging the outcome.\n\nGAIA connects HubSpot and Zoom so every sales call is captured in the CRM automatically. When a Zoom meeting includes a HubSpot contact, GAIA logs the call as a CRM activity and generates a summary from the transcript. Committed action items become HubSpot tasks, and key conversation points are attached to the deal record so anyone on the account team can get up to speed without listening to the recording.\n\nThis integration is built for sales teams that want complete CRM activity timelines, managers who need call visibility without listening to recordings, and account teams who need to hand off deals with full conversation context.",
    useCases: [
      {
        title: "Log Zoom calls as HubSpot activities automatically",
        description:
          "When a Zoom meeting includes a HubSpot contact's email address, GAIA logs the call as a meeting activity on the contact and deal record, including the call duration, attendees, and a link to the recording.",
      },
      {
        title: "Post call summaries to HubSpot deal records",
        description:
          "After a Zoom call, GAIA generates a structured summary from the meeting transcript and posts it to the linked HubSpot deal record as a note, giving the entire account team immediate access to call outcomes.",
      },
      {
        title: "Create follow-up tasks from action items",
        description:
          "GAIA analyzes Zoom call transcripts for commitments and action items — send a proposal, schedule a demo, loop in a technical contact — and creates corresponding HubSpot tasks with due dates for the responsible rep.",
      },
      {
        title: "Advance deal stage from call outcomes",
        description:
          "When a Zoom call summary indicates a specific outcome — verbal agreement, request for contract, demo completed — GAIA can advance the HubSpot deal to the next pipeline stage automatically.",
      },
      {
        title: "Manager call coaching alerts",
        description:
          "GAIA monitors Zoom call summaries for coaching signals — long monologues, no next steps agreed, competitor mentions — and creates a HubSpot task for the sales manager to review the recording and provide feedback.",
      },
    ],
    howItWorks: [
      {
        step: "Connect HubSpot and Zoom to GAIA",
        description:
          "Authorize GAIA to access your HubSpot portal and Zoom account. GAIA matches Zoom meeting attendees to HubSpot contact records by email address.",
      },
      {
        step: "Configure logging rules and follow-up templates",
        description:
          "Define which Zoom meetings should be logged to HubSpot — by attendee domain, meeting type, or calendar invitation — and set the task templates GAIA creates from call action items.",
      },
      {
        step: "GAIA logs every call and drives follow-through",
        description:
          "GAIA monitors Zoom for completed meetings, logs them to HubSpot, generates summaries, and creates follow-up tasks automatically so your CRM reflects every sales conversation and every commitment made.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA require Zoom cloud recording for call logging?",
        answer:
          "Basic call logging — duration, attendees, date — works without recording. Generating call summaries and extracting action items requires Zoom transcription or cloud recording to be enabled on the meeting.",
      },
      {
        question:
          "Can GAIA match Zoom calls to the correct HubSpot deal when a contact has multiple open deals?",
        answer:
          "Yes. GAIA uses the deal currently in an active stage for the contact by default, and you can configure it to prompt the rep to confirm the deal association when ambiguity exists.",
      },
      {
        question:
          "Can managers access Zoom call summaries for their reps from HubSpot?",
        answer:
          "Yes. Call summaries are logged as HubSpot note activities on the deal or contact record, so anyone with CRM access — including managers and account team members — can read the summary without accessing Zoom.",
      },
    ],
  },

  "salesforce-slack": {
    slug: "salesforce-slack",
    toolA: "Salesforce",
    toolASlug: "salesforce",
    toolB: "Slack",
    toolBSlug: "slack",
    tagline:
      "Post deal alerts to Slack and update Salesforce records from Slack messages",
    metaTitle:
      "Salesforce + Slack Automation - Real-Time Deal Alerts in Slack | GAIA",
    metaDescription:
      "Connect Salesforce and Slack with GAIA. Get instant deal stage alerts in Slack, update CRM records from Slack messages, and keep your revenue team aligned without leaving their primary communication tool.",
    keywords: [
      "Salesforce Slack integration",
      "Salesforce Slack automation",
      "deal alerts Slack",
      "connect Salesforce and Slack",
      "CRM Slack workflow",
      "revenue team Slack alerts",
    ],
    intro:
      "Revenue teams live in Slack but their deal data lives in Salesforce, and the gap between the two means critical deal events go unnoticed until someone checks the CRM. A deal closes and the broader team finds out hours later. A deal goes cold and no one escalates because the signal was buried in a Salesforce report nobody opened.\n\nGAIA connects Salesforce and Slack so deal intelligence flows into the conversations where decisions are made. Won deals trigger immediate Slack announcements to the revenue channel. At-risk opportunities generate alerts to the account owner. High-value pipeline updates surface in leadership channels. And when a rep needs to update Salesforce quickly, they can do it from Slack without switching tabs.\n\nThis integration is essential for high-velocity sales teams where deal momentum depends on real-time information, and for revenue leaders who need pipeline visibility without pulling reports manually.",
    useCases: [
      {
        title: "Celebrate closed deals in Slack instantly",
        description:
          "When a Salesforce opportunity is marked Closed Won, GAIA posts a deal win announcement to the revenue Slack channel with the deal name, value, account, and rep, giving the team immediate visibility and morale.",
      },
      {
        title: "Alert account owners about at-risk deals",
        description:
          "When a Salesforce deal's close date passes without progressing or is moved back multiple times, GAIA sends a Slack DM to the account owner and a channel alert to the sales manager to trigger intervention.",
      },
      {
        title: "Update Salesforce fields from Slack",
        description:
          "Reps can message GAIA in Slack to update Salesforce deal fields — close date, stage, next step, amount — without opening Salesforce, reducing CRM friction for field reps and fast-moving deal cycles.",
      },
      {
        title: "Weekly pipeline digest in Slack",
        description:
          "GAIA posts a structured weekly pipeline digest to the revenue Slack channel listing deals by stage, total pipeline value, deals closing this week, and deals that have not been updated in over a week.",
      },
      {
        title: "New lead alerts for high-priority accounts",
        description:
          "When a new Salesforce lead is created for a target account or high-value company, GAIA posts an immediate alert to the designated Slack channel so the right rep can respond before the lead goes cold.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Salesforce and Slack to GAIA",
        description:
          "Authorize GAIA to access your Salesforce organization and Slack workspace. Map Salesforce pipeline stages and record types to Slack channels for notifications.",
      },
      {
        step: "Configure alert rules and channel mappings",
        description:
          "Define which Salesforce events — stage changes, deal wins, overdue dates, new leads — trigger Slack messages, and specify the target channel or user for each alert type.",
      },
      {
        step: "GAIA keeps your revenue team informed in real time",
        description:
          "GAIA monitors Salesforce for deal events and posts structured notifications to Slack immediately, while also accepting CRM update requests from Slack to keep deal data current.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA post Salesforce alerts to different Slack channels for different deal sizes?",
        answer:
          "Yes. You can configure GAIA to route alerts based on deal value — enterprise deals to a dedicated channel, SMB deals to another — so the right audience sees each notification.",
      },
      {
        question: "What Salesforce fields can be updated from Slack?",
        answer:
          "GAIA supports updating standard Salesforce fields — stage, close date, amount, next step, description — and custom fields via natural language commands in Slack. The update is reflected in Salesforce immediately.",
      },
      {
        question:
          "Can GAIA notify the full account team, not just the deal owner?",
        answer:
          "Yes. GAIA can notify all Slack users mapped to the Salesforce account team for a given deal, ensuring everyone with a stake in the account is informed of significant events.",
      },
    ],
  },

  "salesforce-gmail": {
    slug: "salesforce-gmail",
    toolA: "Salesforce",
    toolASlug: "salesforce",
    toolB: "Gmail",
    toolBSlug: "gmail",
    tagline:
      "Log emails to Salesforce automatically and create leads from Gmail replies",
    metaTitle:
      "Salesforce + Gmail Automation - Log Every Email to CRM Automatically | GAIA",
    metaDescription:
      "Connect Salesforce and Gmail with GAIA. Automatically log client emails to Salesforce deal and contact records, create leads from inbound email replies, and keep your CRM activity timeline complete without manual entry.",
    keywords: [
      "Salesforce Gmail integration",
      "Salesforce Gmail automation",
      "log emails Salesforce",
      "Gmail Salesforce sync",
      "connect Salesforce and Gmail",
      "email CRM logging automation",
    ],
    intro:
      "Sales reps send and receive dozens of client emails every day in Gmail, but those emails rarely make it into Salesforce without a deliberate BCC to the CRM email address or a manual activity log. The result is a Salesforce record that understates contact frequency, misses key conversation threads, and fails to capture the email trail that might be critical for deal reviews or handoffs.\n\nGAIA connects Salesforce and Gmail so every relevant client email is logged to the correct CRM record automatically. When a Gmail message is sent to or received from a Salesforce contact, GAIA logs the email as an activity on the contact and opportunity record. When a promising email reply arrives from an unknown address, GAIA can create a new lead in Salesforce so the prospect enters the pipeline immediately.\n\nThis integration is built for sales teams that want complete CRM activity timelines without requiring reps to remember to log emails, and for revenue operations teams who need accurate engagement data for pipeline analysis and forecasting.",
    useCases: [
      {
        title: "Log Gmail emails to Salesforce contact records automatically",
        description:
          "When a Gmail email is sent to or received from a Salesforce contact's email address, GAIA logs the email as an activity on the contact record with the subject, timestamp, and direction, keeping the CRM timeline complete.",
      },
      {
        title: "Create Salesforce leads from inbound email replies",
        description:
          "When an inbound Gmail reply arrives from an email address not in Salesforce, GAIA creates a new lead with the sender's name, email, company, and the email content as the lead description, triggering immediate follow-up.",
      },
      {
        title: "Attach emails to Salesforce opportunity records",
        description:
          "GAIA matches Gmail emails to the relevant Salesforce opportunity based on the contact association and logs the email on both the contact and the deal record, giving account teams full deal email history in the CRM.",
      },
      {
        title: "Identify unresponsive prospects from email gaps",
        description:
          "GAIA monitors Gmail activity for Salesforce contacts and alerts the rep when a prospect has not replied to an email in a configurable number of days, prompting follow-up before the deal goes cold.",
      },
      {
        title: "Draft Salesforce-informed email responses",
        description:
          "When a client email arrives, ask GAIA to draft a reply using CRM context — deal stage, last meeting notes, open tasks — so the response is personalized and accurate without the rep switching to Salesforce to look up details.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Salesforce and Gmail to GAIA",
        description:
          "Authorize GAIA to access your Salesforce organization and Gmail account. GAIA matches Gmail sender and recipient addresses to Salesforce contact and lead records automatically.",
      },
      {
        step: "Configure logging rules and lead creation criteria",
        description:
          "Define which Gmail emails to log — by contact domain, label, or thread — and set the criteria for when an unknown email address should create a new Salesforce lead versus be ignored.",
      },
      {
        step: "GAIA keeps every client email in your CRM",
        description:
          "GAIA monitors Gmail for inbound and outbound messages matching Salesforce contacts and logs them automatically, while also creating leads from high-potential inbound emails so no prospect slips through.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA log every email or only emails to Salesforce contacts?",
        answer:
          "By default, GAIA logs only emails where the sender or recipient matches a Salesforce contact or lead email address. You can also configure it to log emails from specific domains or Gmail labels.",
      },
      {
        question:
          "Can GAIA attach the full email body to Salesforce or just a summary?",
        answer:
          "GAIA logs the email subject, timestamp, direction, and a configurable amount of the body text to the Salesforce activity record. Full email bodies can be included if your Salesforce storage limits allow.",
      },
      {
        question:
          "What happens when an email involves multiple Salesforce contacts?",
        answer:
          "GAIA logs the email to all matching Salesforce contact records in the thread and associates it with the relevant open opportunity for each contact, ensuring no touchpoint is missed on multi-stakeholder deals.",
      },
    ],
  },

  "salesforce-notion": {
    slug: "salesforce-notion",
    toolA: "Salesforce",
    toolASlug: "salesforce",
    toolB: "Notion",
    toolBSlug: "notion",
    tagline:
      "Sync Salesforce deal data to Notion and document account strategies collaboratively",
    metaTitle:
      "Salesforce + Notion Automation - Bring CRM Data into Your Notion Workspace | GAIA",
    metaDescription:
      "Connect Salesforce and Notion with GAIA. Automatically create Notion deal pages from Salesforce opportunities, sync pipeline data to Notion databases, and keep account strategies aligned with live CRM data.",
    keywords: [
      "Salesforce Notion integration",
      "Salesforce Notion sync",
      "CRM Notion automation",
      "connect Salesforce and Notion",
      "deal documentation Notion Salesforce",
      "account strategy workspace",
    ],
    intro:
      "Enterprise sales teams manage complex deals that require rich documentation — account strategies, stakeholder maps, competitive positioning, executive briefings — that cannot live inside Salesforce's structured fields. Notion is where this content gets written, but it stays disconnected from the live deal data in Salesforce. Account documents go stale, pipeline dashboards in Notion require manual updates, and new team members cannot find the strategic context built up during the deal cycle.\n\nGAIA connects Salesforce and Notion so deal intelligence flows between CRM and knowledge base automatically. When a Salesforce opportunity is created, GAIA creates a Notion deal page from an account strategy template pre-populated with CRM data. As the deal progresses, GAIA updates the Notion page with stage changes and key metrics. When account strategies or meeting notes are added to Notion, GAIA can log key outcomes back to Salesforce.\n\nThis integration is designed for enterprise sales teams, strategic account managers, and revenue operations teams that manage complex, multi-stakeholder deals requiring both structured CRM tracking and rich collaborative documentation.",
    useCases: [
      {
        title: "Create Notion deal pages from Salesforce opportunities",
        description:
          "When a Salesforce opportunity is created or reaches a qualifying stage, GAIA creates a Notion deal page from an account strategy template, pre-filled with opportunity name, value, stage, contacts, and close date.",
      },
      {
        title: "Sync pipeline stages and key metrics to Notion databases",
        description:
          "GAIA maintains a Notion database of Salesforce opportunities, keeping stage, value, close date, and rep fields synchronized so pipeline dashboards in Notion always reflect live CRM data.",
      },
      {
        title:
          "Document stakeholder maps in Notion with Salesforce contact data",
        description:
          "GAIA pulls Salesforce contact records associated with an opportunity and populates the stakeholder map section of the Notion deal page, giving the account team a collaborative space to build relationship strategies.",
      },
      {
        title: "Log Notion meeting notes to Salesforce activities",
        description:
          "When a meeting notes section is updated on a Notion deal page, GAIA creates a corresponding activity note on the Salesforce opportunity, keeping the CRM timeline complete without requiring reps to log in two places.",
      },
      {
        title: "Executive briefing generation",
        description:
          "Before a high-value deal review, GAIA compiles a Notion executive briefing page pulling Salesforce deal data, activity history, and risk signals alongside the strategic notes from the Notion deal page.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Salesforce and Notion to GAIA",
        description:
          "Authorize GAIA to access your Salesforce organization and Notion workspace. Map Salesforce opportunity fields to Notion database properties and deal page sections.",
      },
      {
        step: "Configure page templates and sync triggers",
        description:
          "Define the Notion deal page template, choose which Salesforce pipeline stages trigger page creation or updates, and set which Notion changes should log back to Salesforce as activities.",
      },
      {
        step: "GAIA keeps strategy and CRM aligned",
        description:
          "GAIA monitors Salesforce for deal changes and Notion for document updates, propagating data in both directions so your strategic documentation always reflects live deal reality.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create different Notion templates for different Salesforce deal types?",
        answer:
          "Yes. You can configure GAIA to select Notion page templates based on Salesforce opportunity type, record type, or product line, ensuring the right strategic framework is applied to each deal.",
      },
      {
        question:
          "How often does GAIA sync Salesforce data to the Notion pipeline database?",
        answer:
          "GAIA syncs on configurable intervals — real-time on stage changes, or on a scheduled basis for field updates. You can also trigger a manual sync on demand for a specific opportunity.",
      },
      {
        question:
          "Can multiple team members collaborate on a Notion deal page while GAIA syncs CRM data?",
        answer:
          "Yes. GAIA writes to specific structured sections of the Notion deal page — CRM-synced fields, activity logs — while leaving collaborative sections free for the account team to edit without conflict.",
      },
    ],
  },

  "salesforce-asana": {
    slug: "salesforce-asana",
    toolA: "Salesforce",
    toolASlug: "salesforce",
    toolB: "Asana",
    toolBSlug: "asana",
    tagline:
      "Create Asana projects from Salesforce opportunities and sync delivery back to CRM",
    metaTitle:
      "Salesforce + Asana Automation - From Closed Deal to Delivery Project | GAIA",
    metaDescription:
      "Bridge sales and delivery with GAIA. Automatically create Asana projects when Salesforce deals close, sync project milestones back to CRM records, and keep account managers and delivery teams working from shared data.",
    keywords: [
      "Salesforce Asana integration",
      "Salesforce Asana automation",
      "deal to project workflow",
      "connect Salesforce and Asana",
      "sales delivery alignment",
      "CRM project management bridge",
    ],
    intro:
      "Closing a deal in Salesforce is only the beginning — the delivery team then needs to execute on the commitments made during the sale. Without automation, the handoff from Salesforce to Asana is manual: someone copies deal details into a new project, assigns tasks by hand, and sets deadlines without referencing the contract dates in Salesforce. The delivery team starts every engagement with incomplete information.\n\nGAIA automates the Salesforce-to-Asana handoff so delivery begins the moment a deal closes. When a Salesforce opportunity reaches Closed Won, GAIA creates a structured Asana project pre-populated with all relevant deal data — company name, scope, contract dates, assigned delivery lead — and assigns tasks based on your delivery playbook. As the project progresses, GAIA reports milestones back to Salesforce so the account team always knows where delivery stands.\n\nThis integration is critical for professional services teams, SaaS implementation teams, and any organization where closing a deal immediately creates structured project work that must be tracked in Asana.",
    useCases: [
      {
        title: "Auto-create Asana projects from Salesforce Closed Won deals",
        description:
          "When a Salesforce opportunity is marked Closed Won, GAIA immediately creates an Asana project from the appropriate delivery template, pre-fills account details, sets contract-aligned deadlines, and assigns the delivery team.",
      },
      {
        title: "Sync Salesforce contract data to Asana project fields",
        description:
          "GAIA maps Salesforce deal fields — product, contract value, implementation timeline, primary contact — to Asana custom project fields so the delivery team has the sales context they need without CRM access.",
      },
      {
        title: "Report Asana delivery milestones to Salesforce",
        description:
          "When key Asana project milestones are completed, GAIA logs them as Salesforce activity records on the linked account and opportunity, giving account managers delivery status visibility in their CRM.",
      },
      {
        title: "Alert account managers about at-risk deliveries",
        description:
          "When an Asana project is flagged at-risk or falls behind schedule, GAIA creates a Salesforce task for the account owner to proactively communicate with the client and manage expectations.",
      },
      {
        title: "Generate renewal opportunities from project completion",
        description:
          "When an Asana project is marked complete, GAIA creates a new Salesforce opportunity for renewal or expansion, pre-populated with the account details and a renewal timeline based on the original contract.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Salesforce and Asana to GAIA",
        description:
          "Authorize GAIA to access your Salesforce organization and Asana workspace. Map Salesforce opportunity fields to Asana project templates and define the delivery team assignment rules.",
      },
      {
        step: "Configure handoff triggers and templates",
        description:
          "Define which Salesforce pipeline stages trigger Asana project creation, which Asana template to use per deal type, and which Asana milestone completions report back to Salesforce.",
      },
      {
        step: "GAIA automates the sales-to-delivery handoff",
        description:
          "GAIA monitors Salesforce for deal closures and creates Asana projects instantly, while also reporting delivery progress back to Salesforce so account managers stay informed without interrupting the delivery team.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA select different Asana templates based on Salesforce deal attributes?",
        answer:
          "Yes. Configure GAIA to select Asana templates based on Salesforce fields such as product line, contract size, or customer segment, so the right delivery structure is applied to each type of engagement.",
      },
      {
        question:
          "What happens if a Salesforce deal is reopened after the Asana project has started?",
        answer:
          "GAIA can detect deal stage reversals and notify the Asana project manager. The Asana project is not automatically deleted — a human decision is needed to pause, cancel, or continue delivery work.",
      },
      {
        question:
          "Can account managers in Salesforce see Asana project task-level details?",
        answer:
          "GAIA logs milestone-level updates to Salesforce rather than individual task details, keeping the CRM record high-level. Account managers can request a project summary from GAIA at any time for more detail.",
      },
    ],
  },

  "salesforce-google-calendar": {
    slug: "salesforce-google-calendar",
    toolA: "Salesforce",
    toolASlug: "salesforce",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Sync sales calls and meetings with Salesforce CRM activities automatically",
    metaTitle:
      "Salesforce + Google Calendar Automation - Log Sales Meetings to CRM | GAIA",
    metaDescription:
      "Connect Salesforce and Google Calendar with GAIA. Automatically log client meetings as CRM activities, create follow-up tasks from calendar events, and keep your Salesforce activity timeline complete without manual entry.",
    keywords: [
      "Salesforce Google Calendar integration",
      "Salesforce calendar sync",
      "sales meeting CRM logging",
      "connect Salesforce and Google Calendar",
      "Salesforce calendar automation",
      "activity logging Salesforce",
    ],
    intro:
      "Account executives and sales reps schedule and attend client meetings in Google Calendar every day, but those meetings only help the team if they are captured in Salesforce. Manual CRM logging is time-consuming and inconsistently done — reps log some meetings, forget others, and rarely capture enough detail for the next person who inherits the account to understand the relationship history.\n\nGAIA connects Salesforce and Google Calendar so every client meeting is automatically recorded in the CRM with zero manual effort from the rep. When a Google Calendar event involves a Salesforce contact, GAIA creates the activity record, attaches meeting notes, and after the meeting generates follow-up tasks based on what was agreed. The Salesforce timeline becomes a complete, accurate record of all client touchpoints without relying on rep discipline.\n\nThis integration is essential for enterprise sales teams managing complex deal cycles, customer success managers with large books of business, and revenue operations teams that need accurate activity data for pipeline analysis and forecasting.",
    useCases: [
      {
        title: "Log Google Calendar meetings as Salesforce activities",
        description:
          "When a Google Calendar event includes a Salesforce contact's email address, GAIA automatically creates a meeting activity on the Salesforce contact and opportunity record with attendees, date, and duration.",
      },
      {
        title: "Create Salesforce follow-up tasks after meetings",
        description:
          "When a calendar meeting with a Salesforce contact ends, GAIA creates a follow-up task on the opportunity with a configurable due date, prompting the rep to send notes or take the next agreed action.",
      },
      {
        title: "Attach pre-meeting research to Salesforce records",
        description:
          "Before a scheduled meeting with a Salesforce contact, GAIA compiles a meeting brief from CRM data — deal stage, last activities, open tasks — and attaches it to the calendar event so the rep arrives prepared.",
      },
      {
        title: "Identify deal engagement gaps",
        description:
          "GAIA monitors Salesforce opportunities for contacts who have not had a calendar meeting scheduled in a configurable number of days and alerts the rep, ensuring high-value deals maintain appropriate meeting cadence.",
      },
      {
        title: "Schedule Salesforce-informed follow-up meetings",
        description:
          "When a Salesforce task requires a follow-up meeting, GAIA checks the rep's Google Calendar availability and the contact's suggested times to create a meeting invite automatically, reducing scheduling back-and-forth.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Salesforce and Google Calendar to GAIA",
        description:
          "Authorize GAIA to access your Salesforce organization and Google Calendar accounts. GAIA matches calendar attendee email addresses to Salesforce contact and lead records automatically.",
      },
      {
        step: "Configure logging rules and follow-up automation",
        description:
          "Define which calendar events trigger Salesforce activity creation — by attendee domain, calendar, or event type — and set the follow-up task template that GAIA creates after each meeting.",
      },
      {
        step: "GAIA keeps your CRM timeline complete",
        description:
          "GAIA monitors Google Calendar for client meetings and logs them to Salesforce automatically, creating follow-up tasks and meeting briefs so your CRM accurately reflects every sales interaction.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA log internal team meetings to Salesforce or only external client meetings?",
        answer:
          "GAIA logs only meetings where attendees match Salesforce contact or lead email addresses by default, excluding internal team meetings from CRM activity logging to keep the timeline relevant.",
      },
      {
        question:
          "Can GAIA handle calendar meetings where multiple Salesforce contacts attend?",
        answer:
          "Yes. GAIA logs the meeting to all matching Salesforce contact records in the event and associates the activity with the relevant open opportunity for each contact.",
      },
      {
        question:
          "What happens when a calendar meeting is cancelled after being logged to Salesforce?",
        answer:
          "GAIA updates the Salesforce activity record to reflect the cancellation and can optionally create a reschedule task on the opportunity so the rep follows up to book a new time.",
      },
    ],
  },

  "salesforce-drive": {
    slug: "salesforce-drive",
    toolA: "Salesforce",
    toolASlug: "salesforce",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach Drive contracts and proposals to Salesforce deals automatically",
    metaTitle:
      "Salesforce + Google Drive Automation - Link Sales Documents to CRM | GAIA",
    metaDescription:
      "Connect Salesforce and Google Drive with GAIA. Automatically create Drive folders for Salesforce opportunities, attach proposals and contracts to deal records, and keep all sales documents organized and accessible from your CRM.",
    keywords: [
      "Salesforce Google Drive integration",
      "Salesforce Drive automation",
      "attach contracts Salesforce",
      "connect Salesforce and Google Drive",
      "deal document management CRM",
      "sales document workflow",
    ],
    intro:
      "Enterprise sales deals generate extensive documentation — proposals, NDAs, statements of work, contracts, legal amendments — that lives in Google Drive while the deal record lives in Salesforce. Without automation, reps spend time searching for the latest version of a proposal, and document links on Salesforce records go stale when files are moved or renamed in Drive.\n\nGAIA connects Salesforce and Google Drive so deal documentation is always organized and accessible from the CRM. When a Salesforce opportunity is created, GAIA creates a structured Drive folder for the account. As documents are created or signed in Drive, GAIA attaches them to the Salesforce deal record with the correct document type and version. When a contract is executed, GAIA advances the Salesforce deal stage automatically.\n\nThis integration is essential for enterprise sales teams managing complex documentation cycles, legal and procurement teams who need audit trails of contract versions, and revenue operations teams who need document accessibility to be automatic rather than reliant on individual rep habits.",
    useCases: [
      {
        title: "Create Drive account folders from Salesforce opportunities",
        description:
          "When a Salesforce opportunity is created or reaches a qualifying stage, GAIA creates a structured Google Drive folder for the account with subfolders for proposals, contracts, legal documents, and supporting materials.",
      },
      {
        title: "Auto-attach Drive documents to Salesforce deal records",
        description:
          "When a proposal, contract, or SOW is added to an account's Drive folder, GAIA automatically attaches the file to the linked Salesforce opportunity record with the document type labeled, keeping deal files accessible from the CRM.",
      },
      {
        title: "Advance deal stage when contracts are signed",
        description:
          "When an executed contract is added to the signed documents subfolder in Drive, GAIA advances the Salesforce opportunity to Closed Won, records the contract date, and creates the post-sale handoff task automatically.",
      },
      {
        title: "Notify reps when documents require action",
        description:
          "When a legal team member adds comments or a revised version of a contract to Drive, GAIA creates a Salesforce task for the account executive to review and respond, keeping the contract cycle moving.",
      },
      {
        title: "Generate proposals from Salesforce data",
        description:
          "When a Salesforce opportunity reaches the proposal stage, GAIA creates a Drive proposal document from a template pre-filled with opportunity data — company name, products, pricing, key contacts — saving the rep manual document setup time.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Salesforce and Google Drive to GAIA",
        description:
          "Authorize GAIA to access your Salesforce organization and Google Drive. Specify the Drive root folder where account folders should be created and the Salesforce pipelines to monitor.",
      },
      {
        step: "Configure folder templates and document rules",
        description:
          "Define the Drive folder structure for new opportunities and the rules GAIA uses to attach files to Salesforce records — by document type, subfolder location, or file naming convention.",
      },
      {
        step: "GAIA keeps deal documents organized and CRM-linked",
        description:
          "GAIA monitors both Salesforce and Drive for changes, creating folders, attaching documents, advancing deal stages, and notifying reps so your CRM always reflects the current state of your deal documentation.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA generate a proposal draft from a Salesforce opportunity on demand?",
        answer:
          "Yes. Ask GAIA to generate a proposal for a specific Salesforce opportunity and it will create a Drive document from your template, populate it with opportunity and contact data from Salesforce, and attach it to the deal record.",
      },
      {
        question:
          "Does GAIA support multiple document versions on the same Salesforce record?",
        answer:
          "Yes. GAIA attaches each document version to the Salesforce record with a version label and timestamp. Previous versions remain accessible and the latest version is flagged as current.",
      },
      {
        question:
          "Can GAIA enforce document naming conventions when creating Drive files?",
        answer:
          "Yes. You can define file naming templates that GAIA applies when creating Drive documents from Salesforce data — for example, using opportunity name, account, and date in the file name for consistent organization.",
      },
    ],
  },
};
