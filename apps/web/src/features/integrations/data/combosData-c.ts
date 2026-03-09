import type { IntegrationCombo } from "./combosData";

export const combosBatchC: Record<string, IntegrationCombo> = {
  "github-todoist": {
    slug: "github-todoist",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Todoist",
    toolBSlug: "todoist",
    tagline: "Turn GitHub issues and PRs into Todoist tasks automatically",
    metaTitle: "GitHub + Todoist Automation - Sync Dev Work with Tasks | GAIA",
    metaDescription:
      "Connect GitHub and Todoist with GAIA. Auto-create Todoist tasks from GitHub issues and PRs, track dev work alongside personal tasks, and never lose sight of coding to-dos.",
    keywords: [
      "GitHub Todoist integration",
      "GitHub Todoist automation",
      "create Todoist tasks from GitHub issues",
      "sync GitHub with Todoist",
      "connect GitHub and Todoist",
      "developer task management",
    ],
    intro:
      "Developers often juggle GitHub issues and pull requests alongside personal tasks in Todoist, but the two systems never talk to each other. An issue gets assigned in GitHub, but it never makes it onto your Todoist today list. A PR review sits waiting while you work through a Todoist task board that has no awareness of your code queue. The result is context-switching overhead and work falling through the cracks between two separate workflows.\n\nGAIA connects GitHub and Todoist so your development work and personal task management stay aligned. When a GitHub issue is assigned to you or a PR requests your review, GAIA can instantly create a corresponding Todoist task with the right project, priority, and due date. When you close the issue or merge the PR, GAIA marks the Todoist task complete so your list stays clean without manual updates.\n\nThis integration is especially useful for solo developers and small teams who rely on Todoist for personal productivity but live in GitHub for actual development. Instead of maintaining two separate to-do systems, you get a single Todoist inbox that reflects everything on your plate — code work included.",
    useCases: [
      {
        title: "Auto-create tasks from assigned GitHub issues",
        description:
          "Whenever a GitHub issue is assigned to you, GAIA creates a matching Todoist task in your developer project with the issue title, a link back to GitHub, and a due date derived from any milestone attached to the issue.",
      },
      {
        title: "Add PR review requests to your Todoist inbox",
        description:
          "When a teammate requests your review on a pull request, GAIA adds a high-priority Todoist task so code reviews never get buried under other notifications. The task includes the PR title, author, and direct link.",
      },
      {
        title: "Close Todoist tasks when issues are resolved",
        description:
          "GAIA watches GitHub for issue closures and PR merges, then automatically marks the corresponding Todoist tasks complete. Your task list reflects the real state of your work without any manual cleanup.",
      },
      {
        title: "Daily GitHub digest as a Todoist task",
        description:
          "Each morning GAIA creates a single Todoist task summarizing your open GitHub issues, pending reviews, and unresolved PR comments so you start the day with a clear picture of what needs attention in code.",
      },
      {
        title: "Milestone deadline reminders in Todoist",
        description:
          "GAIA monitors GitHub milestone due dates and creates Todoist reminder tasks several days before deadlines so you can plan your development sprint without having to check GitHub project boards manually.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Todoist to GAIA",
        description:
          "Authenticate your GitHub account and Todoist workspace in GAIA's integration settings using OAuth. GAIA only requests the permissions it needs — repository read access for GitHub and task write access for Todoist.",
      },
      {
        step: "Configure your sync preferences",
        description:
          "Tell GAIA which GitHub repositories to watch, which Todoist project should receive the tasks, how to map GitHub labels to Todoist priorities, and when due dates should be set. Natural language rules work here.",
      },
      {
        step: "GAIA keeps both systems in sync automatically",
        description:
          "From that point on, GAIA monitors GitHub events in real time and updates Todoist accordingly. You can also ask GAIA conversationally to create, update, or close tasks across both platforms at any time.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync tasks from multiple GitHub repositories into Todoist?",
        answer:
          "Yes. You can connect multiple GitHub repositories to a single GAIA workspace and route tasks from each repository into the same or different Todoist projects. You can also filter by repository, label, or assignee so only relevant issues become tasks.",
      },
      {
        question:
          "What happens to a Todoist task if the GitHub issue is reopened?",
        answer:
          "GAIA can detect issue reopens and either recreate the Todoist task or reopen it if Todoist supports that state, depending on your preferences. You can configure GAIA to notify you instead of taking automatic action if you prefer manual control.",
      },
      {
        question: "Does GAIA work with GitHub Projects as well as issues?",
        answer:
          "GAIA primarily syncs GitHub issues and pull requests. GitHub Projects columns and card status can inform task creation logic, but full bi-directional Projects sync is handled through GAIA's broader project management integrations.",
      },
    ],
  },

  "github-clickup": {
    slug: "github-clickup",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline: "Link GitHub PRs to ClickUp tasks and auto-update status on merge",
    metaTitle:
      "GitHub + ClickUp Automation - Sync Code with Project Tasks | GAIA",
    metaDescription:
      "Automate GitHub and ClickUp with GAIA. Link pull requests to ClickUp tasks, move tasks through statuses as PRs progress, and keep engineering and project teams aligned without manual updates.",
    keywords: [
      "GitHub ClickUp integration",
      "GitHub ClickUp automation",
      "link GitHub PRs to ClickUp tasks",
      "sync GitHub with ClickUp",
      "connect GitHub and ClickUp",
      "engineering project management sync",
    ],
    intro:
      'Engineering teams use GitHub for code and ClickUp for project management, but keeping the two in sync is a constant manual chore. A developer merges a PR but forgets to update the ClickUp task status. A project manager moves a task to "In Review" without knowing the PR was already approved. The gap between where the code lives and where the project plan lives creates confusion, duplicated status meetings, and a project board that never reflects reality.\n\nGAIA bridges GitHub and ClickUp so code activity automatically drives task status updates. When a developer opens a pull request linked to a ClickUp task, GAIA moves the task to "In Review." When the PR merges, GAIA transitions the task to "Done" and notifies the assignee. When a PR is closed without merging, GAIA can revert the task status and leave a comment explaining why. The project board stays accurate without anyone having to remember to update it.\n\nThis integration is ideal for software teams that plan work in ClickUp and execute in GitHub. Product managers get a real-time view of engineering progress directly in ClickUp, while developers focus on writing code rather than updating tickets.',
    useCases: [
      {
        title: "Auto-move ClickUp tasks when PRs are opened",
        description:
          'When a developer opens a pull request and references a ClickUp task ID in the PR title or description, GAIA automatically moves that task to the "In Review" status so project managers see live development progress in ClickUp.',
      },
      {
        title: "Complete ClickUp tasks on PR merge",
        description:
          "When a pull request merges to the main branch, GAIA marks the linked ClickUp task as complete, sets the resolved date, and posts a comment with the merge commit reference so there is a clear audit trail from task to code.",
      },
      {
        title: "Create ClickUp subtasks from GitHub review comments",
        description:
          "When a code reviewer leaves a change request on a PR, GAIA can create ClickUp subtasks for each requested change so the work is tracked in the project board and the developer has a structured checklist to address before re-requesting review.",
      },
      {
        title: "Sync GitHub milestones with ClickUp sprints",
        description:
          "GAIA maps GitHub milestones to ClickUp sprints, keeping due dates consistent and automatically moving incomplete tasks to the next sprint when a milestone closes with open issues remaining.",
      },
      {
        title: "Notify ClickUp task followers on PR failures",
        description:
          "When a GitHub Actions CI run fails on a PR, GAIA posts a comment on the linked ClickUp task alerting the team that the build is broken, along with a link to the failed run so blockers are visible in the project board immediately.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and ClickUp to GAIA",
        description:
          "Authenticate your GitHub organization and ClickUp workspace through GAIA's integrations panel. Select which repositories and ClickUp spaces or lists should be linked for automated syncing.",
      },
      {
        step: "Define your status mapping rules",
        description:
          "Configure how GitHub PR states map to ClickUp task statuses. Tell GAIA which ClickUp list to use, how to identify the task ID from PR descriptions or branch names, and which status transitions each GitHub event should trigger.",
      },
      {
        step: "GAIA syncs code and project status automatically",
        description:
          "GAIA listens to GitHub webhook events and updates ClickUp tasks in real time. Your ClickUp board becomes a live reflection of development progress without any manual status updates from the engineering team.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA identify which ClickUp task to update from a GitHub PR?",
        answer:
          "GAIA can match tasks using a ClickUp task ID included in the PR title, description, or branch name (e.g., CU-abc123). You can also configure GAIA to match by branch naming conventions or labels. If no match is found, GAIA can create a new ClickUp task from the PR instead.",
      },
      {
        question:
          "Can GAIA handle multiple ClickUp lists across different GitHub repositories?",
        answer:
          "Yes. You can map each GitHub repository to a specific ClickUp list or space, so PRs from the frontend repo update the frontend ClickUp list while backend PRs update a separate list. GAIA manages all mappings from a single configuration.",
      },
      {
        question: "Does this integration work with ClickUp's custom statuses?",
        answer:
          'Yes. GAIA reads your ClickUp workspace\'s custom status definitions and lets you map GitHub events to any status in your workflow — whether that\'s "Code Review," "QA Testing," "Deployed," or any other custom status your team has defined.',
      },
    ],
  },

  "github-figma": {
    slug: "github-figma",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Link design specs to code PRs and notify designers when code ships",
    metaTitle:
      "GitHub + Figma Automation - Bridge Design and Engineering | GAIA",
    metaDescription:
      "Connect GitHub and Figma with GAIA. Link Figma design specs to GitHub pull requests, notify designers when related code merges, and keep design and engineering aligned throughout the build cycle.",
    keywords: [
      "GitHub Figma integration",
      "GitHub Figma automation",
      "link Figma designs to GitHub PRs",
      "design engineering workflow",
      "connect GitHub and Figma",
      "design handoff automation",
    ],
    intro:
      "Design and engineering teams work in parallel — designers in Figma, developers in GitHub — but the handoff between the two is rarely smooth. Developers hunt for the right Figma frame while the designer has already moved to the next screen. Designers have no idea when their designs have shipped to production. Reviews happen in separate tools with no shared context, and version mismatches between the design file and the live implementation go unnoticed until QA catches them.\n\nGAIA connects GitHub and Figma to create a continuous link between design specifications and the code that implements them. When a developer opens a pull request, GAIA can automatically attach the relevant Figma frame or component as a comment on the PR so reviewers can compare design intent against implementation without leaving GitHub. When that PR merges, GAIA notifies the designer in Figma (or via their preferred channel) so they can verify the implementation and sign off.\n\nThis integration is a game-changer for product teams practicing design-led development. Designers stay in the loop on engineering progress without polling developers, developers always have the right spec attached to their PR, and nothing ships that the design team hasn't been able to review.",
    useCases: [
      {
        title: "Attach Figma specs to pull requests automatically",
        description:
          "When a developer opens a PR, GAIA searches for the matching Figma frame based on the branch name, PR title, or a Figma link in the PR body, then posts a direct preview link as a PR comment so reviewers can compare implementation against design intent instantly.",
      },
      {
        title: "Notify designers when their designs ship",
        description:
          "GAIA monitors for merged PRs that implement specific Figma components or screens and sends a notification to the responsible designer via Figma comments, Slack, or email so they can verify the live implementation matches the approved design.",
      },
      {
        title: "Track design implementation status in Figma",
        description:
          "GAIA updates Figma frame annotations or comments with GitHub PR status — open, in review, merged, or reverted — giving designers a real-time implementation tracker directly inside their design files.",
      },
      {
        title: "Flag design-code mismatches for review",
        description:
          "When a Figma component is updated after a related PR has already been merged, GAIA creates a GitHub issue flagging the potential discrepancy between the new design and the shipped code so the team can decide whether to update the implementation.",
      },
      {
        title: "Generate design change changelogs from Figma to GitHub",
        description:
          "When a designer publishes a new version of a Figma component library, GAIA posts a summary of the changes as a GitHub issue or PR comment on affected repositories so developers know which components may need implementation updates.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Figma to GAIA",
        description:
          "Link your GitHub repositories and Figma team files through GAIA's integration settings. GAIA uses GitHub OAuth and a Figma personal access token to read file structures and post comments without needing editor permissions.",
      },
      {
        step: "Set up your design-to-code mapping",
        description:
          "Tell GAIA how to match GitHub branches or PRs to Figma pages and frames — whether by naming convention, explicit Figma links in PR descriptions, or component names. You can configure notification preferences for designers per file or page.",
      },
      {
        step: "GAIA bridges design and code automatically",
        description:
          "GAIA handles the communication between Figma and GitHub continuously. Design specs appear on PRs without developer effort, and designers receive automatic updates when their work ships — no Slack pings or status meetings required.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA need editor access to our Figma files?",
        answer:
          "No. GAIA only requires viewer access to read file structure, frame names, and component information, and commenter access to post status updates. It never modifies your design files without explicit permission.",
      },
      {
        question: "How does GAIA match a GitHub PR to the right Figma frame?",
        answer:
          "GAIA uses several matching strategies: a Figma link pasted in the PR description, branch names that follow a convention like 'feature/component-name', PR labels, or a direct mapping table you configure in GAIA. The most reliable method is including a Figma link in your PR template.",
      },
      {
        question:
          "Can GAIA work with Figma component libraries across multiple files?",
        answer:
          "Yes. GAIA can track components across multiple Figma files and link them to the appropriate GitHub repositories. This is particularly useful for design systems where a shared component library is consumed by multiple product repos.",
      },
    ],
  },

  "github-discord": {
    slug: "github-discord",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline:
      "Post GitHub PR and issue notifications to Discord developer communities",
    metaTitle:
      "GitHub + Discord Automation - Dev Notifications in Discord | GAIA",
    metaDescription:
      "Connect GitHub and Discord with GAIA. Send pull request and issue notifications to Discord channels, engage your developer community with code activity, and keep contributors informed automatically.",
    keywords: [
      "GitHub Discord integration",
      "GitHub Discord notifications",
      "post GitHub activity to Discord",
      "connect GitHub and Discord",
      "open source community Discord",
      "developer community automation",
    ],
    intro:
      "Open-source projects and developer communities live on Discord, but GitHub activity stays siloed inside GitHub unless someone manually posts updates. Contributors miss important issues and PRs because they are not watching the repository. Maintainers spend time copying GitHub links into Discord announcements. Community members who want to contribute have no easy way to discover what needs help without digging through GitHub's interface.\n\nGAIA connects GitHub and Discord to keep your developer community informed and engaged automatically. When a new issue is opened, a PR is merged, or a release is published, GAIA formats the event into a clean Discord message and routes it to the right channel. Members can react, discuss, and jump directly to GitHub from Discord without maintainers doing any manual announcement work.\n\nThis integration is essential for open-source project maintainers who want active contributor communities, for developer-focused companies running public Discord servers, and for internal engineering teams that use Discord as their primary communication platform and want real-time code activity feeds.",
    useCases: [
      {
        title: "Post PR merge announcements to Discord",
        description:
          "When a pull request merges to the main branch, GAIA sends a formatted announcement to your Discord #releases or #dev-activity channel including the PR title, author, a summary of changes, and a link to the full diff.",
      },
      {
        title: "Alert contributors to issues tagged 'good first issue'",
        description:
          "GAIA monitors GitHub for newly opened issues labeled 'good first issue' or 'help wanted' and posts them to a dedicated Discord channel so community contributors can immediately see where they can jump in and help.",
      },
      {
        title: "Real-time CI/CD status in Discord",
        description:
          "GAIA posts GitHub Actions workflow results to Discord so the team knows immediately when a build passes or fails. Failed builds include a direct link to the failing step so engineers can triage without context-switching back to GitHub.",
      },
      {
        title: "New release notifications with changelog",
        description:
          "When a new GitHub release is published, GAIA formats the release notes and posts them to Discord with a download link, version number, and any breaking changes highlighted so community members are always informed about new versions.",
      },
      {
        title: "Daily contributor digest in Discord",
        description:
          "Each day GAIA posts a digest of the previous day's GitHub activity to Discord — merged PRs, resolved issues, new contributors, and open PRs awaiting review — keeping the entire community informed at a glance.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Discord to GAIA",
        description:
          "Authenticate your GitHub repository or organization and your Discord server in GAIA's settings. GAIA uses a Discord bot with webhook access so you control exactly which channels receive which notifications.",
      },
      {
        step: "Map GitHub events to Discord channels",
        description:
          "Configure which GitHub events (issues, PRs, releases, CI runs) should post to which Discord channels. You can filter by repository, branch, label, or event type so each channel receives only relevant, focused updates.",
      },
      {
        step: "GAIA delivers GitHub activity to Discord automatically",
        description:
          "GAIA processes GitHub webhook events and formats them into rich Discord messages with relevant context, links, and formatting. Your community stays informed without any manual announcement effort from maintainers.",
      },
    ],
    faqs: [
      {
        question:
          "Can I customize the format of GitHub notifications posted to Discord?",
        answer:
          "Yes. GAIA supports customizable message templates for each event type. You can control which fields are included, adjust the embed colors, add custom text, and configure whether messages appear as simple text or rich embeds with thumbnails and action buttons.",
      },
      {
        question:
          "Can GAIA handle multiple GitHub repositories in one Discord server?",
        answer:
          "Absolutely. You can connect multiple repositories to a single Discord server and route each repository's events to different channels. For example, a mono-repo organization might route frontend PRs to #frontend-dev and backend PRs to #backend-dev.",
      },
      {
        question: "Is this only for public open-source projects?",
        answer:
          "No. GAIA works equally well for private repositories and internal engineering teams that use Discord for communication. All GitHub data is handled securely, and GAIA only posts to the Discord channels you configure with the permissions you grant.",
      },
    ],
  },

  "github-google-calendar": {
    slug: "github-google-calendar",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Schedule sprint reviews from milestones and track PR deadlines in Calendar",
    metaTitle:
      "GitHub + Google Calendar - Schedule Dev Work Automatically | GAIA",
    metaDescription:
      "Connect GitHub and Google Calendar with GAIA. Auto-schedule sprint reviews from GitHub milestones, add PR review deadlines as calendar events, and keep your engineering schedule and codebase in sync.",
    keywords: [
      "GitHub Google Calendar integration",
      "GitHub Google Calendar automation",
      "schedule sprint reviews from GitHub milestones",
      "GitHub PR deadline calendar",
      "connect GitHub and Google Calendar",
      "engineering calendar automation",
    ],
    intro:
      "Engineering teams manage their schedules in Google Calendar and their code in GitHub, but the two rarely inform each other. A milestone due date set in GitHub has no corresponding calendar block. A sprint review meeting gets scheduled without checking when the milestone actually lands. Developers have no calendar reminders for PRs that need attention before a release, and project managers schedule planning meetings without visibility into the current state of the backlog.\n\nGAIA bridges GitHub and Google Calendar so your development timeline and your schedule stay synchronized. Milestone due dates automatically create calendar events with the list of open issues. PR review requests can generate calendar blocks so reviewers have protected time for code review. When a milestone shifts, GAIA can update the corresponding calendar event so the team's schedule reflects the new reality.\n\nThis integration is particularly valuable for engineering managers and tech leads who are responsible for both code quality and on-time delivery. Instead of maintaining a project timeline in both GitHub and Calendar manually, GAIA keeps the two in sync so your calendar always reflects what is actually happening in the codebase.",
    useCases: [
      {
        title: "Auto-create calendar events from GitHub milestones",
        description:
          "When a GitHub milestone is created or updated, GAIA creates a corresponding Google Calendar event on the due date, including the milestone title, a summary of open issues, and a link to the GitHub milestone page for quick reference.",
      },
      {
        title: "Schedule sprint review meetings from milestone completion",
        description:
          "GAIA monitors GitHub milestones and automatically creates a sprint review calendar invitation for the team when a milestone approaches completion, including an agenda pre-populated with merged PRs and any remaining open issues.",
      },
      {
        title: "Add PR review deadlines as calendar reminders",
        description:
          "When you are requested to review a pull request on a time-sensitive branch, GAIA adds a calendar reminder so you have a dedicated review slot before the PR's target merge date, preventing last-minute bottlenecks.",
      },
      {
        title: "Block calendar time for on-call from GitHub schedules",
        description:
          "GAIA can read on-call rotation schedules defined in GitHub repository wikis or files and create corresponding Google Calendar events so engineers always know when they are on-call without checking a separate document.",
      },
      {
        title: "Update calendar events when milestone dates shift",
        description:
          "When a GitHub milestone due date is edited, GAIA automatically updates the corresponding Google Calendar event to reflect the new date and sends update notifications to all invited attendees so the team is always working from accurate dates.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Google Calendar to GAIA",
        description:
          "Link your GitHub organization and Google Calendar account in GAIA's integration settings using OAuth. Select which repositories to monitor for milestones and which Google Calendar should receive the generated events.",
      },
      {
        step: "Configure your scheduling preferences",
        description:
          "Tell GAIA how far in advance to create calendar events, which team members to invite to milestone reviews, how to handle time zone differences, and whether to create individual events or add milestone dates to a shared team calendar.",
      },
      {
        step: "GAIA keeps your schedule and codebase aligned",
        description:
          "GAIA continuously monitors GitHub milestone changes and PR activity, updating Google Calendar events in real time. Your engineering schedule stays accurate without any manual calendar management from the team.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA add events to a shared team calendar rather than individual calendars?",
        answer:
          "Yes. GAIA can be configured to add milestone events and sprint reviews to a shared Google Calendar that the entire engineering team subscribes to, making it easy for everyone to see the development timeline without individual calendar management.",
      },
      {
        question:
          "What happens to the calendar event if a GitHub milestone is deleted?",
        answer:
          "GAIA can be configured to automatically delete or mark the corresponding calendar event as cancelled when a milestone is deleted, and to notify invited attendees of the cancellation. You can also choose to keep the event and have GAIA add a note about the deletion.",
      },
      {
        question:
          "Does GAIA work with GitHub Projects v2 timeline views as well as milestones?",
        answer:
          "GAIA primarily syncs GitHub milestones with Google Calendar. GitHub Projects v2 roadmap dates can also be used as a source for calendar events depending on your configuration, but milestone-based sync is the most reliable and fully supported path.",
      },
    ],
  },

  "github-trello": {
    slug: "github-trello",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Move Trello cards automatically when GitHub PRs merge or issues close",
    metaTitle:
      "GitHub + Trello Automation - Sync Code with Trello Boards | GAIA",
    metaDescription:
      "Connect GitHub and Trello with GAIA. Auto-move Trello cards when pull requests merge, create cards from GitHub issues, and keep your Trello board in sync with actual development progress.",
    keywords: [
      "GitHub Trello integration",
      "GitHub Trello automation",
      "move Trello cards from GitHub PR",
      "sync GitHub with Trello",
      "connect GitHub and Trello",
      "developer kanban automation",
    ],
    intro:
      "Small development teams and indie developers often use Trello for its simple kanban boards and GitHub for source control, but keeping a Trello board up to date with what is actually happening in GitHub is a manual, error-prone process. A card stays in 'In Progress' long after the PR has merged. Cards in 'Ready for Review' have no link back to the actual GitHub PR. The Trello board that started as a live project tracker becomes a stale to-do list that nobody trusts.\n\nGAIA connects GitHub and Trello so the board updates itself as code moves through the development pipeline. When a developer pushes a branch tied to a Trello card, GAIA moves the card to 'In Progress.' When the PR is opened, the card moves to 'In Review' and a GitHub link appears in the card. When the PR merges, the card moves to 'Done' automatically. The board reflects the real state of the project at all times.\n\nThis integration is perfect for small product teams, freelancers managing client projects in Trello, and any team that wants the simplicity of Trello with the automation power of a connected engineering workflow. No plugins, no Trello Power-Ups required — GAIA handles the bridge.",
    useCases: [
      {
        title: "Move Trello cards through lists based on PR status",
        description:
          "GAIA maps GitHub PR lifecycle events to Trello list transitions. Opening a PR moves the card to 'Code Review,' a passed CI run moves it to 'Ready to Merge,' and a successful merge moves it to 'Done' — all without the developer touching Trello.",
      },
      {
        title: "Create Trello cards from GitHub issues",
        description:
          "When a new GitHub issue is opened and labeled 'backlog' or 'sprint,' GAIA creates a corresponding Trello card in the configured list with the issue title, description, labels, and a direct link back to the GitHub issue for full context.",
      },
      {
        title: "Attach pull request links to Trello cards",
        description:
          "When a developer opens a PR that references a Trello card ID in the branch name or description, GAIA attaches the PR link to the Trello card as an attachment so reviewers and project managers can jump directly to the code diff from the board.",
      },
      {
        title: "Close GitHub issues when Trello cards are archived",
        description:
          "GAIA also works in reverse: when a Trello card is moved to 'Done' or archived, GAIA can close the linked GitHub issue and post a final comment with the Trello card URL, keeping both tools consistent from either direction.",
      },
      {
        title: "Daily stale card notifications",
        description:
          "GAIA monitors Trello cards in 'In Progress' lists and cross-checks them against GitHub PR activity. Cards with no associated PR activity in the last few days trigger a Trello comment notification reminding the assignee to update the PR or flag a blocker.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Trello to GAIA",
        description:
          "Authenticate your GitHub repositories and Trello workspace in GAIA's integration panel. Select the Trello boards and lists that should receive GitHub-driven updates and configure which repositories to monitor.",
      },
      {
        step: "Map GitHub events to Trello list transitions",
        description:
          "Define how GitHub events correspond to Trello list movements. Tell GAIA which branch name patterns or PR description formats indicate a card link, and configure the list names that correspond to each stage of your workflow.",
      },
      {
        step: "GAIA automates your Trello board from GitHub",
        description:
          "GAIA listens for GitHub webhook events and moves, updates, and comments on Trello cards accordingly. Your board becomes a live, accurate reflection of development progress that the whole team — technical and non-technical — can follow.",
      },
    ],
    faqs: [
      {
        question: "How does GAIA match a GitHub PR to the right Trello card?",
        answer:
          "GAIA matches using a Trello card short link or ID in the PR title, description, or branch name. For example, a branch named 'feature/trello-abc123-login-flow' will be matched to the Trello card with ID abc123. You can also configure GAIA to match by PR labels or title keywords.",
      },
      {
        question:
          "Can GAIA handle multiple GitHub repositories feeding into one Trello board?",
        answer:
          "Yes. You can connect several repositories to a single Trello board, useful for projects where frontend and backend code live in separate repos but the project is tracked in one Trello board. GAIA aggregates activity from all connected repos correctly.",
      },
      {
        question: "Does this require installing a Trello Power-Up?",
        answer:
          "No. GAIA connects directly to Trello's API and does not require any Power-Up installation. This means it works regardless of your Trello plan and does not count against Power-Up limits on free Trello workspaces.",
      },
    ],
  },

  "github-drive": {
    slug: "github-drive",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Backup repo docs to Drive and link design assets from Drive to repos",
    metaTitle:
      "GitHub + Google Drive Automation - Sync Code Docs with Drive | GAIA",
    metaDescription:
      "Connect GitHub and Google Drive with GAIA. Auto-backup repository documentation to Drive, link design assets from Drive to pull requests, and keep your code and file storage in sync.",
    keywords: [
      "GitHub Google Drive integration",
      "GitHub Google Drive automation",
      "backup GitHub docs to Drive",
      "link Drive assets to GitHub",
      "connect GitHub and Google Drive",
      "repository documentation backup",
    ],
    intro:
      "Development teams store code in GitHub and shared files in Google Drive, but the two ecosystems rarely reference each other. A design asset in Drive has no link to the GitHub PR that implements it. Documentation written in GitHub Markdown is not accessible to non-technical stakeholders who live in Google Docs. When a repository is archived or a team offboards, the context that lived only in GitHub is not always preserved alongside the project files in Drive.\n\nGAIA connects GitHub and Google Drive to create a persistent bridge between code and file storage. Repository documentation can be automatically backed up to Drive folders at regular intervals or when significant changes are merged. Design assets, mockups, and specification documents stored in Drive can be automatically linked to relevant GitHub pull requests. Non-technical stakeholders get read-only access to documentation through Drive without needing GitHub accounts.\n\nThis integration is especially useful for agencies, consultancies, and product companies that need to deliver documentation to clients (who live in Drive), for compliance-driven teams that must retain documentation artifacts outside of GitHub, and for any team that wants to ensure long-term project context is stored in a platform with richer file management capabilities.",
    useCases: [
      {
        title: "Auto-backup repository documentation to Drive",
        description:
          "GAIA monitors GitHub for merged PRs that modify documentation files and automatically exports updated Markdown files to a corresponding Google Drive folder, converting them to Google Docs format for easy stakeholder access.",
      },
      {
        title: "Link Drive design assets to GitHub pull requests",
        description:
          "When a pull request is opened that implements a feature with matching design assets in Drive, GAIA adds a comment to the PR with direct links to the relevant Drive files so reviewers can check the implementation against design specifications without leaving GitHub.",
      },
      {
        title: "Organize Drive folders by GitHub repository structure",
        description:
          "GAIA can mirror your GitHub repository structure in a Google Drive folder, creating subfolders for documentation, design, and meeting notes that align with the repository layout so project context is organized consistently across both platforms.",
      },
      {
        title: "Share release notes to Drive on GitHub releases",
        description:
          "When a new GitHub release is published, GAIA exports the release notes to a Google Doc in the project's Drive folder, making the changelog accessible to non-technical stakeholders, clients, and the broader organization without requiring GitHub access.",
      },
      {
        title: "Notify team when Drive design assets are updated",
        description:
          "When a designer updates a Drive file linked to an open GitHub PR, GAIA posts a comment on that PR alerting the developer and reviewer that the design spec has changed, reducing the risk of shipping an implementation based on outdated designs.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Google Drive to GAIA",
        description:
          "Authenticate your GitHub repositories and Google Drive account through GAIA's integration settings. Specify which repositories should be monitored and which Drive folder or Shared Drive should serve as the documentation destination.",
      },
      {
        step: "Configure sync and backup preferences",
        description:
          "Tell GAIA which file types to sync, how often to run backups, how to name and organize Drive files, and which Drive folders contain assets that should be linked back to GitHub. You can set per-repository or organization-wide rules.",
      },
      {
        step: "GAIA keeps Drive and GitHub in sync automatically",
        description:
          "GAIA monitors GitHub for documentation changes and Drive for asset updates, running sync and notification workflows automatically. Your team's file storage always reflects the current state of the codebase and vice versa.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync GitHub Wiki pages to Google Drive as well as repository files?",
        answer:
          "Yes. GAIA can export GitHub Wiki pages to Google Drive in addition to repository Markdown files. Wiki exports are converted to Google Docs format so they are fully editable and accessible to non-technical collaborators who need to contribute to documentation.",
      },
      {
        question: "How does GAIA match Drive files to GitHub pull requests?",
        answer:
          "GAIA uses folder structure conventions, file naming patterns, and labels or branch names in GitHub to identify matching Drive assets. You can also include a Drive folder link in a PR description or configure explicit mappings between repository paths and Drive folders.",
      },
      {
        question:
          "Does GAIA support Google Shared Drives for team-wide storage?",
        answer:
          "Yes. GAIA works with both personal Google Drive and Google Shared Drives (formerly Team Drives), making it suitable for organizations that manage all project files in a centralized Shared Drive accessible to the whole team.",
      },
    ],
  },

  "github-zoom": {
    slug: "github-zoom",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline:
      "Schedule code review meetings from PRs and post summaries back to issues",
    metaTitle:
      "GitHub + Zoom Automation - Code Review Meetings from PRs | GAIA",
    metaDescription:
      "Connect GitHub and Zoom with GAIA. Schedule code review meetings directly from pull request comments, post Zoom meeting summaries back to GitHub issues, and keep your dev discussions documented.",
    keywords: [
      "GitHub Zoom integration",
      "GitHub Zoom automation",
      "schedule code review meeting from GitHub",
      "post Zoom meeting notes to GitHub",
      "connect GitHub and Zoom",
      "developer meeting automation",
    ],
    intro:
      "Code reviews that require synchronous discussion are a common bottleneck in engineering workflows. A reviewer leaves a complex comment on a GitHub PR, the developer responds in a thread, and the back-and-forth takes days to resolve what a ten-minute Zoom call could address immediately. But scheduling that call requires leaving GitHub, opening a calendar, finding available time, creating a Zoom link, and sharing it — a process that rarely happens quickly enough to prevent the PR from stalling.\n\nGAIA connects GitHub and Zoom to make synchronous code review as easy as leaving a comment. A developer or reviewer can ask GAIA to schedule a code review meeting directly from a PR comment, and GAIA will find available time, create a Zoom meeting, and post the link back to the PR thread within seconds. After the meeting ends, GAIA posts a summary of the discussion back to the GitHub issue or PR as a comment, creating a permanent record of decisions made without anyone having to manually document the call.\n\nThis integration is valuable for distributed engineering teams where asynchronous code review occasionally requires a quick sync, for engineering managers who want all architectural decisions documented in GitHub regardless of how they were made, and for any team that wants to reduce the friction between async and sync collaboration in their development workflow.",
    useCases: [
      {
        title: "Schedule code review meetings from PR comments",
        description:
          "When a developer comments '@gaia schedule review meeting' on a pull request, GAIA checks participants' calendars, finds the next available slot, creates a Zoom meeting, and posts the join link back to the PR thread — all within seconds.",
      },
      {
        title: "Post Zoom meeting summaries to GitHub issues",
        description:
          "After a code review or architectural discussion on Zoom concludes, GAIA generates a meeting summary and posts it as a comment on the linked GitHub issue or PR, creating a searchable record of decisions, action items, and open questions without manual note-taking.",
      },
      {
        title: "Create GitHub issues from Zoom meeting action items",
        description:
          "GAIA analyzes Zoom meeting transcripts for action items and automatically creates corresponding GitHub issues with the right labels and assignees so follow-up work from technical discussions is always captured in the backlog.",
      },
      {
        title: "Notify PR participants when a review meeting is scheduled",
        description:
          "When a Zoom meeting is scheduled for a specific PR, GAIA automatically notifies all PR participants — author, reviewers, and commenters — via GitHub comment and email so no one misses the synchronous discussion.",
      },
      {
        title:
          "Schedule sprint planning and retrospective meetings from milestones",
        description:
          "GAIA can schedule recurring Zoom meetings for sprint planning and retrospectives based on GitHub milestone cadence, automatically linking the meeting agenda to the milestone's open and closed issues for a structured engineering rhythm.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Zoom to GAIA",
        description:
          "Authenticate your GitHub account and Zoom account in GAIA's integrations panel. GAIA will request calendar access to find available meeting slots and Zoom API access to create and manage meetings on your behalf.",
      },
      {
        step: "Configure your meeting preferences",
        description:
          "Set default meeting durations for different types of reviews, specify which GitHub repositories should have meeting scheduling enabled, configure how summaries should be formatted, and choose whether GAIA should automatically transcribe meetings.",
      },
      {
        step: "GAIA connects your code discussions with synchronous meetings",
        description:
          "GAIA monitors GitHub for meeting scheduling requests and Zoom for completed meetings, handling scheduling, notifications, and post-meeting documentation automatically. All your technical discussions end up documented in GitHub where future contributors can find them.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA automatically transcribe Zoom meetings about code reviews?",
        answer:
          "GAIA can use Zoom's built-in transcription feature (available on paid Zoom plans) to generate meeting summaries. If transcription is not available, GAIA creates a structured summary template for the meeting host to fill in, then posts it to GitHub on their behalf.",
      },
      {
        question:
          "Can GAIA schedule meetings with participants across different time zones?",
        answer:
          "Yes. GAIA checks the Google Calendar or Outlook availability of all PR participants and proposes meeting times that work across time zones, presenting options in each participant's local time to avoid scheduling confusion.",
      },
      {
        question:
          "What if I want to schedule a Zoom meeting without connecting it to a GitHub issue?",
        answer:
          "GAIA can schedule Zoom meetings independently of GitHub at any time through its conversational interface. The GitHub-Zoom integration is an additional layer that connects meetings to specific PRs and issues when that context is relevant.",
      },
    ],
  },

  "notion-clickup": {
    slug: "notion-clickup",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "ClickUp",
    toolBSlug: "clickup",
    tagline:
      "Sync project documentation with task management across Notion and ClickUp",
    metaTitle: "Notion + ClickUp Automation - Connect Docs and Tasks | GAIA",
    metaDescription:
      "Connect Notion and ClickUp with GAIA. Sync project docs with ClickUp tasks, auto-update Notion pages from task progress, and eliminate the documentation lag that plagues project teams.",
    keywords: [
      "Notion ClickUp integration",
      "Notion ClickUp automation",
      "sync Notion with ClickUp tasks",
      "connect Notion and ClickUp",
      "project docs and task management",
      "Notion ClickUp workflow",
    ],
    intro:
      "Project teams that use Notion for documentation and ClickUp for task management inevitably face the same problem: the two tools drift apart. A ClickUp task gets completed but the Notion spec page still says 'In Progress.' A Notion project plan is updated but none of the ClickUp tasks reflect the new requirements. Teams end up holding sync meetings not because there is important news to share, but simply to manually reconcile the state of two tools that should be speaking to each other automatically.\n\nGAIA connects Notion and ClickUp so documentation and task management stay in lockstep. When a ClickUp task moves to a new status, GAIA can update the corresponding Notion page. When a Notion project document is published or updated with new requirements, GAIA can create or update the relevant ClickUp tasks. The two systems become a unified project management environment where changes in one tool are always reflected in the other.\n\nThis integration is particularly powerful for product teams where the product manager maintains Notion specs and the engineering team tracks work in ClickUp, and for agencies that document project plans in Notion for clients while executing tasks in ClickUp internally.",
    useCases: [
      {
        title: "Update Notion pages when ClickUp tasks change status",
        description:
          "When a ClickUp task moves from 'In Progress' to 'Complete,' GAIA updates the status indicator on the linked Notion page so project documentation reflects real-time task progress without anyone manually touching the Notion page.",
      },
      {
        title: "Create ClickUp tasks from Notion action items",
        description:
          "When a Notion document is updated with a new action item or requirement, GAIA parses the change and creates a corresponding ClickUp task with the appropriate assignee, list, and due date derived from context in the Notion page.",
      },
      {
        title: "Sync project timelines between Notion databases and ClickUp",
        description:
          "GAIA maps Notion database date properties to ClickUp task due dates, keeping timeline data consistent across both tools. When a deadline shifts in ClickUp, the Notion project database updates automatically and vice versa.",
      },
      {
        title: "Generate Notion meeting notes from ClickUp sprint reviews",
        description:
          "After a sprint review is logged in ClickUp, GAIA creates a structured Notion page with the sprint summary, completed tasks, carry-over work, and blockers so project documentation grows automatically alongside task completion.",
      },
      {
        title: "Archive completed ClickUp tasks into Notion project logs",
        description:
          "GAIA periodically exports completed ClickUp tasks into a Notion database structured as a project log, giving leadership and stakeholders a searchable, long-term record of what was delivered without cluttering the active ClickUp workspace.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and ClickUp to GAIA",
        description:
          "Authenticate your Notion workspace and ClickUp workspace through GAIA's integration settings. Select the Notion pages and databases and the ClickUp spaces and lists that should be linked for automated syncing.",
      },
      {
        step: "Define your sync rules and mappings",
        description:
          "Configure which Notion pages correspond to which ClickUp lists, how status fields map between the two tools, and whether sync should be one-directional or fully bidirectional. Use natural language to describe your workflow preferences.",
      },
      {
        step: "GAIA keeps your docs and tasks aligned automatically",
        description:
          "GAIA monitors both Notion and ClickUp for changes and propagates updates between them in real time. Your documentation always reflects the actual state of the work, and your task board always reflects the documented requirements.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync a Notion database with multiple ClickUp lists simultaneously?",
        answer:
          "Yes. A single Notion database can be mapped to multiple ClickUp lists, useful for projects that span several ClickUp spaces or teams. GAIA handles the routing based on properties in the Notion database, such as team, project type, or priority.",
      },
      {
        question:
          "Does GAIA support Notion's relation and rollup properties for ClickUp sync?",
        answer:
          "GAIA can read and write standard Notion properties including selects, dates, text, and checkboxes. Relation and rollup properties are readable but writes to relation fields depend on the linked databases also being part of the configured integration.",
      },
      {
        question:
          "What happens if a ClickUp task is deleted — does GAIA delete the Notion page?",
        answer:
          "No. GAIA does not delete Notion content by default when a ClickUp task is removed. Instead, it updates the Notion page with a 'Task deleted in ClickUp' status note. Deletion must be explicitly configured or performed manually to prevent accidental data loss.",
      },
    ],
  },

  "notion-trello": {
    slug: "notion-trello",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Sync Trello cards with Notion databases and embed boards in project docs",
    metaTitle:
      "Notion + Trello Automation - Sync Cards with Notion Databases | GAIA",
    metaDescription:
      "Connect Notion and Trello with GAIA. Sync Trello cards with Notion database entries, embed board views in project docs, and keep your kanban boards and project wiki in perfect alignment.",
    keywords: [
      "Notion Trello integration",
      "Notion Trello automation",
      "sync Trello cards with Notion",
      "connect Notion and Trello",
      "embed Trello in Notion",
      "Notion Trello workflow",
    ],
    intro:
      "Teams that use Trello for day-to-day task tracking and Notion for project documentation find themselves constantly copying information between the two. A Trello card gets completed, but the Notion project page still lists it as in progress. A project plan documented in Notion spawns a whole set of Trello cards that are never linked back to their source. The kanban board and the project wiki exist in parallel universes, and the team spends valuable time at status meetings just reconciling the two.\n\nGAIA connects Notion and Trello to eliminate this reconciliation overhead. Trello card status changes can update corresponding Notion database entries. Notion project documents can automatically generate Trello cards for new action items. And GAIA can maintain an embedded, always-updated Trello board view within a Notion project page so stakeholders see live task progress without switching tools.\n\nThis combination is especially popular with small product teams, content teams, and consultancies that love Trello's visual simplicity for task tracking but rely on Notion's depth for project documentation, wikis, and stakeholder reporting.",
    useCases: [
      {
        title: "Sync Trello card status with Notion database properties",
        description:
          "When a Trello card moves to a new list, GAIA updates the status field on the corresponding Notion database entry so project tracking pages in Notion reflect real-time task progress from the Trello board without any manual updates.",
      },
      {
        title: "Create Trello cards from Notion action items",
        description:
          "When a Notion project page is updated with new tasks or requirements, GAIA parses the action items and creates corresponding Trello cards in the designated board and list, pre-filled with descriptions, due dates, and label mappings from the Notion document.",
      },
      {
        title: "Link Trello cards to Notion pages for full context",
        description:
          "GAIA attaches the relevant Notion page link as a Trello card attachment so team members working from the Trello board can jump directly to full project specifications, design docs, and meeting notes without searching Notion separately.",
      },
      {
        title: "Generate Notion project summaries from Trello board state",
        description:
          "GAIA can generate a structured Notion page summarizing the current state of a Trello board — cards by list, overdue cards, recently completed work, and upcoming deadlines — providing a narrative project status update that complements the visual kanban view.",
      },
      {
        title: "Archive Trello board history to Notion",
        description:
          "When a Trello board is closed or a sprint ends, GAIA exports the full board history into a structured Notion database, creating a searchable record of completed work that persists beyond the active board lifecycle.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Trello to GAIA",
        description:
          "Authenticate your Notion workspace and Trello account in GAIA's integrations panel. Select the Notion databases and Trello boards that should be linked, and configure the direction of sync for each pairing.",
      },
      {
        step: "Map Trello lists to Notion status options",
        description:
          "Tell GAIA how Trello list names correspond to Notion status field values. Configure how Trello labels map to Notion tags, how card due dates map to Notion date properties, and which Trello members map to Notion assignees.",
      },
      {
        step: "GAIA syncs your kanban and wiki automatically",
        description:
          "GAIA listens for Trello webhook events and Notion page updates, propagating changes between the two platforms in real time. Your Notion project docs stay current with Trello board activity without any manual copy-pasting.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA sync multiple Trello boards into a single Notion database?",
        answer:
          "Yes. You can map multiple Trello boards to a single Notion database, with a board or project property distinguishing which cards came from which source. This is useful for teams that run separate Trello boards per client or project but want unified reporting in Notion.",
      },
      {
        question:
          "What Notion page properties does GAIA support for Trello sync?",
        answer:
          "GAIA supports all standard Notion property types for Trello sync: text, select, multi-select, date, checkbox, person, URL, and number. This covers the full range of Trello card attributes including title, description, due date, labels, members, and completion status.",
      },
      {
        question:
          "Is there a limit to how many Trello cards GAIA can sync per Notion database?",
        answer:
          "GAIA does not impose a hard limit on the number of cards synced. Practical limits are determined by Trello and Notion API rate limits, which are generous for typical team usage. For very large boards with thousands of cards, GAIA can be configured to sync incrementally or filter to active cards only.",
      },
    ],
  },

  "notion-figma": {
    slug: "notion-figma",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Embed Figma designs in Notion and sync design status with project pages",
    metaTitle:
      "Notion + Figma Automation - Link Design Specs to Project Docs | GAIA",
    metaDescription:
      "Connect Notion and Figma with GAIA. Embed Figma frames in Notion project pages, auto-update design status in Notion databases, and keep your design workflow and project documentation in perfect sync.",
    keywords: [
      "Notion Figma integration",
      "Notion Figma automation",
      "embed Figma in Notion",
      "sync Figma status with Notion",
      "connect Notion and Figma",
      "design documentation workflow",
    ],
    intro:
      "Product and design teams rely on Notion for project documentation and Figma for design work, but keeping design specifications and project docs in sync is a constant challenge. A Notion project page describes a feature, but the actual design lives in Figma with no link back. When the design is approved in Figma, the Notion page still says 'In Design.' Stakeholders reviewing the Notion project doc have no idea what the feature is supposed to look like without separately navigating to Figma.\n\nGAIA creates a live connection between Figma and Notion so design work and project documentation reinforce each other. When a Figma frame is finalized, GAIA can embed a preview in the corresponding Notion page and update the design status field. When a Notion project enters the design phase, GAIA can create a linked Figma file section and notify the design team. Design decisions documented in Figma comments can be captured in Notion, and Notion feedback can flow back to Figma as annotations.\n\nThis integration transforms Notion from a static document repository into a live design documentation hub, and gives Figma the project context it needs to keep designers aligned with product goals. It is indispensable for product teams practicing design-led development who need a single source of truth that spans both disciplines.",
    useCases: [
      {
        title: "Auto-embed Figma frames in Notion project pages",
        description:
          "When a Figma frame is linked in a Notion page or when a Figma file is associated with a Notion project, GAIA automatically embeds a live preview of the design in the Notion page so stakeholders see the actual design alongside the project documentation.",
      },
      {
        title: "Update Notion design status when Figma frames are approved",
        description:
          "When a designer marks a Figma frame as ready for handoff or when a Figma comment thread is resolved, GAIA updates the design status property in the linked Notion database entry from 'In Design' to 'Design Complete' so project tracking pages stay accurate.",
      },
      {
        title: "Capture Figma design decisions in Notion",
        description:
          "GAIA monitors Figma comment threads on key design files and exports resolved discussions to a Notion 'Design Decisions' database, creating a searchable record of why design choices were made that survives beyond the Figma comment thread.",
      },
      {
        title: "Notify designers when Notion specs are updated",
        description:
          "When a product manager updates a Notion feature spec, GAIA notifies the assigned designer with a summary of what changed so they can update the Figma design accordingly — closing the feedback loop between product and design without a manual handoff meeting.",
      },
      {
        title: "Generate Notion design review checklists from Figma components",
        description:
          "GAIA can read a Figma component library and generate a Notion checklist for design review, listing each component with its current status, last-updated date, and link to the Figma frame so design system reviews are structured and thorough.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Figma to GAIA",
        description:
          "Authenticate your Notion workspace and Figma team through GAIA's integration settings. GAIA uses a Figma access token with viewer/commenter permissions and Notion OAuth to read and update pages without requiring admin access to either platform.",
      },
      {
        step: "Map Figma files to Notion pages and databases",
        description:
          "Tell GAIA which Figma files correspond to which Notion projects. You can link by sharing a Figma URL in a Notion page, by naming convention, or by explicit mapping in GAIA's configuration. Set preferences for which events should trigger updates.",
      },
      {
        step: "GAIA keeps design work and project docs in sync",
        description:
          "GAIA monitors Figma for design status changes and comment activity, and Notion for spec updates, propagating relevant changes between the two platforms automatically. Your project documentation becomes a live reflection of design progress.",
      },
    ],
    faqs: [
      {
        question:
          "Does the Figma embed in Notion update live when the design changes?",
        answer:
          "GAIA refreshes embedded Figma previews in Notion when it detects that the source Figma frame has been published with changes. The frequency of refresh can be configured, from real-time on every Figma publish to a daily scheduled update.",
      },
      {
        question:
          "Can GAIA work with Figma component libraries as well as individual project files?",
        answer:
          "Yes. GAIA can connect to Figma component libraries and track individual component status, version history, and usage across your Notion design system documentation. This is particularly useful for teams maintaining a living design system in Notion.",
      },
      {
        question: "Will GAIA add comments or annotations to my Figma files?",
        answer:
          "Only if you explicitly configure it to do so. By default, GAIA reads from Figma and writes to Notion. Writing Notion feedback back to Figma as comments is an optional feature you enable per-file or per-page, and it uses commenter permissions only.",
      },
    ],
  },

  "notion-discord": {
    slug: "notion-discord",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline:
      "Share Notion pages to Discord communities and capture decisions in Notion",
    metaTitle:
      "Notion + Discord Automation - Connect Your Wiki and Community | GAIA",
    metaDescription:
      "Connect Notion and Discord with GAIA. Share Notion pages to Discord channels automatically, capture important Discord discussions in Notion, and keep your community and documentation in sync.",
    keywords: [
      "Notion Discord integration",
      "Notion Discord automation",
      "share Notion pages to Discord",
      "capture Discord decisions in Notion",
      "connect Notion and Discord",
      "community documentation workflow",
    ],
    intro:
      "Communities and teams that build their knowledge base in Notion and their conversations in Discord face a familiar problem: important decisions, announcements, and resources get trapped in one platform and never reach the people in the other. A major update gets published in Notion but community members in Discord never see it unless someone manually shares the link. A critical decision made in a Discord discussion thread is lost to history because no one took the time to document it in Notion.\n\nGAIA bridges Notion and Discord to create a continuous flow of information between your knowledge base and your community. When a Notion page is published or updated, GAIA can post a formatted announcement to the relevant Discord channel so your community always knows about new content. When an important decision is made in a Discord thread, GAIA can capture it in a Notion database so it is documented, searchable, and accessible to people who were not in the conversation.\n\nThis integration is ideal for open-source communities, DAOs, creator communities, and developer ecosystems that maintain public documentation in Notion while running their real-time community in Discord. It is also valuable for internal teams that use Discord as their chat platform but need to maintain a permanent knowledge base in Notion.",
    useCases: [
      {
        title: "Auto-announce Notion page publications in Discord",
        description:
          "When a Notion page is published or moved to a published state, GAIA posts an announcement to the designated Discord channel with the page title, a brief summary, and the link so community members are immediately informed about new content.",
      },
      {
        title: "Capture important Discord decisions in Notion",
        description:
          "When a Discord conversation is marked with a specific emoji reaction or a moderator uses a slash command, GAIA extracts the thread context and creates a structured Notion page documenting the decision, participants, date, and any relevant links.",
      },
      {
        title: "Sync Notion announcements to multiple Discord servers",
        description:
          "For communities with multiple Discord servers or channels for different audiences, GAIA can route Notion page updates to the most relevant Discord destination based on tags, categories, or explicit routing rules defined in GAIA.",
      },
      {
        title: "Create Notion FAQ entries from Discord Q&A threads",
        description:
          "GAIA monitors Discord channels designated for Q&A and automatically exports resolved question threads to a Notion FAQ database, building your knowledge base from real community questions without any manual documentation effort.",
      },
      {
        title: "Post Notion weekly digest to Discord",
        description:
          "GAIA compiles a weekly digest of new and updated Notion pages and posts a structured summary to Discord every week so community members who miss individual announcements get a regular catch-up of everything new in the knowledge base.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Discord to GAIA",
        description:
          "Authenticate your Notion workspace and Discord server in GAIA's integration settings. Configure which Notion databases and pages GAIA should monitor and which Discord channels should receive announcements or capture triggers.",
      },
      {
        step: "Set up your announcement and capture rules",
        description:
          "Tell GAIA which types of Notion page updates should post to Discord, what the announcement format should look like, and how Discord messages or reactions should trigger Notion captures. You can set rules per-channel, per-database, or globally.",
      },
      {
        step: "GAIA flows information between Notion and Discord automatically",
        description:
          "GAIA monitors both platforms for configured triggers and executes announcements and captures in real time. Your Discord community stays informed about knowledge base updates, and important community discussions always find their way into Notion.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA capture entire Discord threads, or just individual messages?",
        answer:
          "GAIA can capture full Discord threads as a single Notion page, including all replies, timestamps, and participant names. For long threads, GAIA provides a summary at the top followed by the full transcript, making the captured content useful even without reading every message.",
      },
      {
        question:
          "Can GAIA post Notion updates to multiple Discord channels simultaneously?",
        answer:
          "Yes. A single Notion page update can trigger posts to multiple Discord channels if configured. You can also set up routing rules where a Notion page tagged 'announcement' goes to a public Discord channel while pages tagged 'internal' route only to a private staff channel.",
      },
      {
        question: "Does GAIA require bot permissions in Discord to function?",
        answer:
          "Yes. GAIA uses a Discord bot with message send, read message history, and reaction access permissions. These are standard permissions that can be granted without admin access and can be scoped to specific channels if your Discord server uses channel-level permission overrides.",
      },
    ],
  },

  "notion-teams": {
    slug: "notion-teams",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Microsoft Teams",
    toolBSlug: "teams",
    tagline:
      "Share Notion content in Teams and capture meeting notes back to Notion",
    metaTitle:
      "Notion + Microsoft Teams Automation - Connect Wiki and Chat | GAIA",
    metaDescription:
      "Connect Notion and Microsoft Teams with GAIA. Share Notion pages in Teams channels, capture Teams meeting notes in Notion automatically, and keep your knowledge base and team chat aligned.",
    keywords: [
      "Notion Microsoft Teams integration",
      "Notion Teams automation",
      "share Notion in Microsoft Teams",
      "capture Teams meeting notes to Notion",
      "connect Notion and Teams",
      "enterprise knowledge management",
    ],
    intro:
      "Enterprise teams that rely on Microsoft Teams for communication and Notion for knowledge management constantly lose information in the gap between the two. A Notion document published with important policy updates never reaches most of the team because they are living in Teams. Meeting decisions made in a Teams call are never written up in Notion because someone has to manually transcribe them after the fact. The knowledge base and the conversation platform operate as separate worlds, and institutional knowledge accumulates nowhere.\n\nGAIA connects Notion and Microsoft Teams to ensure that information flows seamlessly between the two. When an important Notion page is published, GAIA posts a rich summary to the relevant Teams channel. When a Teams meeting concludes, GAIA generates structured meeting notes and saves them directly to a Notion page linked to the meeting's agenda. Important Teams messages can be pinned to Notion with a single reaction, and Notion pages can be referenced in Teams with automatic previews.\n\nThis integration is particularly valuable for large organizations standardized on Microsoft 365 but using Notion as an internal wiki, for consulting teams that document client work in Notion but coordinate in Teams, and for any enterprise team that wants to reduce knowledge loss between their communication and documentation platforms.",
    useCases: [
      {
        title: "Post Notion page updates to Teams channels",
        description:
          "When a Notion page in a configured workspace or database is published or significantly updated, GAIA sends a formatted Teams message to the relevant channel with the page title, author, a summary of changes, and a direct link for the full document.",
      },
      {
        title: "Capture Teams meeting notes automatically in Notion",
        description:
          "After a Teams meeting ends, GAIA generates structured meeting notes using the meeting transcript or key messages and creates a Notion page in a designated meeting notes database, complete with attendees, date, agenda items, decisions, and action items.",
      },
      {
        title: "Save important Teams messages to Notion with a reaction",
        description:
          "Team members can react to a Teams message with a configured emoji to trigger GAIA to save that message to a Notion 'Important Messages' database, creating an accessible knowledge record from in-the-moment Teams conversations.",
      },
      {
        title: "Daily Teams digest of new Notion content",
        description:
          "Each morning GAIA posts a structured Teams message listing all Notion pages created or updated in the past 24 hours, organized by workspace section, so the team starts the day knowing what is new in the knowledge base without having to check Notion separately.",
      },
      {
        title: "Link Teams channel conversations to Notion project pages",
        description:
          "GAIA can associate a Microsoft Teams channel with a Notion project page, posting a project context card to new channel members and ensuring that major project updates in Notion are always surfaced in the Teams discussion thread.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Microsoft Teams to GAIA",
        description:
          "Authenticate your Notion workspace and Microsoft Teams organization through GAIA's integration settings. GAIA uses OAuth for both platforms and only requests the minimum permissions needed — message send for Teams and page read/write for Notion.",
      },
      {
        step: "Configure your information flow rules",
        description:
          "Specify which Notion databases trigger Teams notifications, which Teams channels are linked to which Notion sections, how meeting notes should be formatted and filed, and which Teams reactions should trigger Notion saves.",
      },
      {
        step: "GAIA bridges your wiki and your chat automatically",
        description:
          "GAIA monitors both Notion and Teams for configured triggers and executes information flows in real time. Your Teams channels stay informed about Notion updates, and important Teams discussions find their way into your permanent knowledge base.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA work with Microsoft Teams private channels?",
        answer:
          "Yes. GAIA can be configured to post to and read from both standard and private Teams channels, provided the GAIA bot is added to the private channel and granted appropriate permissions. Private channel content is handled securely and never routed to unintended destinations.",
      },
      {
        question:
          "Can GAIA capture meeting notes from Teams without using the transcript feature?",
        answer:
          "If Teams transcription is not available or enabled, GAIA creates a structured meeting notes template in Notion pre-populated with attendee names, meeting title, date, and duration. A team member can then fill in key decisions and action items, and GAIA files it in the right Notion location.",
      },
      {
        question:
          "Is this integration compatible with Microsoft 365 GCC or government cloud environments?",
        answer:
          "GAIA's Teams integration is designed for standard Microsoft 365 commercial environments. Government cloud (GCC) compatibility depends on the specific API endpoints available in that environment. Contact the GAIA team for guidance on GCC deployments.",
      },
    ],
  },

  "notion-stripe": {
    slug: "notion-stripe",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline:
      "Track Stripe revenue in Notion databases and route payment alerts to pages",
    metaTitle: "Notion + Stripe Automation - Revenue Tracking in Notion | GAIA",
    metaDescription:
      "Connect Notion and Stripe with GAIA. Auto-track Stripe revenue metrics in Notion databases, get payment and subscription alerts in Notion, and keep your business metrics alongside your project docs.",
    keywords: [
      "Notion Stripe integration",
      "Notion Stripe automation",
      "track Stripe revenue in Notion",
      "Stripe payment alerts Notion",
      "connect Notion and Stripe",
      "business metrics Notion database",
    ],
    intro:
      "Founders, product managers, and business teams use Notion to run their operations and Stripe to process payments, but revenue data stays siloed inside Stripe's dashboard. Key metrics like MRR, churn rate, and new subscriptions are not visible in the Notion workspace where strategy is planned and OKRs are tracked. Payment failures require manual investigation in Stripe rather than appearing automatically in the operational context where action items are managed. The business intelligence that lives in Stripe never finds its way into the Notion workspace where decisions are made.\n\nGAIA connects Stripe and Notion to bring revenue data into your operational hub. Key Stripe metrics can be synced to a Notion database on a regular schedule, giving you an always-current financial snapshot alongside your product plans and team OKRs. Payment events — successful charges, subscription starts, cancellations, and failed payments — can be routed to Notion pages as notifications so the right people can act on them without needing Stripe dashboard access.\n\nThis integration is especially valuable for SaaS founders using Notion as their company operating system, for finance teams that want revenue metrics in the same workspace as their planning documents, and for customer success teams that need to see payment and subscription status alongside their customer notes in Notion.",
    useCases: [
      {
        title: "Daily revenue metrics in a Notion database",
        description:
          "GAIA pulls key Stripe metrics — MRR, ARR, new subscriptions, churned revenue, active customers — on a daily schedule and writes them to a structured Notion database so your revenue dashboard lives in the same workspace as your company goals and plans.",
      },
      {
        title: "New subscription alerts in Notion",
        description:
          "When a new customer subscribes in Stripe, GAIA creates a Notion entry in a customer database with the plan, start date, customer email, and subscription value so your team has a CRM-like record of every customer automatically populated from Stripe.",
      },
      {
        title: "Payment failure notifications to Notion",
        description:
          "When a Stripe payment fails, GAIA creates a task in a Notion 'Revenue Operations' database with the customer name, amount, failure reason, and a link to the Stripe customer record so the team can follow up on dunning without Stripe dashboard access.",
      },
      {
        title: "Subscription cancellation tracking in Notion",
        description:
          "GAIA logs every Stripe subscription cancellation to a Notion churn database with the customer details, plan, cancellation reason (if provided), and lifetime value so the team can analyze churn patterns and prioritize win-back campaigns.",
      },
      {
        title: "Monthly financial report generation in Notion",
        description:
          "At the end of each month, GAIA queries Stripe for the period's financial summary and generates a structured Notion report with MRR growth, new customers, churn, and net revenue retention that is shared automatically with the leadership team.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Stripe to GAIA",
        description:
          "Authenticate your Notion workspace and connect your Stripe account using a restricted Stripe API key with read-only access. GAIA never writes to Stripe — it only reads revenue data and event webhooks to populate your Notion workspace.",
      },
      {
        step: "Configure your metrics and alert preferences",
        description:
          "Select which Stripe events and metrics should flow into Notion, which Notion databases should receive each type of data, and how often scheduled syncs should run. You can also set revenue threshold alerts to trigger Notion entries only above a certain amount.",
      },
      {
        step: "GAIA keeps your Notion workspace updated with Stripe data",
        description:
          "GAIA listens to Stripe webhook events and runs scheduled metric syncs, writing data to your Notion databases automatically. Your operational workspace becomes a live business intelligence hub without any manual reporting effort.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA have access to write to my Stripe account?",
        answer:
          "No. GAIA uses a read-only Stripe API key with restricted permissions. It can read customer, subscription, payment, and metric data but cannot create charges, modify subscriptions, or access your Stripe settings. This ensures revenue data flows safely to Notion without any risk to your Stripe account.",
      },
      {
        question:
          "Can GAIA sync Stripe data for multiple Stripe accounts into one Notion workspace?",
        answer:
          "Yes. If you operate multiple businesses or brands with separate Stripe accounts, GAIA can sync data from each account into the same Notion workspace, using a source property in the database to distinguish which account each entry belongs to.",
      },
      {
        question: "How current is the Stripe data in Notion — is it real-time?",
        answer:
          "Event-based data like new subscriptions, cancellations, and payment failures is synced in near real-time via Stripe webhooks. Aggregate metrics like MRR and ARR are synced on the schedule you configure — daily is the default, but hourly is available for teams that need more frequent updates.",
      },
    ],
  },

  "notion-airtable": {
    slug: "notion-airtable",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline:
      "Sync databases between Notion and Airtable and migrate data bidirectionally",
    metaTitle: "Notion + Airtable Automation - Sync and Migrate Data | GAIA",
    metaDescription:
      "Connect Notion and Airtable with GAIA. Sync databases between Notion and Airtable, migrate data without manual exports, and keep both platforms updated as your data workflow evolves.",
    keywords: [
      "Notion Airtable integration",
      "Notion Airtable automation",
      "sync Notion database with Airtable",
      "migrate Notion to Airtable",
      "connect Notion and Airtable",
      "database sync automation",
    ],
    intro:
      "Notion and Airtable are both powerful database tools, and many teams use both — Notion for documentation-rich, narrative-style databases and Airtable for structured, spreadsheet-like data that requires complex filtering, formulas, and API access. But when the same records need to exist in both systems, teams face a painful choice: maintain two separate databases manually, or accept that one will always be out of date.\n\nGAIA eliminates this dilemma by keeping Notion databases and Airtable bases synchronized automatically. Records created in Airtable appear in Notion. Updates made to Notion properties propagate to Airtable fields. Teams can use whichever interface suits their workflow — Airtable's grid for data analysis, Notion's page view for narrative context — and always see the same underlying data. Data migration from Notion to Airtable (or vice versa) can be initiated with a single GAIA command rather than a manual export-import cycle.\n\nThis integration is valuable for operations teams that need Airtable's relational database power alongside Notion's wiki capabilities, for content teams that manage editorial calendars in both tools, and for any organization transitioning between the two platforms and needing a smooth, automated migration path.",
    useCases: [
      {
        title: "Bidirectional database sync between Notion and Airtable",
        description:
          "GAIA maintains a live, bidirectional sync between a Notion database and an Airtable base. New records, updated fields, and deleted entries in either platform are propagated to the other within minutes, keeping both databases consistently current.",
      },
      {
        title: "Migrate data from Notion to Airtable on demand",
        description:
          "When your team decides to move a Notion database to Airtable, GAIA handles the migration automatically — mapping Notion properties to Airtable field types, preserving relations where possible, and validating the migrated records to ensure data integrity.",
      },
      {
        title: "Use Airtable for data analysis, Notion for narrative context",
        description:
          "GAIA syncs the structured data fields bidirectionally while letting each tool maintain its strengths. Airtable handles formulas, lookups, and API integrations for data analysis; Notion stores the rich page content, comments, and documentation context that Airtable cannot represent.",
      },
      {
        title: "Sync editorial calendars between content teams",
        description:
          "Content teams using Airtable for structured editorial planning and Notion for article drafting can sync their calendars via GAIA so published status, publish dates, and author assignments are consistent in both tools without manual reconciliation.",
      },
      {
        title: "Auto-create Airtable records from Notion form submissions",
        description:
          "When a Notion form or database entry is created through a public Notion page, GAIA mirrors the submission to an Airtable base in real time, enabling Airtable's automation and integration capabilities to process the new record for CRM, reporting, or workflow triggers.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Airtable to GAIA",
        description:
          "Authenticate your Notion workspace and Airtable account in GAIA's integration settings. Select the Notion databases and Airtable bases that should be linked, and configure the sync direction — one-way push, one-way pull, or fully bidirectional.",
      },
      {
        step: "Map fields between Notion and Airtable",
        description:
          "GAIA guides you through matching Notion property types to Airtable field types. For properties with no direct equivalent, GAIA offers mapping options — for example, Notion rich text to an Airtable long text field or a Notion multi-select to an Airtable multiple select.",
      },
      {
        step: "GAIA syncs your databases continuously",
        description:
          "Once configured, GAIA monitors both platforms for changes and propagates updates between them automatically. You can run a full sync at any time via GAIA's conversational interface or let it run on the configured polling interval.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA handle Notion relation properties during sync with Airtable?",
        answer:
          "Notion relation properties are synced to Airtable linked record fields when the related Notion database is also synced to a corresponding Airtable table. If only one side of a relation is synced, GAIA converts the relation to a text field containing the related page title to preserve the reference.",
      },
      {
        question: "Can GAIA handle Airtable formula fields during sync?",
        answer:
          "Airtable formula fields are read-only computed values. GAIA can read and push formula field results to Notion as static values, but it does not replicate Airtable formulas in Notion — the formula logic itself stays in Airtable and only the computed result is synced.",
      },
      {
        question:
          "What happens if the same record is edited in both platforms simultaneously?",
        answer:
          "GAIA uses a last-write-wins conflict resolution strategy by default, where the most recently modified version of a record takes precedence. You can alternatively configure GAIA to flag conflicts for manual review rather than automatically resolving them, which is recommended for critical data.",
      },
    ],
  },

  "notion-drive": {
    slug: "notion-drive",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Attach Drive files to Notion pages and organize Drive by your Notion structure",
    metaTitle: "Notion + Google Drive Automation - Link Files and Docs | GAIA",
    metaDescription:
      "Connect Notion and Google Drive with GAIA. Automatically attach Drive files to Notion pages, mirror your Notion workspace structure in Drive folders, and keep file storage and documentation aligned.",
    keywords: [
      "Notion Google Drive integration",
      "Notion Google Drive automation",
      "attach Drive files to Notion",
      "organize Drive by Notion structure",
      "connect Notion and Google Drive",
      "file and documentation management",
    ],
    intro:
      "Teams that use Notion as their primary wiki and Google Drive for file storage inevitably end up with two parallel organizational systems that do not know each other exists. A Notion project page has no link to the Drive folder with the relevant files. A Drive folder full of project assets has no connection to the Notion page where the project is documented. Finding everything related to a project means hunting across two separate systems with different organizational logic.\n\nGAIA creates a unified organizational layer between Notion and Google Drive. When a Notion project page is created, GAIA can automatically create a corresponding Google Drive folder and link it in the Notion page. When a new file is added to a Drive folder, GAIA can attach it to the linked Notion page as an embedded file reference. The result is a project ecosystem where documentation and files are always connected — click from the Notion page to the Drive folder, or from Drive back to the Notion context.\n\nThis integration is essential for content teams managing production assets, design teams linking deliverables to project specs, and any knowledge-intensive organization that wants a single entry point to all project-related information regardless of whether it lives in a Google Doc or a Notion page.",
    useCases: [
      {
        title: "Auto-create Drive folders when Notion projects are created",
        description:
          "When a new entry is created in a Notion project database, GAIA automatically creates a corresponding Google Drive folder with the project name, adds the Drive folder link to the Notion page, and organizes it within the correct parent Drive directory.",
      },
      {
        title: "Attach new Drive files to linked Notion pages",
        description:
          "When a new file is added to a Google Drive folder linked to a Notion page, GAIA attaches the file to the Notion page as a link or embed so anyone viewing the Notion page can access the latest files without navigating to Drive separately.",
      },
      {
        title: "Mirror Notion workspace structure in Google Drive",
        description:
          "GAIA can generate a Google Drive folder hierarchy that mirrors your Notion workspace structure — creating team, project, and document-level folders that correspond to your Notion pages — so file storage and documentation share the same organizational logic.",
      },
      {
        title: "Sync Google Doc titles with Notion page titles",
        description:
          "When a Notion page title changes, GAIA updates the title of the linked Google Doc in Drive, and vice versa. This keeps cross-references accurate and ensures that searches in either platform surface the right document.",
      },
      {
        title: "Archive Notion pages to Google Drive on deletion",
        description:
          "When a Notion page is deleted or moved to an archive database, GAIA exports the page content as a Google Doc in a Drive archive folder, providing a non-Notion backup of important documentation that persists beyond the Notion workspace.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Google Drive to GAIA",
        description:
          "Authenticate your Notion workspace and Google Drive account in GAIA's integration settings. Select which Notion databases should have linked Drive folders and which Drive folders GAIA should monitor for new file attachments.",
      },
      {
        step: "Set your folder and attachment preferences",
        description:
          "Configure the Drive folder naming convention, the parent folder where new project folders should be created, which Notion property should store the Drive folder link, and whether file attachments should appear as links or embedded in the Notion page.",
      },
      {
        step: "GAIA links your files and documentation automatically",
        description:
          "GAIA monitors Notion for new pages and updates and Drive for new files, creating folder structures and attachments automatically. Your team can navigate seamlessly between documentation and files without maintaining separate organizational systems.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA work with Google Shared Drives for team file storage?",
        answer:
          "Yes. GAIA supports Google Shared Drives (formerly Team Drives) in addition to personal Google Drive. When using Shared Drives, GAIA creates project folders within the configured Shared Drive and links them to Notion, ensuring all team members with Shared Drive access can also reach the linked files.",
      },
      {
        question: "What file types can GAIA attach from Drive to Notion?",
        answer:
          "GAIA can attach any file type stored in Google Drive to Notion, including Google Docs, Google Sheets, Slides, PDFs, images, videos, and other file formats. Files are linked by their Drive URL, so they open in the appropriate application when accessed from Notion.",
      },
      {
        question:
          "If a file is moved in Drive, does GAIA update the link in Notion?",
        answer:
          "Google Drive file links are stable and do not change when a file is moved between folders, so existing Notion attachments continue to work correctly after a Drive reorganization. Folder links may update if the folder is moved, and GAIA can detect these changes and update Notion folder references accordingly.",
      },
    ],
  },

  "notion-zoom": {
    slug: "notion-zoom",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Zoom",
    toolBSlug: "zoom",
    canonicalSlug: "zoom-notion",
    tagline: "Post Zoom meeting summaries to Notion pages automatically",
    metaTitle: "Notion + Zoom Automation - Meeting Notes to Notion | GAIA",
    metaDescription:
      "Connect Notion and Zoom with GAIA. Automatically post Zoom meeting summaries and transcripts to Notion pages, capture action items, and build a searchable meeting archive in your Notion workspace.",
    keywords: [
      "Notion Zoom integration",
      "Notion Zoom automation",
      "save Zoom meeting notes to Notion",
      "Zoom transcript to Notion",
      "connect Notion and Zoom",
      "meeting documentation automation",
    ],
    intro:
      "Zoom meetings generate enormous amounts of valuable information — decisions, action items, project updates, and strategic discussions — but almost none of it gets documented in a systematic way. Meeting notes end up in someone's personal document, never linked to the Notion pages where the relevant projects are tracked. Transcripts pile up in Zoom's cloud storage, unsearchable and disconnected from the rest of the team's knowledge base. The same decisions get made in meetings repeatedly because no one can find the record of the previous discussion.\n\nGAIA automatically bridges Zoom and Notion to capture every meeting's value into your knowledge base. When a Zoom meeting ends, GAIA generates a structured summary from the transcript — highlighting key decisions, action items, participants, and topics discussed — and posts it to the designated Notion page. Recurring meetings build a chronological archive of notes in Notion automatically. Action items extracted from meeting transcripts become Notion tasks linked to the right project pages.\n\nThis integration transforms how organizations use meeting time. Participants can focus on the conversation instead of frantic note-taking. Anyone who misses a meeting can read the Notion summary in minutes. Leaders can track decisions and commitments across all meetings from a central Notion database. The institutional knowledge generated in Zoom finally has a permanent, organized home.",
    useCases: [
      {
        title: "Auto-generate meeting notes in Notion after every Zoom call",
        description:
          "When a Zoom meeting ends, GAIA processes the meeting transcript and creates a structured Notion page with the meeting title, date, attendees, key discussion points, decisions made, and action items so every meeting is documented without anyone taking manual notes.",
      },
      {
        title: "Extract and create Notion tasks from action items",
        description:
          "GAIA parses Zoom transcripts for commitments and action items — 'John will send the report by Friday,' 'we need to update the pricing page' — and creates corresponding Notion tasks assigned to the right team members with appropriate due dates.",
      },
      {
        title: "Build a searchable meeting archive in Notion",
        description:
          "All Zoom meeting summaries are added to a centralized Notion meetings database organized by date, team, and project. The database becomes a searchable institutional archive so anyone can find what was discussed and decided in any meeting, no matter how long ago.",
      },
      {
        title: "Link meeting notes to project pages automatically",
        description:
          "GAIA uses meeting titles, invitees, and transcript content to identify the relevant Notion project page and links the meeting notes there, so every project page in Notion has a complete history of all meetings related to that project.",
      },
      {
        title: "Send meeting summary digests to stakeholders",
        description:
          "After Notion captures the meeting notes, GAIA can send a summary to meeting participants and any other stakeholders who were not present, including action item owners, so everyone is aligned on outcomes without reading the full transcript.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Zoom to GAIA",
        description:
          "Authenticate your Notion workspace and Zoom account in GAIA's integration settings. Enable Zoom cloud recording and transcription so GAIA can access meeting transcripts, and select the Notion database where meeting notes should be saved.",
      },
      {
        step: "Configure your meeting note preferences",
        description:
          "Tell GAIA how to structure meeting notes in Notion — which properties to populate, how to format summaries, how to identify action items, and how to match meetings to the right Notion project pages. You can configure different templates for different meeting types.",
      },
      {
        step: "GAIA documents every meeting in Notion automatically",
        description:
          "After every Zoom meeting, GAIA processes the transcript, generates a structured summary, creates the Notion page, and links it to the relevant project. Your knowledge base grows with every meeting your team holds, with zero manual documentation effort.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA require Zoom cloud recording to be enabled?",
        answer:
          "Yes. GAIA accesses meeting transcripts through Zoom's cloud recording feature, which is available on Zoom Pro, Business, and Enterprise plans. If cloud recording is not enabled for a meeting, GAIA can still create a meeting notes template in Notion pre-populated with attendee and meeting metadata for manual completion.",
      },
      {
        question: "Can GAIA generate notes for meetings I did not host?",
        answer:
          "GAIA can generate notes for any Zoom meeting where the connected Zoom account has access to the cloud recording. For meetings hosted by others in your organization, the meeting host must share cloud recording access or the organization must use a Zoom account with centralized recording management.",
      },
      {
        question: "How accurate are the AI-generated meeting summaries?",
        answer:
          "GAIA's meeting summaries are generated from Zoom's transcript using an AI model trained for structured summarization. Accuracy depends on transcript quality, which improves with clear audio and speakers identifying themselves. You can always edit the generated Notion page, and GAIA learns your formatting preferences over time.",
      },
    ],
  },

  "notion-hubspot": {
    slug: "notion-hubspot",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Sync HubSpot CRM data to Notion and document customer context alongside deals",
    metaTitle:
      "Notion + HubSpot Automation - CRM Data in Your Notion Wiki | GAIA",
    metaDescription:
      "Connect Notion and HubSpot with GAIA. Sync CRM contacts, deals, and company data to Notion databases, document customer context alongside HubSpot records, and keep sales and operations aligned.",
    keywords: [
      "Notion HubSpot integration",
      "Notion HubSpot automation",
      "sync HubSpot CRM to Notion",
      "customer context in Notion",
      "connect Notion and HubSpot",
      "sales documentation workflow",
    ],
    intro:
      "Sales teams live in HubSpot while the broader organization — product, customer success, engineering — works in Notion. The result is that customer context stays locked inside HubSpot, accessible only to sales team members. Important customer feedback, special agreements, implementation notes, and relationship history never make it into the Notion workspace where product decisions are made and customer success plans are documented. When a deal closes, the context that sales built up over months of relationship development rarely transfers to the team that will actually deliver the product.\n\nGAIA connects HubSpot and Notion to make customer intelligence accessible across the organization. HubSpot contacts, companies, and deals can be synced to Notion databases where product, engineering, and success teams can add context, documentation, and notes alongside the CRM data. When a deal moves to a new stage in HubSpot, the linked Notion page updates automatically. When a customer success manager adds implementation notes to Notion, GAIA can push key data points back to the HubSpot record.\n\nThis integration is transformative for customer-centric organizations that want to break down the silos between sales, product, and success. It is especially valuable during the critical handoff from sales to implementation, where all the context a sales rep built needs to flow immediately to the people responsible for delivering on the promise.",
    useCases: [
      {
        title: "Sync HubSpot deals to a Notion pipeline database",
        description:
          "GAIA syncs HubSpot deals to a Notion database, keeping deal stage, value, close date, and owner properties current in both systems. Sales leaders can view deal status in Notion alongside product plans and customer context without toggling to HubSpot.",
      },
      {
        title: "Auto-create Notion pages for new HubSpot contacts",
        description:
          "When a new contact is created in HubSpot, GAIA creates a corresponding Notion page pre-populated with the contact's name, company, email, and deal history. The page serves as a customer context hub where any team member can add notes, meeting summaries, and project links.",
      },
      {
        title: "Document customer implementation plans linked to HubSpot deals",
        description:
          "Customer success teams can create detailed implementation plans in Notion linked to the corresponding HubSpot deal. GAIA keeps the HubSpot deal stage and the Notion project status synchronized, giving leadership a unified view of both sales and delivery progress.",
      },
      {
        title: "Push Notion customer notes back to HubSpot",
        description:
          "When a customer success manager or account manager adds a significant note or meeting summary to a Notion customer page, GAIA can push a summarized version to the corresponding HubSpot contact timeline so sales reps always have access to post-sales customer interactions.",
      },
      {
        title: "Alert the team in Notion when HubSpot deals close",
        description:
          "When a HubSpot deal moves to 'Closed Won,' GAIA creates a handoff task in a Notion operations database, includes the deal value, customer name, and key requirements from the HubSpot record, and notifies the implementation team so onboarding begins immediately after close.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and HubSpot to GAIA",
        description:
          "Authenticate your Notion workspace and HubSpot portal through GAIA's integration settings. Select which HubSpot objects — contacts, companies, deals, or tickets — should sync to Notion, and which Notion databases should receive them.",
      },
      {
        step: "Configure your data mapping and sync rules",
        description:
          "Map HubSpot properties to Notion database properties, define which HubSpot pipeline stages trigger Notion updates, set the direction of sync for each property, and configure which team members should be notified of key events like deal closes.",
      },
      {
        step: "GAIA keeps CRM and documentation in sync automatically",
        description:
          "GAIA monitors HubSpot for CRM updates and Notion for documentation changes, propagating relevant data between the two platforms automatically. Your entire organization gets visibility into customer relationships without needing HubSpot access.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync HubSpot custom properties to Notion?",
        answer:
          "Yes. GAIA reads all custom properties defined in your HubSpot portal and lets you map them to corresponding Notion database properties. This includes custom contact properties, deal properties, and company properties created for your specific business process.",
      },
      {
        question:
          "Does GAIA support HubSpot's association between contacts, companies, and deals?",
        answer:
          "GAIA syncs the primary association data between HubSpot objects to Notion relation properties where the linked Notion databases are also synced. For example, a Notion contact page can have a relation to the linked company page and deal page if all three HubSpot object types are configured for sync.",
      },
      {
        question:
          "Is bidirectional sync safe — could Notion changes overwrite important HubSpot data?",
        answer:
          "GAIA's bidirectional sync is carefully managed. By default, GAIA only writes to HubSpot fields that you explicitly designate as writable, and all Notion-to-HubSpot sync is logged. We recommend starting with one-way HubSpot-to-Notion sync and enabling bidirectional sync selectively after validating the field mappings.",
      },
    ],
  },

  "github-jira": {
    slug: "github-jira",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Keep GitHub PRs and Jira tickets in sync so your sprint board always reflects the true state of your code",
    metaTitle: "GitHub + Jira Integration - Sync Code and Sprint Board | GAIA",
    metaDescription:
      "Automate GitHub and Jira with GAIA. Sync PR status to Jira tickets, auto-transition issues on merge, and keep your sprint board accurate without manual updates.",
    keywords: [
      "GitHub Jira integration",
      "GitHub Jira automation",
      "sync GitHub PR to Jira",
      "auto-transition Jira on PR merge",
      "GitHub Jira sprint sync",
      "GitHub Jira workflow",
    ],
    intro:
      "Most engineering teams use both GitHub for code and Jira for project tracking, but keeping them synchronized is a constant manual chore. A developer merges a PR and forgets to move the Jira ticket to Done. A Jira issue gets closed by a product manager before the code is even reviewed. The sprint board drifts out of sync with the actual state of the codebase, and velocity reports become unreliable.\n\nGAIA automates the handoff between GitHub and Jira so the two systems stay consistent without anyone having to remember to update both. When a PR is opened, GAIA transitions the linked Jira ticket to In Review. When the PR is merged, the ticket moves to Done automatically. When a Jira issue is created and added to a sprint, GAIA can open a corresponding GitHub issue or branch to match.\n\nFor engineering managers, this means sprint boards that accurately reflect code reality. For developers, it means one less context switch—write the code, merge the PR, and trust that the project tracker will catch up on its own.",
    useCases: [
      {
        title: "Auto-transition Jira tickets on PR events",
        description:
          "When a pull request is opened, GAIA moves the linked Jira issue to In Review. When the PR is merged, the ticket transitions to Done. When a PR is closed without merging, GAIA moves the ticket back to In Progress.",
      },
      {
        title: "Create GitHub issues from new Jira sprint tickets",
        description:
          "When a new Jira issue is added to a sprint, GAIA creates a linked GitHub issue in the appropriate repository so developers can track code-level work directly from GitHub without leaving their workflow.",
      },
      {
        title: "Post PR review status to Jira ticket comments",
        description:
          "GAIA posts a comment on the Jira ticket whenever the linked PR receives a review—approved, changes requested, or commented—so product managers can follow code review progress without needing GitHub access.",
      },
      {
        title: "Failed CI notification on Jira tickets",
        description:
          "When a GitHub Actions CI run fails on a PR, GAIA adds a flag or comment to the linked Jira ticket alerting the team that the build is broken, preventing the ticket from being marked Done prematurely.",
      },
      {
        title: "Sprint completion report from merged PRs",
        description:
          "At the end of a sprint, GAIA compiles all merged PRs and their linked Jira tickets into a structured summary, giving engineering managers an accurate picture of what was shipped without manually cross-referencing two tools.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Jira to GAIA",
        description:
          "Authenticate your GitHub repositories and Jira project in GAIA's integration settings. GAIA uses OAuth for both connections and only requests the permissions needed for issue and PR sync.",
      },
      {
        step: "Map GitHub events to Jira transitions",
        description:
          "Configure which GitHub PR events trigger which Jira transitions, how to link PRs to Jira issues (by branch name, PR title, or commit message), and which Jira project to target for new issues.",
      },
      {
        step: "GAIA keeps GitHub and Jira synchronized automatically",
        description:
          "GAIA monitors both GitHub and Jira for changes and keeps them in sync automatically. You can override any automated action by telling GAIA directly, and all sync history is logged for audit purposes.",
      },
    ],
    faqs: [
      {
        question: "How does GAIA link a GitHub PR to the correct Jira ticket?",
        answer:
          "GAIA looks for Jira issue keys (e.g., PROJ-123) in the PR title, branch name, or commit messages. If it finds a match, it links the PR to that Jira ticket automatically. You can also manually link a PR to a ticket via a GAIA command.",
      },
      {
        question: "Can GAIA work with Jira's custom workflows and statuses?",
        answer:
          "Yes. During setup GAIA reads your Jira project's workflow configuration and lets you map GitHub events to your specific custom statuses rather than assuming a generic To Do / In Progress / Done structure.",
      },
      {
        question: "Does this work with Jira Cloud and Jira Server?",
        answer:
          "GAIA supports Jira Cloud natively. Jira Server and Jira Data Center integrations are available with additional configuration and require network access to your self-hosted instance.",
      },
      {
        question:
          "Will GAIA create duplicate Jira tickets if the same issue appears in multiple PRs?",
        answer:
          "No. GAIA tracks the relationship between GitHub PRs and Jira tickets and updates the existing ticket rather than creating duplicates. Multiple PRs can be linked to the same Jira ticket with individual status updates per PR.",
      },
    ],
  },

  "github-hubspot": {
    slug: "github-hubspot",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Log deployment activity to HubSpot deals and notify sales when customer-facing features ship",
    metaTitle:
      "GitHub + HubSpot Integration - Link Code Releases to CRM | GAIA",
    metaDescription:
      "Connect GitHub and HubSpot with GAIA. Auto-log releases to deals, alert sales when requested features ship, and tie engineering output to customer revenue.",
    keywords: [
      "GitHub HubSpot integration",
      "GitHub HubSpot automation",
      "log GitHub releases to HubSpot",
      "engineering CRM integration",
      "feature release CRM notification",
      "GitHub HubSpot workflow",
    ],
    intro:
      "Sales and engineering teams operate in separate worlds—one focused on deals and customer relationships in HubSpot, the other tracking code and releases in GitHub. When a customer's requested feature finally ships, the sales rep who promised it often finds out days later, missing the opportunity to re-engage the prospect at exactly the right moment.\n\nGAIA creates a live connection between GitHub and HubSpot so engineering releases automatically surface in your CRM. When a release is published in GitHub, GAIA logs it as an activity on relevant HubSpot deals and accounts, notifies the owning AE, and can even trigger a follow-up task to reach out to customers who requested that feature.\n\nFor product-led growth companies, this integration also lets you tie engagement signals from GitHub—like when an enterprise customer first uses a new API endpoint—back to the HubSpot contact record, giving your sales team richer context for their conversations.",
    useCases: [
      {
        title: "Notify sales reps when requested features ship",
        description:
          "When a GitHub release includes a feature linked to a HubSpot deal, GAIA notifies the deal owner with a summary of what shipped so they can immediately follow up with the customer at the ideal moment.",
      },
      {
        title: "Log releases as CRM timeline activities",
        description:
          "Every GitHub release is automatically logged as a timeline activity on relevant HubSpot company or deal records, giving sales and success teams a complete picture of what has been delivered to each customer.",
      },
      {
        title: "Create HubSpot tasks for customer-impacting bugs",
        description:
          "When a GitHub issue is labeled as a customer-impacting bug, GAIA creates a HubSpot task for the customer success manager assigned to the affected account, ensuring proactive outreach before the customer escalates.",
      },
      {
        title: "Advance deal stages based on technical milestones",
        description:
          "For enterprise deals with a technical evaluation phase, GAIA advances the HubSpot deal stage automatically when key GitHub milestones are reached, such as a proof-of-concept integration being merged.",
      },
      {
        title: "Track GitHub engagement signals in HubSpot contacts",
        description:
          "When a customer's GitHub organization forks your public repository or opens their first issue, GAIA logs this engagement signal in their HubSpot contact record so sales can reach out with perfectly timed outreach.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and HubSpot to GAIA",
        description:
          "Authenticate your GitHub organization and HubSpot portal in GAIA's integration settings. GAIA requests read access to GitHub releases and issues, and write access to HubSpot activities and tasks.",
      },
      {
        step: "Map GitHub events to HubSpot records",
        description:
          "Define how GitHub releases map to HubSpot deals—by customer label, milestone name, or repository. Configure which events create tasks, log activities, or send notifications to deal owners.",
      },
      {
        step: "GAIA keeps sales informed as code ships",
        description:
          "Every time a relevant GitHub event occurs, GAIA updates the appropriate HubSpot records in real time. Your sales team always knows what was recently shipped and which customers are affected.",
      },
    ],
    faqs: [
      {
        question:
          "How does GAIA match a GitHub release to the right HubSpot deal?",
        answer:
          "GAIA matches via customer or company labels on GitHub issues, release notes mentioning account names, or a mapping table you configure in GAIA's settings that associates repositories with specific HubSpot companies.",
      },
      {
        question:
          "Can GAIA pull HubSpot deal data into GitHub for engineer context?",
        answer:
          "Yes. GAIA can add a comment to a GitHub issue with the relevant HubSpot deal stage and contact information, giving engineers context about which customers are waiting on a fix or feature.",
      },
      {
        question: "Does this work with HubSpot's free tier?",
        answer:
          "GAIA's GitHub-HubSpot integration works with HubSpot Starter and above. Some features like custom deal properties and advanced timeline activities require HubSpot Professional or Enterprise.",
      },
      {
        question: "Can GAIA trigger HubSpot sequences when a feature ships?",
        answer:
          "Yes. When a GitHub release is tagged, GAIA can enroll specified contacts in a HubSpot sequence automatically, enabling fully automated re-engagement campaigns timed to feature releases.",
      },
    ],
  },

  "github-salesforce": {
    slug: "github-salesforce",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Connect GitHub releases to Salesforce opportunities so sales always knows what engineering just shipped",
    metaTitle:
      "GitHub + Salesforce Integration - Engineering to CRM Automation | GAIA",
    metaDescription:
      "Link GitHub and Salesforce with GAIA. Log releases to opportunities, alert account owners when features ship, and tie code milestones to pipeline activity.",
    keywords: [
      "GitHub Salesforce integration",
      "GitHub Salesforce automation",
      "log GitHub releases to Salesforce",
      "engineering Salesforce CRM sync",
      "release notification Salesforce",
      "GitHub Salesforce workflow",
    ],
    intro:
      "Enterprise sales cycles often hinge on engineering commitments—a prospect is waiting for a specific feature before signing, or a renewal is contingent on a bug fix being resolved. Yet in most organizations, the Salesforce opportunity and the GitHub milestone tracking that work exist in complete isolation. Account executives learn about releases through Slack messages or hallway conversations rather than automated, reliable notifications.\n\nGAIA creates a live connection between GitHub and Salesforce so engineering output automatically surfaces in your CRM. When a release is published in GitHub, GAIA logs the event against the relevant Salesforce opportunities and accounts, notifies the owning AE, and can advance the opportunity stage if the release satisfies a committed deliverable.\n\nFor enterprise engineering teams, this integration also works in reverse: when a high-value Salesforce opportunity is marked Closed Won, GAIA can create a GitHub milestone for the onboarding work, ensuring implementation starts immediately with full context about what was promised.",
    useCases: [
      {
        title: "Log GitHub releases to Salesforce opportunity timelines",
        description:
          "When a GitHub release is published, GAIA creates a Salesforce activity on every opportunity where the release is relevant, giving account executives a real-time log of what has been delivered.",
      },
      {
        title: "Alert AEs when committed features ship",
        description:
          "When a GitHub milestone closes and it was linked to a Salesforce opportunity, GAIA sends an in-app notification and email to the account executive so they can immediately follow up with the prospect.",
      },
      {
        title: "Advance opportunity stage on technical milestones",
        description:
          "For deals with a technical proof-of-concept phase, GAIA advances the Salesforce opportunity stage automatically when the corresponding GitHub milestone is marked complete, keeping your pipeline data accurate.",
      },
      {
        title: "Create GitHub milestones from Closed Won deals",
        description:
          "When a Salesforce opportunity is marked Closed Won, GAIA creates a GitHub milestone for implementation work with the deal's key deliverables as issues, ensuring the engineering team starts with full context.",
      },
      {
        title: "Escalate customer bugs by opportunity value",
        description:
          "When a GitHub issue is tagged with a customer account, GAIA checks the Salesforce opportunity value for that account and escalates the issue's priority in GitHub accordingly, ensuring high-value customer bugs get fastest attention.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Salesforce to GAIA",
        description:
          "Authenticate your GitHub organization and Salesforce org in GAIA's settings. GAIA uses OAuth for both connections and only requests the access levels needed for release logging and opportunity updates.",
      },
      {
        step: "Map repositories and milestones to Salesforce objects",
        description:
          "Define how GitHub repositories and milestones correspond to Salesforce accounts, opportunities, or custom objects. You can use naming conventions, labels, or a manual mapping table.",
      },
      {
        step: "GAIA automates the engineering-to-sales handoff",
        description:
          "Once configured, GAIA monitors GitHub for release and milestone events and updates Salesforce in real time, ensuring your CRM always reflects the current state of engineering deliverables.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA work with Salesforce custom objects and fields?",
        answer:
          "Yes. GAIA can read and write to standard Salesforce objects as well as custom objects and fields. During setup you can map GitHub event data to any Salesforce field in your org.",
      },
      {
        question:
          "How does GAIA know which Salesforce account a GitHub release affects?",
        answer:
          "GAIA matches based on labels in GitHub repositories or issues, release note content, or a mapping table you define in GAIA's settings that associates repositories with specific Salesforce accounts.",
      },
      {
        question: "Can GAIA trigger Salesforce flows or process builder rules?",
        answer:
          "GAIA updates Salesforce records via the standard API, which can trigger any Salesforce automation rules, flows, or process builder processes you have configured on those objects.",
      },
      {
        question:
          "Is this secure for enterprise Salesforce orgs with strict data policies?",
        answer:
          "Yes. GAIA uses OAuth 2.0 with Salesforce's standard connected app mechanism. No GitHub code or sensitive data is stored in Salesforce—only metadata like release names, dates, and links.",
      },
    ],
  },

  "github-teams": {
    slug: "github-teams",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Microsoft Teams",
    toolBSlug: "teams",
    tagline:
      "Post GitHub PR updates and release notifications directly into Microsoft Teams channels",
    metaTitle:
      "GitHub + Microsoft Teams Integration - Code Alerts in Teams | GAIA",
    metaDescription:
      "Connect GitHub and Microsoft Teams with GAIA. Stream PR reviews, issue alerts, and release announcements to Teams channels and keep your dev team informed.",
    keywords: [
      "GitHub Microsoft Teams integration",
      "GitHub Teams automation",
      "GitHub notifications Teams channel",
      "post GitHub releases to Teams",
      "GitHub Teams workflow",
      "developer Teams notifications",
    ],
    intro:
      "Microsoft Teams is the communication hub for many enterprise engineering teams, yet GitHub activity—PR reviews, issue escalations, release announcements—rarely surfaces there without manual effort. Developers have to monitor GitHub notifications separately, copy-paste important updates into Teams manually, and remind teammates about pending code reviews through ad-hoc messages.\n\nGAIA automates the flow of GitHub events into Microsoft Teams so your entire organization stays informed about code activity in the tools they already use. PR review requests appear in the relevant Teams channel. Release notes are posted when a new version ships. Critical bugs trigger adaptive card notifications that the team can act on without leaving Teams.\n\nFor enterprise organizations where Teams is the standard, this integration is essential for bridging the gap between the developer-facing GitHub workflow and the broader business communication happening in Teams, ensuring visibility without forcing non-developers to monitor GitHub directly.",
    useCases: [
      {
        title: "PR review requests posted to Teams",
        description:
          "When a pull request is opened or updated on GitHub, GAIA posts an adaptive card to the designated Teams channel or the reviewer's direct message, including the PR title, description, and a one-click link to review.",
      },
      {
        title: "Release announcements with changelog",
        description:
          "When a GitHub release is published, GAIA posts a formatted announcement card to the #engineering Teams channel with the version number, key changes, and a link to the full release notes.",
      },
      {
        title: "Incident alerts from GitHub issues",
        description:
          "Issues labeled as production incidents trigger an immediate Teams alert to the on-call channel with severity, description, and a direct link, ensuring the right people are paged through Teams rather than a separate tool.",
      },
      {
        title: "Daily PR status digest",
        description:
          "GAIA compiles a daily digest of open PRs sorted by age and reviewer assignment and posts it to the engineering Teams channel each morning so the team knows exactly what needs attention that day.",
      },
      {
        title: "Cross-team visibility on shared repositories",
        description:
          "For repositories maintained by multiple teams, GAIA routes GitHub notifications to the appropriate Teams channels based on the files changed or labels applied, ensuring each team only sees activity relevant to them.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Microsoft Teams to GAIA",
        description:
          "Authorize your GitHub organization and Microsoft Teams tenant in GAIA's integration settings. GAIA uses Azure AD OAuth for Teams and GitHub's OAuth for repository access.",
      },
      {
        step: "Configure event routing to Teams channels",
        description:
          "Map GitHub repositories and event types to specific Teams channels or individual users. Set filters to reduce noise and configure adaptive card templates for different event categories.",
      },
      {
        step: "GAIA delivers GitHub intelligence to Teams automatically",
        description:
          "GAIA monitors GitHub continuously and posts formatted notifications to Teams as events occur. Team members can respond to or act on notifications directly from within Teams.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA send adaptive cards instead of plain text messages to Teams?",
        answer:
          "Yes. GAIA uses Microsoft's adaptive card format to post richly structured GitHub notifications to Teams, including action buttons to approve PRs, close issues, or navigate to GitHub directly from the card.",
      },
      {
        question:
          "Does GAIA work with Teams private channels and guest access?",
        answer:
          "GAIA can post to public and private Teams channels that the GAIA bot has been added to. Guest access permissions are respected—GAIA will only post to channels where it has been explicitly granted access.",
      },
      {
        question:
          "Can team members interact with GitHub through Teams using GAIA?",
        answer:
          "Yes. GAIA's Teams bot understands natural language commands, so a team member can type '@GAIA close issue #42 in repo frontend' directly in Teams and GAIA will execute the action in GitHub.",
      },
      {
        question: "How is this different from the native GitHub app for Teams?",
        answer:
          "The native GitHub app for Teams provides basic notifications. GAIA adds AI-powered filtering, cross-tool automation, natural language commands, and customizable digest formats that the native app doesn't support.",
      },
    ],
  },

  "github-stripe": {
    slug: "github-stripe",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline:
      "Coordinate billing feature releases with Stripe configuration and catch payment-related code risks before they ship",
    metaTitle:
      "GitHub + Stripe Integration - Deploy and Billing Change Automation | GAIA",
    metaDescription:
      "Connect GitHub and Stripe with GAIA. Coordinate billing feature releases with Stripe changes, track payment-related PRs, and automate deployment notifications.",
    keywords: [
      "GitHub Stripe integration",
      "GitHub Stripe automation",
      "billing feature deployment GitHub",
      "Stripe GitHub release workflow",
      "payment engineering automation",
      "GitHub Stripe workflow",
    ],
    intro:
      "Payment engineering is high stakes—a breaking change to Stripe integration code or a billing feature shipped without coordinated Stripe product configuration can result in failed charges, broken checkouts, and revenue loss. Yet many engineering teams manage their GitHub and Stripe workflows in complete isolation, without guardrails that catch dangerous coordination errors before they reach production.\n\nGAIA connects GitHub and Stripe to add safety and coordination to payment engineering workflows. When a PR touches Stripe-related files, GAIA automatically flags it for extra review scrutiny and checks against current Stripe API versions. When a billing feature is deployed via a GitHub release, GAIA can verify that the corresponding Stripe product or price configuration has been updated before the release goes live.\n\nFor SaaS engineering teams, this integration provides the coordination layer between code deployments and billing infrastructure that currently relies on manual checklists and Slack reminders, replacing tribal knowledge with automated guardrails.",
    useCases: [
      {
        title: "Flag PRs that touch payment code for extra review",
        description:
          "When a pull request modifies files in payment-related directories or imports Stripe libraries, GAIA automatically adds a payment-sensitive label and assigns a designated payments reviewer, ensuring no billing change ships without proper scrutiny.",
      },
      {
        title: "Verify Stripe config before billing feature releases",
        description:
          "Before a GitHub release that includes billing changes goes live, GAIA checks that the required Stripe products, prices, and webhook endpoints are configured correctly in the target environment, alerting the team to any discrepancies.",
      },
      {
        title: "Create GitHub issues from Stripe webhook failures",
        description:
          "When Stripe webhook deliveries start failing, GAIA creates a GitHub issue in the relevant repository with the error details and a link to the Stripe dashboard, automatically assigning it to the payments team.",
      },
      {
        title: "Track Stripe API version upgrades as GitHub issues",
        description:
          "When Stripe announces a new API version, GAIA creates a GitHub issue in your billing repository with the breaking changes, migration guide link, and a suggested timeline based on Stripe's deprecation schedule.",
      },
      {
        title: "Deployment rollback checklist for billing changes",
        description:
          "When a GitHub release that touches billing code is deployed, GAIA creates a time-limited GitHub issue with a rollback checklist including Stripe-specific steps that stays open until the deployment is confirmed stable.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Stripe to GAIA",
        description:
          "Authenticate your GitHub repositories and Stripe account in GAIA's settings. GAIA uses restricted Stripe API keys with read-only access to the product catalog and webhook configuration.",
      },
      {
        step: "Define payment engineering rules",
        description:
          "Configure which directories or files are considered payment-sensitive, who the required reviewers are, what pre-release checks to run, and how to handle Stripe webhook failure alerts.",
      },
      {
        step: "GAIA enforces payment engineering guardrails automatically",
        description:
          "GAIA monitors both GitHub and Stripe for relevant events and enforces the rules you've defined, creating issues, alerting reviewers, or notifying on-call as configured without manual intervention.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA prevent a GitHub release from deploying if Stripe config is wrong?",
        answer:
          "GAIA can block a GitHub Actions deployment step by failing a pre-deployment check and posting the configuration discrepancies as a PR comment. Actual deployment gating requires integrating GAIA's check into your CI/CD pipeline.",
      },
      {
        question: "Does GAIA need full Stripe account access?",
        answer:
          "No. GAIA uses restricted Stripe API keys with read-only access to products, prices, and webhook endpoints. GAIA never needs access to customer payment data or live charge records.",
      },
      {
        question: "Can GAIA help us track which Stripe API version we're on?",
        answer:
          "Yes. GAIA can scan your codebase for the Stripe API version pinned in your configuration files and compare it against the current Stripe API version, creating a GitHub issue when you're running behind on upgrades.",
      },
      {
        question: "Does this work for both Stripe test mode and live mode?",
        answer:
          "Yes. GAIA can be configured to monitor your Stripe test environment for staging deployments and your live environment for production releases, with separate alerting thresholds for each.",
      },
    ],
  },

  "github-airtable": {
    slug: "github-airtable",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline:
      "Sync GitHub issues and PRs to Airtable so your project database always reflects your code reality",
    metaTitle:
      "GitHub + Airtable Integration - Sync Issues to Project Database | GAIA",
    metaDescription:
      "Connect GitHub and Airtable with GAIA. Sync issues, PRs, and releases to Airtable bases automatically for custom reporting, roadmapping, and project tracking.",
    keywords: [
      "GitHub Airtable integration",
      "GitHub Airtable automation",
      "sync GitHub issues to Airtable",
      "GitHub Airtable project tracking",
      "engineering database automation",
      "GitHub Airtable workflow",
    ],
    intro:
      "Airtable's flexible database structure makes it the go-to tool for custom project tracking, roadmapping, and engineering metrics—but keeping an Airtable base in sync with GitHub is a manual, time-consuming process. Issues get logged in GitHub but never make it to the roadmap base. PRs are merged but the corresponding Airtable record stays stuck in In Progress. Leadership dashboards built in Airtable are always a few days behind reality.\n\nGAIA syncs GitHub and Airtable in real time so your custom project databases are always accurate. Issues created in GitHub appear in your Airtable roadmap base automatically. PR status changes update the corresponding Airtable record. Releases trigger new rows in your release tracking base with the relevant metadata.\n\nFor product-engineering teams that have built custom Airtable workflows for planning and reporting, this integration removes the manual data entry burden that makes those workflows unsustainable at scale.",
    useCases: [
      {
        title: "Sync GitHub issues to an Airtable roadmap base",
        description:
          "When a GitHub issue is created or updated, GAIA creates or updates the corresponding record in your Airtable roadmap base, mapping issue fields like labels, assignees, and milestones to your custom Airtable columns.",
      },
      {
        title: "Track PR cycle time in Airtable",
        description:
          "GAIA records PR open and merge timestamps in an Airtable base, enabling you to build custom views and formulas that track engineering cycle time, review duration, and throughput metrics without manual data collection.",
      },
      {
        title: "Update release tracking base on GitHub releases",
        description:
          "When a GitHub release is published, GAIA adds a new record to your Airtable release tracking base with the version number, date, number of issues closed, and a link to the release notes.",
      },
      {
        title: "Weekly engineering metrics compiled into Airtable",
        description:
          "GAIA compiles weekly engineering metrics—issues opened and closed, PRs merged, releases shipped—into an Airtable summary record that feeds your leadership reporting views automatically.",
      },
      {
        title: "Map GitHub labels to Airtable select fields",
        description:
          "GitHub issue labels like priority::high or type::bug are automatically mapped to corresponding Airtable single-select or multi-select fields, ensuring your database categorization stays consistent with GitHub's labeling system.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Airtable to GAIA",
        description:
          "Authorize your GitHub repositories and Airtable workspace in GAIA's settings. Specify which Airtable base and table to sync with each GitHub repository.",
      },
      {
        step: "Map GitHub fields to Airtable columns",
        description:
          "Configure how GitHub data maps to your Airtable schema—which GitHub fields populate which Airtable columns, how to handle new GitHub labels, and whether to create new records or update existing ones.",
      },
      {
        step: "GAIA keeps your Airtable base synchronized with GitHub",
        description:
          "GAIA monitors GitHub for issue, PR, and release events and updates your Airtable base in real time. Your dashboards and views always reflect current GitHub data without manual imports.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA sync data from Airtable back to GitHub?",
        answer:
          "Yes. Two-way sync is supported—if you update an issue status in Airtable, GAIA can update the corresponding GitHub issue label or assignee. This is useful for product managers who manage priority in Airtable but want changes reflected in GitHub.",
      },
      {
        question: "Does GAIA work with Airtable's linked records feature?",
        answer:
          "Yes. GAIA can create linked records in Airtable—for example, linking a PR record to the issue records it closes—preserving the relational structure of your data rather than flattening everything into a single table.",
      },
      {
        question: "Can I use Airtable automations alongside GAIA's sync?",
        answer:
          "Yes. GAIA's record updates trigger Airtable's native automations just like manual edits do, so you can combine GAIA's GitHub sync with Airtable's own automation features for additional downstream actions.",
      },
      {
        question: "How does GAIA handle GitHub issues that are deleted?",
        answer:
          "When a GitHub issue is deleted, GAIA can either delete the corresponding Airtable record, mark it as deleted in a status field, or leave it as an archived record—depending on your configuration preference.",
      },
    ],
  },

  "github-loom": {
    slug: "github-loom",
    toolA: "GitHub",
    toolASlug: "github",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Attach Loom walkthroughs to PRs and auto-request video reviews for complex code changes",
    metaTitle:
      "GitHub + Loom Integration - Video Code Reviews and PR Walkthroughs | GAIA",
    metaDescription:
      "Connect GitHub and Loom with GAIA. Attach Loom walkthroughs to PRs, request video reviews for complex changes, and make async code review more effective.",
    keywords: [
      "GitHub Loom integration",
      "GitHub Loom automation",
      "Loom code review PR walkthrough",
      "video PR review GitHub",
      "async code review Loom",
      "GitHub Loom workflow",
    ],
    intro:
      "Complex pull requests are notoriously hard to review from code alone. A PR that refactors a core service, introduces a new architecture pattern, or changes subtle UX behavior is difficult to understand through diff reading, leading to slow or shallow reviews and frequently missed issues. Engineers end up in long Zoom calls just to explain a change that could have been covered in a three-minute Loom video.\n\nGAIA connects GitHub and Loom to make async code review richer and more efficient. When a large or complex PR is opened, GAIA prompts the author to record a Loom walkthrough and attaches the video link to the PR automatically. When a reviewer requests changes, GAIA can suggest recording a Loom to explain the feedback rather than writing a lengthy comment thread. When a Loom documenting a bug is shared with GAIA, it creates the corresponding GitHub issue with the video embedded.\n\nFor distributed engineering teams that rely on async communication, this integration bridges the gap between recorded video explanations and the GitHub code review workflow, reducing time-to-review and improving the quality of feedback on complex changes.",
    useCases: [
      {
        title: "Prompt PR authors to record a Loom for large changes",
        description:
          "When a PR exceeds a configured number of changed lines or files, GAIA posts a comment prompting the author to record a Loom walkthrough and providing a direct link to create one, improving review quality for complex changes.",
      },
      {
        title: "Auto-format Loom links in PR descriptions as previews",
        description:
          "When a Loom URL is included anywhere in a PR description or comment, GAIA formats it as a prominent preview card at the top of the PR so reviewers immediately see there's a video walkthrough available.",
      },
      {
        title: "Create GitHub issues from Loom bug recordings",
        description:
          "When a team member records a Loom video documenting a bug and shares it via GAIA, GAIA creates a GitHub issue with the Loom video embedded, the transcript as the issue body, and automatic label assignment.",
      },
      {
        title: "Request Loom explanations for complex review comments",
        description:
          "When a reviewer leaves a complex change request on a PR, GAIA suggests they record a Loom to explain the concern, resulting in clearer feedback and faster resolution than back-and-forth text threads.",
      },
      {
        title: "Build a Loom walkthrough library from merged PRs",
        description:
          "GAIA maintains a collection of Loom walkthroughs attached to merged PRs, organized by date and feature area, so new team members have a video library of how the codebase evolved over time.",
      },
    ],
    howItWorks: [
      {
        step: "Connect GitHub and Loom to GAIA",
        description:
          "Authorize your GitHub repositories and Loom workspace in GAIA's settings. GAIA uses GitHub's API for PR interactions and Loom's API to access and embed video metadata.",
      },
      {
        step: "Configure Loom prompts and thresholds",
        description:
          "Set the PR size threshold that triggers a walkthrough prompt, define which repositories require video reviews for specific file types, and configure how Loom links are displayed in PRs.",
      },
      {
        step: "GAIA makes video a first-class part of code review",
        description:
          "GAIA monitors PR creation and updates, prompts for Looms when helpful, embeds video links prominently, and maintains a searchable index of PR walkthroughs for your team.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA actually embed the Loom video in GitHub or just link to it?",
        answer:
          "GitHub doesn't support embedded video playback in PR descriptions. GAIA formats the Loom link as a prominent thumbnail preview using Loom's embed URL, which shows the video title and a preview image with a clear link to watch it.",
      },
      {
        question:
          "Can GAIA use Loom transcripts to summarize a PR for non-technical reviewers?",
        answer:
          "Yes. GAIA can extract the auto-generated Loom transcript and create a plain-language summary of the walkthrough, which it can post to Slack or include in a Jira ticket for stakeholders who don't read code.",
      },
      {
        question:
          "Is this useful for teams that don't currently do video reviews?",
        answer:
          "Absolutely. GAIA's prompts are configurable—you can start with only suggesting Looms for very large PRs or specific repositories, gradually normalizing the practice without overwhelming the team with new process requirements.",
      },
      {
        question:
          "Can GAIA notify a reviewer when a new Loom walkthrough is added to a PR?",
        answer:
          "Yes. When a Loom link is added to a PR that already has pending reviewers, GAIA sends a notification to the assigned reviewers alerting them that a walkthrough has been posted, often prompting faster review.",
      },
    ],
  },

  "notion-jira": {
    slug: "notion-jira",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Jira",
    toolBSlug: "jira",
    tagline:
      "Sync Notion project docs with Jira issues so your specs and sprint tickets always match",
    metaTitle:
      "Notion + Jira Integration - Sync Specs and Sprint Tickets | GAIA",
    metaDescription:
      "Connect Notion and Jira with GAIA. Sync spec pages to Jira epics, create tickets from Notion requirements, and keep your docs aligned with your sprint board.",
    keywords: [
      "Notion Jira integration",
      "Notion Jira automation",
      "sync Notion specs to Jira",
      "create Jira tickets from Notion",
      "Notion Jira project sync",
      "Notion Jira workflow",
    ],
    intro:
      "Product and engineering teams frequently maintain separate workspaces for the same information—requirements live in Notion pages while the corresponding Jira epics and tickets are maintained independently. When the Notion spec changes, the Jira tickets rarely update to match. When a Jira ticket's scope evolves during development, the Notion document doesn't reflect the change. Teams spend hours reconciling two sets of documentation that should be in sync.\n\nGAIA bridges Notion and Jira so that documentation and project tracking reinforce each other rather than drifting apart. When a Notion requirements page is finalized, GAIA can generate the corresponding Jira epic and user stories automatically. When a Jira ticket is updated with new acceptance criteria, GAIA updates the linked Notion section. When a sprint closes in Jira, GAIA updates the Notion project doc with the outcomes.\n\nFor product-engineering teams that use Notion as their spec repository and Jira as their sprint board, this integration eliminates the manual overhead of maintaining parallel documentation, ensuring that everyone—regardless of which tool they prefer—has access to accurate, current information.",
    useCases: [
      {
        title: "Generate Jira epics and stories from Notion specs",
        description:
          "When a Notion requirements page is marked as ready for development, GAIA reads the document structure and creates a corresponding Jira epic with user stories derived from the spec's sections, saving hours of ticket creation work.",
      },
      {
        title: "Sync Jira ticket status back to Notion project pages",
        description:
          "GAIA monitors Jira for status changes and updates the corresponding Notion database records or inline callouts, so the Notion project page always reflects which features are in development, in review, or shipped.",
      },
      {
        title: "Create Notion meeting notes linked to Jira tickets",
        description:
          "When a Jira ticket is discussed in a meeting, GAIA creates a linked Notion page for meeting notes with the ticket context pre-filled, ensuring decisions and discussions are captured alongside the work being tracked.",
      },
      {
        title: "Sprint retrospective doc from closed Jira tickets",
        description:
          "At sprint end, GAIA compiles all closed Jira tickets into a structured Notion retrospective page including ticket titles, assignees, and story points, giving the team a ready-made foundation for their retro discussion.",
      },
      {
        title: "Update Notion roadmap from Jira milestone completions",
        description:
          "When a Jira version or fix version is released, GAIA updates the corresponding row in your Notion roadmap database, marking the milestone as shipped and adding the release date automatically.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Jira to GAIA",
        description:
          "Authorize your Notion workspace and Jira project in GAIA's integration settings. GAIA requests read and write access to specific Notion databases and Jira projects you designate.",
      },
      {
        step: "Map Notion pages to Jira objects",
        description:
          "Define which Notion databases correspond to which Jira projects, how Notion properties map to Jira fields, and which triggers—like a Notion status change—should create or update Jira tickets.",
      },
      {
        step: "GAIA keeps your docs and tickets in sync",
        description:
          "GAIA monitors both Notion and Jira for changes and synchronizes them according to your configuration, ensuring that documentation and project tracking always reflect the same reality.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create Notion pages from Jira epics that already exist?",
        answer:
          "Yes. GAIA can run an initial import that creates Notion pages for existing Jira epics, allowing you to establish the sync relationship even if Jira was already populated before you set up the integration.",
      },
      {
        question:
          "Does GAIA handle rich text formatting when converting between Notion and Jira?",
        answer:
          "GAIA converts Notion's rich text blocks to Jira's wiki markup and vice versa, preserving headings, lists, code blocks, and basic formatting. Complex Notion page layouts are simplified to flat Jira descriptions.",
      },
      {
        question:
          "What happens when a Jira ticket is deleted—does GAIA delete the Notion page?",
        answer:
          "No. GAIA does not delete Notion pages when a Jira ticket is removed. Instead, it marks the linked Notion record as archived or removes the Jira link property, leaving the documentation intact.",
      },
      {
        question: "Can GAIA sync comments between Notion and Jira?",
        answer:
          "GAIA can sync Jira comments to Notion page comments and vice versa, but comment sync is optional and off by default to avoid cluttering either tool with duplicate discussion threads.",
      },
    ],
  },

  "notion-salesforce": {
    slug: "notion-salesforce",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Sync Salesforce account data to Notion wikis so your team always has current customer context",
    metaTitle:
      "Notion + Salesforce Integration - CRM Data to Knowledge Base | GAIA",
    metaDescription:
      "Connect Notion and Salesforce with GAIA. Sync account data and deal notes to Notion, auto-generate customer wikis, and keep CRM knowledge accessible to your whole team.",
    keywords: [
      "Notion Salesforce integration",
      "Notion Salesforce automation",
      "sync Salesforce to Notion",
      "Salesforce customer wiki Notion",
      "CRM knowledge base automation",
      "Notion Salesforce workflow",
    ],
    intro:
      "Salesforce holds your company's most valuable customer data, but it's structured for CRM workflows rather than human reading. Account managers who need to understand a customer's history, product teams who need to know what features were promised in a deal, and onboarding teams who need to brief themselves on a new account all struggle to extract the knowledge they need from Salesforce's field-heavy interface.\n\nGAIA bridges Salesforce and Notion by automatically generating readable, organized knowledge in Notion from the structured data in Salesforce. When an opportunity closes, GAIA creates a customer wiki in Notion with the deal details, key contacts, and committed deliverables. When Salesforce account data changes, the corresponding Notion page updates automatically.\n\nFor customer success, solutions engineering, and product teams, this integration turns Salesforce from a system of record into a source of readable, actionable knowledge that everyone can access in the tool they use every day.",
    useCases: [
      {
        title: "Auto-generate customer wikis from Closed Won deals",
        description:
          "When a Salesforce opportunity is marked Closed Won, GAIA creates a structured Notion page for the new customer including account details, key contacts, deal terms, and a blank onboarding checklist.",
      },
      {
        title: "Sync account health data to Notion dashboards",
        description:
          "GAIA pulls Salesforce account health indicators—renewal date, ARR, product tier, support tier—into a Notion database so your customer success team has a live dashboard without toggling between tools.",
      },
      {
        title: "Create Notion meeting prep pages from Salesforce opportunities",
        description:
          "Before a Salesforce opportunity reaches a key stage, GAIA creates a Notion meeting prep page with the opportunity history, contact information, and previous meeting notes, so your AE walks in fully briefed.",
      },
      {
        title: "Log Notion meeting notes back to Salesforce activities",
        description:
          "When a meeting note is finalized in Notion, GAIA creates a corresponding Salesforce activity log on the relevant opportunity or account record, keeping the CRM up to date without requiring the AE to double-enter information.",
      },
      {
        title: "Update Notion product feedback database from Salesforce notes",
        description:
          "GAIA scans Salesforce opportunity notes and call logs for product feedback mentions and adds them to a Notion product feedback database, giving product teams a structured view of what customers are requesting.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Salesforce to GAIA",
        description:
          "Authenticate your Notion workspace and Salesforce org in GAIA's settings. Specify which Salesforce objects (Accounts, Opportunities, Contacts) should sync to which Notion databases.",
      },
      {
        step: "Configure sync triggers and field mappings",
        description:
          "Define which Salesforce events create or update Notion pages, how Salesforce fields map to Notion properties, and which Notion database changes should write back to Salesforce activities.",
      },
      {
        step: "GAIA turns CRM data into accessible knowledge",
        description:
          "GAIA monitors Salesforce for the triggers you've configured and automatically creates or updates the corresponding Notion pages, ensuring your team always has current customer context in a readable format.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA pull custom Salesforce fields into Notion?",
        answer:
          "Yes. During setup GAIA reads your Salesforce object schema including custom fields and objects, allowing you to map any Salesforce data to Notion properties in your database.",
      },
      {
        question: "Is the Notion-to-Salesforce sync real-time or periodic?",
        answer:
          "Salesforce-to-Notion sync is event-driven and near real-time. Notion-to-Salesforce sync (e.g., logging meeting notes) can be triggered manually by the user or automatically when a Notion page reaches a specified status.",
      },
      {
        question:
          "Does GAIA expose sensitive CRM data to unauthorized Notion users?",
        answer:
          "GAIA writes to the Notion pages and databases you designate and respects Notion's existing permission model. If a Notion page is restricted to specific members, only those members can view the Salesforce-derived content.",
      },
      {
        question:
          "Can multiple Salesforce accounts map to a single Notion page?",
        answer:
          "Yes. For customers with multiple Salesforce account records (e.g., parent and child accounts), GAIA can consolidate the relevant data into a single Notion page or create linked child pages, depending on your configured structure.",
      },
    ],
  },

  "notion-loom": {
    slug: "notion-loom",
    toolA: "Notion",
    toolASlug: "notion",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Embed Loom videos into Notion pages automatically and create docs from video transcripts",
    metaTitle:
      "Notion + Loom Integration - Video Knowledge Base Automation | GAIA",
    metaDescription:
      "Connect Notion and Loom with GAIA. Auto-embed Loom videos in Notion pages, generate docs from transcripts, and build a searchable video knowledge base.",
    keywords: [
      "Notion Loom integration",
      "Notion Loom automation",
      "embed Loom in Notion",
      "Loom transcript to Notion",
      "video knowledge base Notion",
      "Notion Loom workflow",
    ],
    intro:
      "Loom videos capture knowledge in a way that written documentation can't—a product walkthrough, a design critique, a process explanation—but video content is notoriously hard to search and organize. Recordings pile up in Loom without being linked to the relevant Notion pages where they would provide the most context. Knowledge shared in a video gets lost when someone new joins the team because no one connected it to the written documentation.\n\nGAIA bridges Notion and Loom so that video and written knowledge reinforce each other. When a Loom is recorded and shared with GAIA, it is automatically embedded in the relevant Notion page based on the video's title and content. GAIA can also extract the Loom transcript and generate a structured Notion document from it, making video knowledge searchable and scannable.\n\nFor teams that rely heavily on async video communication, this integration transforms a scattered Loom library into a structured, searchable knowledge base anchored in Notion, ensuring that important knowledge shared in video format is never lost.",
    useCases: [
      {
        title: "Auto-embed Loom recordings in Notion pages by topic",
        description:
          "When a Loom video is recorded and tagged with a project name or topic, GAIA finds the relevant Notion page and embeds the video in a dedicated Recordings section, keeping video content organized with its written context.",
      },
      {
        title: "Generate Notion docs from Loom transcripts",
        description:
          "GAIA extracts the auto-generated Loom transcript, structures it into a Notion page with headings, bullet points, and action items, making the video's content searchable and scannable for those who prefer reading over watching.",
      },
      {
        title: "Create Notion action item pages from meeting Looms",
        description:
          "When a Loom is recorded as a meeting update or project review, GAIA identifies the action items mentioned in the transcript and creates a Notion task page with the items listed, assignees suggested, and the original video embedded.",
      },
      {
        title: "Build a searchable onboarding video library in Notion",
        description:
          "GAIA automatically catalogs Loom recordings tagged as onboarding content into a dedicated Notion database with title, description, speaker, duration, and a direct embed, creating a self-updating new hire resource library.",
      },
      {
        title: "Link Loom design walkthroughs to Notion specs",
        description:
          "When a designer records a Loom walking through a new design, GAIA links the video to the corresponding Notion spec page and adds a summary of the walkthrough as a page comment, keeping design decisions documented alongside specs.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Notion and Loom to GAIA",
        description:
          "Authorize your Notion workspace and Loom account in GAIA's integration settings. Specify which Notion databases should receive embedded Loom videos and transcripts.",
      },
      {
        step: "Configure video routing and transcript rules",
        description:
          "Define how Loom videos are matched to Notion pages—by video title, tags, or workspace folder—and configure whether GAIA should embed the video, generate a transcript document, extract action items, or all three.",
      },
      {
        step: "GAIA builds your video knowledge base automatically",
        description:
          "When a Loom is recorded and processed, GAIA routes it to the appropriate Notion pages and generates any configured documents. Your knowledge base grows automatically as your team continues to record.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA embed Loom videos directly in Notion or just link to them?",
        answer:
          "GAIA uses Notion's embed block to insert Loom videos directly into pages so they can be watched without leaving Notion. The video appears as an inline playable embed rather than an external link.",
      },
      {
        question:
          "How accurate are Loom's auto-generated transcripts for GAIA to work with?",
        answer:
          "Loom's transcripts are generally accurate for clear speech but may need light editing for technical terms or heavy accents. GAIA's transcript-to-Notion feature works well for structured content and clearly stated action items.",
      },
      {
        question: "Can GAIA handle a large backlog of existing Loom videos?",
        answer:
          "Yes. GAIA can run an initial batch import of your existing Loom library, creating Notion pages or database entries for each video. You can filter which videos to import by date range, workspace folder, or creator.",
      },
      {
        question:
          "What if I record a Loom that belongs to multiple Notion pages?",
        answer:
          "GAIA can embed the same Loom video in multiple Notion pages if the video's tags or content match multiple pages. You can also manually specify multiple destination pages when sharing the Loom via GAIA.",
      },
    ],
  },
};
