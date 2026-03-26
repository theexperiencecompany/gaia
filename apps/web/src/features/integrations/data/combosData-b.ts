import type { IntegrationCombo } from "./combosData";

export const combosBatchB: Record<string, IntegrationCombo> = {
  "gmail-github": {
    slug: "gmail-github",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "GitHub",
    toolBSlug: "github",
    tagline: "Turn emails into GitHub issues and route PR alerts to your inbox",
    metaTitle: "Gmail + GitHub Automation - Email to Issues, PR Alerts | GAIA",
    metaDescription:
      "Connect Gmail and GitHub with GAIA. Create issues from emails, get pull request notifications in your inbox, and keep engineering and stakeholders aligned automatically.",
    keywords: [
      "Gmail GitHub integration",
      "email to GitHub issue",
      "Gmail GitHub automation",
      "GitHub PR notification email",
      "connect Gmail and GitHub",
      "GitHub issue from email",
    ],
    intro:
      "Bug reports arrive by email. Feature requests come from clients over email threads. Yet your engineering workflow lives entirely in GitHub. The gap between these two worlds creates a tedious manual loop: copy the email, open GitHub, create an issue, paste the details, and remember to update both sides when progress is made.\n\nGAIA eliminates this translation layer by connecting Gmail and GitHub directly. When a client emails a bug report or a stakeholder sends a feature request, GAIA can create a properly formatted GitHub issue with the right labels, assignees, and milestones extracted from the email context. Conversely, when pull requests are opened, reviewed, or merged, GAIA can route structured summaries to relevant inboxes so non-technical stakeholders stay informed without needing GitHub access.\n\nThis integration is particularly valuable for teams where product managers, client-facing staff, and engineers need to collaborate across the email-to-code divide without losing context or creating duplicated effort.",
    useCases: [
      {
        title: "Create GitHub issues from bug report emails",
        description:
          "When a client or teammate emails a bug report, GAIA parses the email, extracts the key details — steps to reproduce, environment, severity — and creates a formatted GitHub issue in the correct repository with appropriate labels. The original sender is referenced in the issue body so engineers have full context.",
      },
      {
        title: "Feature request pipeline from email to backlog",
        description:
          "Product feedback and feature requests sent by email are automatically converted into GitHub issues tagged as feature requests and added to the relevant project backlog. GAIA extracts the core request and formats it as a user story so engineers can act on it immediately.",
      },
      {
        title: "PR status notifications for non-technical stakeholders",
        description:
          "When a pull request tied to a client-facing feature is opened, reviewed, or merged, GAIA sends a plain-language email summary to the relevant stakeholders so they know progress is being made without needing to navigate GitHub.",
      },
      {
        title: "Release notification emails",
        description:
          "When a new GitHub release is published, GAIA composes and sends a formatted release summary email to your distribution list — including changelog highlights, known issues, and upgrade notes — keeping clients and internal teams informed automatically.",
      },
      {
        title: "Email-triggered issue comments",
        description:
          "When a stakeholder replies to a GitHub notification email with a comment or update, GAIA posts their reply as a comment on the original GitHub issue so the conversation stays unified in the engineering workflow.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and GitHub to GAIA",
        description:
          "Authenticate your Gmail account and GitHub organization or personal account in GAIA's integration settings. GAIA uses OAuth for both connections so your credentials remain secure.",
      },
      {
        step: "Configure your routing rules",
        description:
          "Tell GAIA which email senders, labels, or keywords should trigger issue creation, which repositories to target, and which GitHub events should send email notifications. You can specify assignees, labels, and milestones as part of the rules.",
      },
      {
        step: "GAIA automates the email-to-GitHub workflow",
        description:
          "Once configured, GAIA monitors Gmail and GitHub continuously, creating issues from qualifying emails and dispatching notifications for relevant GitHub events without any manual intervention.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create issues in specific repositories based on email content?",
        answer:
          "Yes. You can set up rules that route emails to different repositories based on sender, subject keywords, Gmail labels, or AI classification of the email content. For example, emails about your mobile app can go to the mobile-app repo while API-related emails go to the backend repo.",
      },
      {
        question:
          "Will GAIA avoid creating duplicate issues if the same bug is emailed twice?",
        answer:
          "GAIA checks for existing open issues with similar titles and content before creating a new one. If a likely duplicate is found, GAIA can add the new email as a comment on the existing issue instead, keeping discussions consolidated.",
      },
      {
        question:
          "Can GAIA handle GitHub notifications I already receive in Gmail?",
        answer:
          "Yes. GAIA can parse GitHub's native notification emails and enrich them — summarizing long PR review threads, extracting action items, or routing specific notifications to teammates — rather than just letting them accumulate in your inbox.",
      },
    ],
  },

  "gmail-trello": {
    slug: "gmail-trello",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Convert emails into Trello cards and keep your boards updated from your inbox",
    metaTitle:
      "Gmail + Trello Automation - Email to Cards, Inbox to Board | GAIA",
    metaDescription:
      "Automate Gmail and Trello with GAIA. Create Trello cards from emails, update board lists based on email replies, and manage tasks without switching between your inbox and boards.",
    keywords: [
      "Gmail Trello integration",
      "email to Trello card",
      "Gmail Trello automation",
      "create Trello card from email",
      "connect Gmail and Trello",
      "Trello email workflow",
    ],
    intro:
      "Email is where work requests arrive; Trello is where work gets organized and tracked. But bridging the two requires constant manual effort — reading emails, deciding which board and list they belong in, creating cards, copying over the relevant details, and then returning to Gmail to reply. For teams managing high email volumes, this becomes a significant time drain that takes attention away from actual work.\n\nGAIA connects Gmail and Trello so that email content flows directly into your boards. Incoming emails that represent tasks, requests, or deliverables can be automatically converted into Trello cards with the right metadata, assigned to the correct list, and linked back to the original email thread. When card statuses change in Trello, GAIA can notify the relevant people via email so external stakeholders stay informed without needing Trello access.\n\nThis integration is ideal for client-facing teams, project managers, and operations teams who live in both email and Trello and want to eliminate the manual handoff between the two.",
    useCases: [
      {
        title: "Create Trello cards from client request emails",
        description:
          "When a client emails a new request, GAIA creates a Trello card in the appropriate board and list, pre-populated with the request details, due date if mentioned, and a link back to the original email thread so your team has full context when they pick up the card.",
      },
      {
        title: "Move cards based on email replies",
        description:
          "When you or a teammate sends an email update on a project, GAIA can move the corresponding Trello card to the next list — for example, from 'In Progress' to 'Awaiting Client Feedback' — so your board reflects the actual state of work without manual updates.",
      },
      {
        title: "Email notifications when cards are completed",
        description:
          "When a Trello card is moved to 'Done', GAIA composes and sends a completion notification email to the relevant stakeholder, summarizing what was done and any next steps, keeping clients informed without requiring manual follow-up emails.",
      },
      {
        title: "Daily board digest to email",
        description:
          "GAIA sends a morning email digest summarizing the state of your Trello boards — cards due today, overdue items, and recently completed tasks — so you start the day with a clear picture of priorities without opening Trello.",
      },
      {
        title: "Attachment forwarding from email to cards",
        description:
          "Files and documents sent as email attachments are automatically attached to the corresponding Trello card so your team has everything they need in one place without hunting through email threads for assets.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Trello to GAIA",
        description:
          "Authenticate your Gmail account and Trello workspace in GAIA's integration settings. GAIA will ask which boards it should have access to so you control the scope of the integration.",
      },
      {
        step: "Set up your card creation rules",
        description:
          "Tell GAIA which types of emails should become Trello cards, which board and list they should land in, how to set labels and due dates, and who to assign cards to. Rules can be based on sender, Gmail labels, keywords, or AI classification.",
      },
      {
        step: "GAIA manages the email-to-board pipeline automatically",
        description:
          "GAIA monitors your Gmail and Trello boards continuously, creating cards from qualifying emails and sending notifications for board events according to your rules — no manual copying required.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA create cards on different Trello boards based on the email content?",
        answer:
          "Yes. You can set rules that route emails to different boards based on sender domain, Gmail labels, or AI-detected content type. For example, design request emails go to your Design board while support emails go to your Support board.",
      },
      {
        question:
          "What happens to the original email after GAIA creates a Trello card?",
        answer:
          "GAIA can apply a Gmail label such as 'Sent to Trello' to the original email and optionally archive it so your inbox stays clean. The link back to the email thread is stored in the Trello card description so you can always find the source.",
      },
      {
        question:
          "Can I create a Trello card manually by forwarding an email to GAIA?",
        answer:
          "Yes. In addition to automatic rules, you can forward any email to GAIA with a quick instruction like 'add this to the Marketing board under To Do' and GAIA will create the card immediately.",
      },
    ],
  },

  "gmail-discord": {
    slug: "gmail-discord",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline:
      "Route important emails to Discord channels and keep your community in the loop",
    metaTitle:
      "Gmail + Discord Automation - Email Notifications to Discord | GAIA",
    metaDescription:
      "Connect Gmail and Discord with GAIA. Forward important email alerts to Discord channels, notify your community about key updates, and bridge email communications with Discord automatically.",
    keywords: [
      "Gmail Discord integration",
      "email to Discord notification",
      "Gmail Discord automation",
      "forward email to Discord",
      "connect Gmail and Discord",
      "Discord email alerts",
    ],
    intro:
      "Many teams and communities coordinate in Discord but still receive critical notifications — system alerts, client emails, payment confirmations, and vendor communications — via Gmail. Manually monitoring both platforms creates alert fatigue and gaps in awareness, especially for distributed teams spread across time zones.\n\nGAIA bridges Gmail and Discord by routing important email notifications to the right Discord channels automatically. System alert emails can post to a #monitoring channel. Client communication summaries can land in a #clients channel. Financial notifications can appear in a #finance channel. Your Discord server becomes a real-time nerve center that pulls in email-based signals without anyone having to relay them manually.\n\nThis is especially useful for developer communities, open-source projects, gaming studios, and creator-led businesses that run their operations inside Discord but still interact with partners and vendors over email.",
    useCases: [
      {
        title: "System alert emails to Discord monitoring channel",
        description:
          "Infrastructure monitoring tools often send alert emails when systems go down or thresholds are breached. GAIA routes these emails to your #monitoring Discord channel the moment they arrive, with a formatted summary so your on-call team can respond immediately without checking email.",
      },
      {
        title: "Client update summaries to team Discord",
        description:
          "When important client emails arrive in Gmail, GAIA posts a concise summary to the relevant Discord channel so the whole team is aware of client needs and context without being CC'd on every email thread.",
      },
      {
        title: "Payment and billing notifications",
        description:
          "Payment confirmations, subscription renewals, and billing alerts from services like Stripe or PayPal arrive by email. GAIA forwards these to a private Discord channel for your finance or operations team so nothing is missed.",
      },
      {
        title: "Community announcement emails to Discord",
        description:
          "When you send a newsletter or announcement to your email list, GAIA can simultaneously post a version to your Discord announcements channel so your Discord community receives the news at the same time as your email subscribers.",
      },
      {
        title: "New lead or inquiry alerts",
        description:
          "When a contact form submission or sales inquiry arrives in Gmail, GAIA posts an alert to your #sales or #leads Discord channel so the team can discuss and assign follow-up immediately rather than waiting for someone to check email.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Discord to GAIA",
        description:
          "Authenticate your Gmail account and authorize GAIA to post to your Discord server. GAIA uses Discord webhooks or bot permissions to post to specific channels, so you control exactly where messages appear.",
      },
      {
        step: "Map email types to Discord channels",
        description:
          "Define rules for which emails should route to which Discord channels. You can filter by sender, subject keywords, Gmail labels, or let GAIA use AI classification to determine the appropriate channel.",
      },
      {
        step: "GAIA monitors Gmail and posts to Discord automatically",
        description:
          "GAIA watches your inbox continuously and posts formatted notifications to the configured Discord channels as qualifying emails arrive, keeping your Discord server updated in real time.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA format the Discord message differently from the original email?",
        answer:
          "Yes. GAIA can post the full email, an AI-generated summary, or a custom template that extracts specific fields like sender, subject, and key points. For noisy alert emails, a concise one-line summary is often more useful than the full email body.",
      },
      {
        question:
          "Can GAIA post to multiple Discord channels for the same email?",
        answer:
          "Yes. You can configure rules where a single email triggers posts to multiple channels. For example, a major client email might post to both #clients and #management so both teams are notified simultaneously.",
      },
      {
        question: "Will GAIA work with private Discord channels?",
        answer:
          "Yes, as long as the GAIA bot or webhook has permission to post in the private channel. During setup, you grant GAIA access to specific channels, and it will only post where it is authorized.",
      },
    ],
  },

  "gmail-drive": {
    slug: "gmail-drive",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline: "Automatically save email attachments and content to Google Drive",
    metaTitle:
      "Gmail + Google Drive Automation - Save Attachments Automatically | GAIA",
    metaDescription:
      "Connect Gmail and Google Drive with GAIA. Auto-save email attachments to Drive folders, convert email threads to Drive documents, and keep files organized without manual downloading.",
    keywords: [
      "Gmail Google Drive integration",
      "save email attachments to Drive",
      "Gmail Drive automation",
      "email to Google Drive",
      "connect Gmail and Google Drive",
      "automatic email file backup",
    ],
    intro:
      "Email attachments are one of the most common ways files enter a team's workflow, yet they remain locked inside Gmail threads rather than organized in a shared Drive folder where everyone can find them. Downloading attachments manually, renaming them, and uploading them to the right folder is a repetitive chore that adds up to hours of wasted time each week.\n\nGAIA automates the entire pipeline from Gmail to Google Drive. Attachments from qualifying emails are saved to the correct Drive folders automatically, named consistently, and organized by sender, project, or date depending on your preferences. Entire email threads can be converted into Drive documents for archiving. Contracts, invoices, and reports that arrive by email end up exactly where your team expects to find them.\n\nThis integration is invaluable for finance teams handling invoices, legal teams receiving contracts, operations teams managing vendor documents, and any team that regularly receives files by email and needs them accessible in a shared Drive.",
    useCases: [
      {
        title: "Auto-save invoice attachments to the correct Drive folder",
        description:
          "When an invoice or receipt arrives in Gmail, GAIA extracts the attachment and saves it to the designated Drive folder for that vendor or project. The file is named consistently — including vendor name, invoice number, and date — so your accounting team can always find it without searching email.",
      },
      {
        title: "Contract and agreement archiving",
        description:
          "Signed contracts and legal agreements sent by email are automatically saved to your Contracts Drive folder. GAIA can also create a Drive shortcut linked back to the original email thread for full context.",
      },
      {
        title: "Project asset collection",
        description:
          "Design files, briefs, and project assets sent by clients or vendors over email are automatically routed to the correct project folder in Drive so your team has access without anyone acting as a manual file relay.",
      },
      {
        title: "Email thread to Drive document",
        description:
          "Important email threads — project decisions, client approvals, or policy discussions — can be converted by GAIA into formatted Drive documents for long-term archiving and easy sharing with people who weren't on the original thread.",
      },
      {
        title: "Photo and media attachment organization",
        description:
          "Photos and media files emailed by clients or partners are saved to organized Drive folders automatically, eliminating the need to manually download and re-upload assets that arrive in your inbox.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Google Drive to GAIA",
        description:
          "Authenticate your Google account for both Gmail and Drive access. GAIA uses a single OAuth connection for Google Workspace services, so you only authorize once and specify which Drive folders GAIA should have write access to.",
      },
      {
        step: "Configure your folder routing rules",
        description:
          "Tell GAIA which types of attachments or emails should go to which Drive folders. You can base rules on sender domain, Gmail labels, subject keywords, file type, or AI-detected document category such as invoice, contract, or design file.",
      },
      {
        step: "GAIA automatically saves files as they arrive",
        description:
          "From the moment setup is complete, GAIA monitors incoming emails and saves qualifying attachments to Drive without any manual action. Files are organized, named, and placed exactly where your team expects them.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA organize files into subfolders based on the email sender or date?",
        answer:
          "Yes. You can instruct GAIA to create a folder structure based on sender name, sender domain, year and month, project name, or any combination. For example, invoices can be organized into Drive folders by vendor and then by month automatically.",
      },
      {
        question: "What file types can GAIA save to Drive?",
        answer:
          "GAIA can save any file type that Gmail supports as an attachment, including PDFs, Word documents, Excel spreadsheets, images, ZIP archives, and more. Google Workspace files like Docs and Sheets are handled natively.",
      },
      {
        question:
          "Will GAIA create duplicate files if the same attachment is sent twice?",
        answer:
          "GAIA checks for existing files with the same name and content hash before saving. If a duplicate is detected, it will skip the save or append a version suffix depending on your preference, keeping your Drive folders clean.",
      },
    ],
  },

  "gmail-hubspot": {
    slug: "gmail-hubspot",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Sync Gmail conversations with HubSpot CRM contacts and deals automatically",
    metaTitle:
      "Gmail + HubSpot Automation - Email to CRM, Contacts Synced | GAIA",
    metaDescription:
      "Connect Gmail and HubSpot with GAIA. Log email conversations to CRM contacts, create deals from emails, update contact records automatically, and never lose a sales interaction.",
    keywords: [
      "Gmail HubSpot integration",
      "email to HubSpot CRM",
      "Gmail HubSpot automation",
      "log emails to HubSpot",
      "connect Gmail and HubSpot",
      "HubSpot email sync",
    ],
    intro:
      "Sales and customer success teams rely on HubSpot to manage relationships, but the actual conversations happen in Gmail. When email interactions aren't consistently logged to CRM, your HubSpot data becomes incomplete, deal timelines have gaps, and new team members lack context when they take over an account. Manual CRM logging is tedious enough that it gets skipped, especially under pressure.\n\nGAIA bridges Gmail and HubSpot by keeping them synchronized automatically. When you exchange emails with a HubSpot contact, GAIA logs the conversation to the correct contact record, extracts action items, and updates deal stages based on email signals. New contacts discovered in email can be automatically created in HubSpot with relevant context. Your CRM stays accurate without relying on sales reps to remember to log every interaction.\n\nThis integration is essential for sales teams who do high-volume outreach, account managers who maintain long-term client relationships, and customer success teams who need a complete interaction history for every account.",
    useCases: [
      {
        title: "Automatic email logging to HubSpot contacts",
        description:
          "Every qualifying email you send or receive is automatically logged as an activity on the corresponding HubSpot contact record. The full email content, date, and thread context are captured so your CRM always reflects what has actually been communicated with each contact.",
      },
      {
        title: "Create HubSpot deals from inbound email inquiries",
        description:
          "When a prospect emails with an inquiry or request for information, GAIA creates a new HubSpot deal and associates it with the contact, setting the deal stage, estimated value if mentioned, and linked email thread so your sales team can follow up immediately from HubSpot.",
      },
      {
        title: "Update deal stages based on email signals",
        description:
          "When an email indicates a deal has progressed — a prospect confirms a meeting, sends a purchase order, or requests a contract — GAIA updates the HubSpot deal stage accordingly so your pipeline always reflects current reality without requiring manual updates.",
      },
      {
        title: "New contact creation from email signatures",
        description:
          "When you receive an email from someone not yet in HubSpot, GAIA extracts contact details from the email signature — name, company, phone, title — and creates a new HubSpot contact record enriched with that information.",
      },
      {
        title: "Follow-up task creation from email commitments",
        description:
          "When an email contains a commitment — 'I'll get back to you by Friday' or 'let's schedule a call next week' — GAIA creates a follow-up task in HubSpot assigned to the responsible rep so commitments are tracked and nothing falls through the cracks.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and HubSpot to GAIA",
        description:
          "Authenticate your Gmail account and HubSpot portal in GAIA. GAIA uses HubSpot's OAuth integration and requests only the permissions needed to read and write contacts, deals, and activities.",
      },
      {
        step: "Define your sync rules and preferences",
        description:
          "Specify which email addresses or domains should trigger CRM logging, how contacts should be matched or created, and which email signals indicate deal stage changes. You can also set which team members' inboxes GAIA should monitor.",
      },
      {
        step: "GAIA keeps Gmail and HubSpot synchronized automatically",
        description:
          "GAIA monitors qualifying inboxes and logs interactions to HubSpot continuously. Your CRM data stays current without manual entry, giving your whole team an accurate and complete view of every customer relationship.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA match emails to existing HubSpot contacts automatically?",
        answer:
          "Yes. GAIA matches emails to HubSpot contacts by email address first, and if no match is found, it can search by company domain. You can configure whether unmatched emails create new contacts automatically or are flagged for manual review.",
      },
      {
        question: "Will personal emails also be logged to HubSpot?",
        answer:
          "No. GAIA only logs emails that match your defined rules — typically emails from or to contacts in HubSpot or email addresses from known customer domains. Internal team emails and personal communications are excluded by default.",
      },
      {
        question: "Can GAIA work across multiple team members' Gmail inboxes?",
        answer:
          "Yes. GAIA can be configured for an entire sales or customer success team, logging interactions from each team member's Gmail to the appropriate HubSpot contact records so your CRM captures the full picture of every customer relationship.",
      },
    ],
  },

  "gmail-salesforce": {
    slug: "gmail-salesforce",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Log emails to Salesforce CRM and create leads from your inbox automatically",
    metaTitle:
      "Gmail + Salesforce Automation - Email Logging, Lead Creation | GAIA",
    metaDescription:
      "Connect Gmail and Salesforce with GAIA. Automatically log emails to Salesforce records, create leads from inbound emails, update opportunities, and keep your CRM data accurate.",
    keywords: [
      "Gmail Salesforce integration",
      "email to Salesforce CRM",
      "Gmail Salesforce automation",
      "log emails to Salesforce",
      "create Salesforce lead from email",
      "connect Gmail and Salesforce",
    ],
    intro:
      "Salesforce is the system of record for enterprise sales teams, but keeping it accurate requires logging every customer interaction — a task that falls on sales reps who are already stretched thin. Studies consistently show that CRM data quality suffers because manual logging is time-consuming, inconsistent, and the first thing to be skipped when reps are busy closing deals.\n\nGAIA automates Gmail-to-Salesforce data flow so your CRM is kept accurate without burdening your sales team. Inbound emails from prospects automatically create Salesforce leads with the correct lead source, contact details, and email content captured. Existing customer email threads are logged to the right Account, Contact, and Opportunity records. Deal-progressing email signals trigger Opportunity stage updates. Your Salesforce data becomes a true reflection of sales activity rather than a manual approximation.\n\nThis integration is designed for enterprise sales teams, revenue operations managers who depend on CRM data quality, and organizations where Salesforce is the authoritative system of record for all customer interactions.",
    useCases: [
      {
        title: "Automatic lead creation from inbound inquiry emails",
        description:
          "When a prospect emails your sales team for the first time, GAIA creates a Salesforce Lead record with all available contact information extracted from the email and signature, the lead source set to 'Email', and the original email attached to the record so your sales reps have full context when following up.",
      },
      {
        title: "Email activity logging to Accounts and Opportunities",
        description:
          "Every email exchange with a Salesforce Contact is automatically logged as an Email Activity on the related Account and Opportunity records. Sales managers get a complete interaction timeline without chasing reps to log their calls and emails manually.",
      },
      {
        title: "Opportunity stage advancement from email signals",
        description:
          "When an email from a prospect contains language indicating deal progression — a request for a proposal, a reference check, or a verbal commitment — GAIA advances the associated Salesforce Opportunity to the appropriate stage and creates a follow-up task for the rep.",
      },
      {
        title: "Contact record enrichment from email signatures",
        description:
          "GAIA extracts contact details from email signatures — title, direct phone, LinkedIn profile, and company details — and updates the corresponding Salesforce Contact record so your CRM data stays enriched and current as relationships evolve.",
      },
      {
        title: "Lead conversion email notifications",
        description:
          "When a Salesforce Lead is converted to an Account and Contact after a successful qualification call, GAIA sends an automated welcome email from Gmail to the new contact, keeping communication warm while the Salesforce record is being set up.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Salesforce to GAIA",
        description:
          "Authenticate your Gmail account and Salesforce organization in GAIA. GAIA supports both Salesforce sandbox and production environments and requests only the API permissions needed for reading and writing Leads, Contacts, Accounts, Opportunities, and Activities.",
      },
      {
        step: "Map your email-to-Salesforce rules",
        description:
          "Configure which email senders trigger lead creation, how emails are matched to existing Salesforce records, which Opportunity stage changes map to which email signal keywords, and which team members' inboxes should be monitored.",
      },
      {
        step: "GAIA keeps your Salesforce CRM automatically updated",
        description:
          "GAIA monitors qualifying Gmail inboxes and updates Salesforce records in real time as emails arrive and are sent. Your CRM stays current and your sales team spends more time selling and less time on data entry.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA support Salesforce custom objects, not just standard ones?",
        answer:
          "Yes. GAIA can read and write to custom Salesforce objects in addition to standard Leads, Contacts, Accounts, and Opportunities. You can map email content to custom fields by describing the mapping in GAIA's configuration.",
      },
      {
        question:
          "How does GAIA handle emails that match multiple Salesforce records?",
        answer:
          "When an email matches multiple Salesforce records — for example, a contact associated with multiple opportunities — GAIA will log the activity to all relevant records or prompt for disambiguation based on your configuration preferences.",
      },
      {
        question: "Is this compatible with Salesforce Lightning and Classic?",
        answer:
          "GAIA integrates with Salesforce via the REST API, which is compatible with both Lightning and Classic. The integration works regardless of which Salesforce UI your team uses.",
      },
    ],
  },

  "gmail-airtable": {
    slug: "gmail-airtable",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline:
      "Save email data to Airtable databases and trigger workflows from your inbox",
    metaTitle:
      "Gmail + Airtable Automation - Email Data to Airtable Records | GAIA",
    metaDescription:
      "Connect Gmail and Airtable with GAIA. Automatically create Airtable records from emails, extract structured data from your inbox, and keep databases updated without manual data entry.",
    keywords: [
      "Gmail Airtable integration",
      "email to Airtable automation",
      "Gmail Airtable workflow",
      "save email data to Airtable",
      "connect Gmail and Airtable",
      "Airtable email sync",
    ],
    intro:
      "Airtable's power lies in its ability to structure and organize information flexibly — but feeding that database with data from email still requires someone to read each email and manually enter the relevant fields. For teams that receive high volumes of structured information by email — orders, applications, registrations, inquiries, or reports — manual data entry is a bottleneck that slows down operations and introduces errors.\n\nGAIA connects Gmail and Airtable so that email content flows automatically into the right database fields. When an order confirmation arrives, GAIA creates an Airtable record with the order number, customer name, items, and value extracted from the email. When a job application lands in your inbox, GAIA creates an applicant record with name, contact details, and relevant experience parsed from the email. Your Airtable databases stay current without anyone acting as a manual data relay.\n\nThis is particularly powerful for operations teams running Airtable-based workflows, HR teams managing applicant tracking, event teams handling registrations, and any team that receives structured data via email and needs it organized in a database.",
    useCases: [
      {
        title: "Order and purchase confirmation data capture",
        description:
          "When order confirmation or purchase receipt emails arrive, GAIA extracts the structured data — order number, items, quantities, amounts, vendor name, and delivery date — and creates a new Airtable record in your orders or purchases database with all fields populated automatically.",
      },
      {
        title: "Job application intake",
        description:
          "When job applications arrive by email, GAIA parses the applicant's details, extracts the position they are applying for, and creates a new record in your Airtable applicant tracking base, assigning the appropriate status and notifying the hiring manager.",
      },
      {
        title: "Event registration management",
        description:
          "Registration confirmation emails from events, webinars, or workshops are parsed by GAIA and added as records in your Airtable events database with attendee name, company, role, and registration date captured automatically.",
      },
      {
        title: "Vendor invoice tracking",
        description:
          "Invoice emails from vendors are processed by GAIA, which extracts invoice number, vendor name, amount due, and payment due date, then creates a record in your Airtable accounts payable database and alerts your finance team if the amount exceeds a defined threshold.",
      },
      {
        title: "Customer feedback collection",
        description:
          "Feedback and survey responses received by email are parsed by GAIA and stored as structured records in your Airtable feedback database, categorized by sentiment and topic so your product team can analyze patterns without reading every email manually.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Airtable to GAIA",
        description:
          "Authenticate your Gmail account and Airtable workspace in GAIA. Specify which Airtable bases and tables GAIA should have write access to, and GAIA will map your email fields to Airtable columns.",
      },
      {
        step: "Define your email-to-record mapping",
        description:
          "Tell GAIA which types of emails should create records in which Airtable tables, and how email content maps to table fields. GAIA uses AI to extract structured data from unstructured email text, so you don't need perfectly formatted emails.",
      },
      {
        step: "GAIA populates your Airtable databases automatically",
        description:
          "GAIA processes qualifying emails as they arrive and creates or updates Airtable records accordingly. Your databases stay current without manual data entry, and your team can focus on acting on the data rather than entering it.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA update existing Airtable records as well as create new ones?",
        answer:
          "Yes. GAIA can match incoming emails to existing Airtable records based on a key field like email address or order number, and update the record rather than creating a duplicate. For example, a follow-up email from a job applicant can update their existing applicant record.",
      },
      {
        question:
          "What if the email doesn't contain all the fields my Airtable table requires?",
        answer:
          "GAIA will populate the fields it can extract from the email and leave required fields blank or set them to a default value you specify. You can configure GAIA to notify you when a record is created with missing required fields so you can complete it manually.",
      },
      {
        question:
          "Can GAIA trigger Airtable automations after creating a record?",
        answer:
          "Yes. Once GAIA creates a record in Airtable, any Airtable automations triggered by record creation will fire as normal. You can also configure GAIA to send a confirmation email or Slack notification after creating the Airtable record.",
      },
    ],
  },

  "gmail-stripe": {
    slug: "gmail-stripe",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline:
      "Enrich payment emails with Stripe data and automate revenue notifications",
    metaTitle:
      "Gmail + Stripe Automation - Payment Emails, Revenue Alerts | GAIA",
    metaDescription:
      "Connect Gmail and Stripe with GAIA. Enrich payment notification emails with Stripe customer data, automate revenue summaries, and act on billing events without manual lookups.",
    keywords: [
      "Gmail Stripe integration",
      "payment email Stripe automation",
      "Gmail Stripe workflow",
      "Stripe payment notification email",
      "connect Gmail and Stripe",
      "Stripe revenue alert Gmail",
    ],
    intro:
      "Stripe sends email notifications for payments, failed charges, disputes, and subscription events, but those emails contain only minimal context — a transaction ID and an amount. Getting the full picture requires logging into Stripe, finding the customer, and cross-referencing with your own records. For finance teams and operations managers processing dozens of payment events daily, this back-and-forth is a significant time drain.\n\nGAIA connects Gmail and Stripe so that payment-related emails are automatically enriched with detailed Stripe customer and transaction data. When a payment failure email arrives, GAIA fetches the customer's full payment history, subscription status, and contact details and compiles a complete summary so your team can respond intelligently without opening Stripe. Dispute and chargeback emails trigger automated evidence gathering. Revenue milestone emails can be generated automatically based on Stripe data.\n\nThis integration is most valuable for SaaS companies, e-commerce teams, and subscription businesses where payment events require coordinated action from finance, customer success, and operations teams.",
    useCases: [
      {
        title: "Payment failure enrichment and follow-up",
        description:
          "When a failed payment notification arrives from Stripe, GAIA fetches the customer's full details from Stripe — their plan, payment history, and contact information — and composes a personalized follow-up email ready for review, so your team can respond in minutes rather than manually looking up each case.",
      },
      {
        title: "Dispute and chargeback response automation",
        description:
          "When a Stripe dispute notification email arrives, GAIA automatically pulls the relevant transaction details, order confirmation, and communication history from Gmail and assembles a dispute evidence package to streamline your response before the deadline.",
      },
      {
        title: "Daily and weekly revenue summaries",
        description:
          "GAIA pulls revenue data from Stripe and delivers a structured email summary to your finance team every morning or week — including total revenue, new subscribers, churned accounts, and outstanding invoices — eliminating the need for manual Stripe dashboard exports.",
      },
      {
        title: "Subscription event notifications to team email",
        description:
          "When a customer upgrades, downgrades, or cancels their subscription in Stripe, GAIA sends an enriched notification email to the relevant internal team with the customer's account history and context so customer success can reach out proactively.",
      },
      {
        title: "High-value payment alerts",
        description:
          "When a Stripe payment above a defined threshold is processed, GAIA sends an immediate alert email to your sales or finance leadership with the customer details, plan, and payment history so high-value transactions receive the attention they deserve.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Stripe to GAIA",
        description:
          "Authenticate your Gmail account and connect your Stripe account via API key in GAIA. GAIA uses read-only Stripe API access by default so your financial data remains secure.",
      },
      {
        step: "Configure your payment event rules",
        description:
          "Define which Stripe events should trigger email actions, what data to pull from Stripe for enrichment, who should receive notifications, and what thresholds apply for high-value or high-priority alerts.",
      },
      {
        step: "GAIA enriches payment emails and automates revenue workflows",
        description:
          "GAIA monitors both incoming Stripe notification emails and Stripe webhook events, enriches them with full customer context, and dispatches the right actions — follow-up emails, internal alerts, or summary reports — automatically.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA need write access to my Stripe account?",
        answer:
          "For most workflows, GAIA only needs read access to retrieve customer and transaction data. If you want GAIA to take actions like issuing refunds or updating subscriptions, you can grant write permissions for those specific capabilities, but it is not required for email enrichment and notifications.",
      },
      {
        question: "Can GAIA send automated dunning emails for failed payments?",
        answer:
          "Yes. GAIA can compose and send personalized dunning emails when payment failures occur, including the customer's name, the failed amount, and a link to update their payment method. You can set a sequence of escalating follow-ups on a schedule you define.",
      },
      {
        question:
          "Does this work with Stripe Connect or only standard Stripe accounts?",
        answer:
          "GAIA works with standard Stripe accounts. Stripe Connect support for marketplace and platform integrations is on the roadmap. Contact the GAIA team if you have a specific Connect use case.",
      },
    ],
  },

  "gmail-zoom": {
    slug: "gmail-zoom",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline:
      "Create Zoom meetings from email invites and send join links automatically",
    metaTitle: "Gmail + Zoom Automation - Schedule Meetings from Email | GAIA",
    metaDescription:
      "Connect Gmail and Zoom with GAIA. Automatically create Zoom meetings when scheduling emails arrive, send join links to participants, and keep your calendar and inbox in sync.",
    keywords: [
      "Gmail Zoom integration",
      "email to Zoom meeting",
      "Gmail Zoom automation",
      "schedule Zoom from email",
      "connect Gmail and Zoom",
      "Zoom meeting email invite",
    ],
    intro:
      "Scheduling a meeting over email is a multi-step process: negotiate a time by email, open Zoom to create a meeting, copy the link, return to Gmail, compose a reply with the link, and hope you didn't forget to add it to your calendar. When this process repeats dozens of times a week, it consumes significant time and is prone to errors — forgotten links, wrong time zones, and meetings that never make it onto the calendar.\n\nGAIA automates the Gmail-to-Zoom scheduling loop entirely. When an email arrives with a meeting request or a confirmed time, GAIA creates the Zoom meeting, adds it to your Google Calendar, and replies to the thread with the join link — all without you leaving your inbox. For teams using Zoom as their primary video conferencing tool, this eliminates the single most tedious step in the workday.\n\nThis integration is particularly valuable for executives, sales teams, consultants, and customer success managers who spend a significant portion of their day negotiating and setting up meetings over email.",
    useCases: [
      {
        title: "Auto-create Zoom meetings from confirmed email times",
        description:
          "When an email exchange concludes with a confirmed meeting time, GAIA detects the agreed time, creates a Zoom meeting for that slot, adds it to your calendar, and replies to the email thread with the Zoom join link and calendar invite so both parties are set up instantly.",
      },
      {
        title: "One-click meeting creation from email",
        description:
          "Forward any email to GAIA with a note like 'set up a Zoom for Thursday at 2 PM' and GAIA creates the meeting, sends the invite to all email participants, and confirms the details back to you — turning a multi-step process into a single action.",
      },
      {
        title: "Recurring meeting setup from email chains",
        description:
          "When an email discussion establishes a recurring check-in or weekly sync, GAIA creates the recurring Zoom meeting series, sends invites to all participants, and adds the series to your calendar so you never have to set up a recurring meeting manually again.",
      },
      {
        title: "Zoom link recovery and resending",
        description:
          "When a meeting participant emails asking for the Zoom link, GAIA looks up the scheduled meeting, retrieves the join URL, and replies automatically so you don't have to dig through your calendar and compose a reply yourself.",
      },
      {
        title: "Post-meeting follow-up email automation",
        description:
          "After a Zoom meeting ends, GAIA sends an automated follow-up email to all participants with a summary of discussion points and agreed next steps extracted from the meeting, keeping the post-meeting communication loop closed without manual effort.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Zoom to GAIA",
        description:
          "Authenticate your Gmail account and Zoom account in GAIA. GAIA uses Zoom's OAuth integration to create and manage meetings on your behalf, and accesses your Gmail to detect scheduling signals in email threads.",
      },
      {
        step: "Set your scheduling preferences",
        description:
          "Tell GAIA your default Zoom meeting settings — duration, waiting room preference, recording options, and calendar integration. You can also specify which types of email threads should trigger automatic meeting creation versus requiring your confirmation.",
      },
      {
        step: "GAIA handles meeting creation and communication automatically",
        description:
          "GAIA monitors your Gmail for meeting-related signals and creates Zoom meetings automatically when the conditions are met. Join links are sent to participants and meetings appear on your calendar without any manual steps.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA handle time zone differences when creating Zoom meetings from email?",
        answer:
          "Yes. GAIA detects time zone references in email text and converts them to the correct UTC time when creating the Zoom meeting and calendar event. If the time zone is ambiguous, GAIA will ask for clarification before creating the meeting.",
      },
      {
        question:
          "Will GAIA create Zoom meetings for every email that mentions a time, or only confirmed meetings?",
        answer:
          "GAIA uses context to distinguish between 'are you free Thursday at 2?' (a proposal) and 'confirmed: Thursday at 2 PM' (a commitment). You can also configure GAIA to always ask before creating a meeting if you prefer full control.",
      },
      {
        question:
          "Does this work with Google Calendar for adding meeting events?",
        answer:
          "Yes. When GAIA creates a Zoom meeting from Gmail, it simultaneously creates the Google Calendar event with the Zoom link embedded so the meeting appears on your calendar with all the details in one place.",
      },
    ],
  },

  "gmail-teams": {
    slug: "gmail-teams",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Microsoft Teams",
    toolBSlug: "microsoft-teams",
    tagline:
      "Route important Gmail messages to Microsoft Teams channels automatically",
    metaTitle:
      "Gmail + Microsoft Teams Automation - Email to Teams Notifications | GAIA",
    metaDescription:
      "Connect Gmail and Microsoft Teams with GAIA. Forward important emails to Teams channels, get inbox alerts in Teams, and keep your Microsoft 365 team updated from Gmail automatically.",
    keywords: [
      "Gmail Microsoft Teams integration",
      "email to Teams notification",
      "Gmail Teams automation",
      "forward email to Teams",
      "connect Gmail and Microsoft Teams",
      "Teams email alert workflow",
    ],
    intro:
      "Organizations that use Google Workspace for email but Microsoft 365 for team collaboration face a constant bridging problem. Important emails arrive in Gmail while the team is active in Microsoft Teams. Colleagues who need to know about a client email, system alert, or vendor communication have to be individually forwarded threads, creating email overload and losing the collaborative context that Teams provides.\n\nGAIA bridges Gmail and Microsoft Teams so that critical email communications surface automatically in the right Teams channels. Client emails can post to a #clients channel. System alerts can go to #monitoring. Financial notifications can appear in a #finance channel. Your Teams workspace becomes informed by Gmail events in real time, and your team can discuss and respond within Teams rather than jumping between platforms.\n\nThis integration is essential for organizations in hybrid technology environments — using Google Workspace for email but Microsoft 365 for Office apps and team collaboration — and for teams where different departments have standardized on different platforms.",
    useCases: [
      {
        title: "Client email alerts to Teams channels",
        description:
          "When a priority client emails your Gmail, GAIA posts a formatted summary to the designated Microsoft Teams channel so the whole account team is immediately aware and can coordinate a response in Teams without waiting for someone to forward the email.",
      },
      {
        title: "System and infrastructure alert routing",
        description:
          "Monitoring services that send email alerts can have those alerts forwarded by GAIA to your Teams #ops or #monitoring channel so your engineering team sees them immediately in the platform they are already working in.",
      },
      {
        title: "Daily email digest in Teams",
        description:
          "GAIA posts a morning summary of your key unread Gmail messages directly to your personal Teams chat so you can triage your inbox without opening Gmail, seeing the most important emails summarized in the collaboration tool you start your day in.",
      },
      {
        title: "Cross-platform reply drafting",
        description:
          "When your team discusses a client email in Teams and reaches a decision, you can ask GAIA to draft the Gmail reply based on the Teams conversation thread, composing the response with the agreed content and queuing it for your review in Gmail.",
      },
      {
        title: "New lead and inquiry notifications",
        description:
          "Contact form submissions and sales inquiry emails that land in Gmail are routed by GAIA to your Teams sales channel with the prospect's details and inquiry summary so your sales team can immediately discuss and assign follow-up within Teams.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Microsoft Teams to GAIA",
        description:
          "Authenticate your Gmail account and your Microsoft 365 organization in GAIA. GAIA uses Microsoft Graph API and Teams webhooks to post to specific channels, and Google OAuth to access Gmail.",
      },
      {
        step: "Configure your routing and notification rules",
        description:
          "Specify which Gmail labels, senders, or email categories should trigger Teams notifications, which Teams channels each type should go to, and what format the Teams messages should take — full email, summary, or custom template.",
      },
      {
        step: "GAIA bridges Gmail and Teams automatically",
        description:
          "GAIA monitors your Gmail continuously and posts to Teams channels as qualifying emails arrive. Your Teams environment stays informed by Gmail activity without anyone manually relaying information between the two platforms.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA post to Teams private channels as well as public ones?",
        answer:
          "Yes. GAIA can post to any Teams channel — public, private, or shared — where it has been granted permission. During setup, you specify which channels GAIA should have access to, and it will only post where authorized.",
      },
      {
        question:
          "Can GAIA include email attachments in the Teams notification?",
        answer:
          "GAIA can reference attachments in the Teams message and provide a link back to the original Gmail thread. Uploading binary attachments directly to Teams is supported for common file types. For large files, GAIA recommends linking to a shared Google Drive location instead.",
      },
      {
        question:
          "Does GAIA support conditional routing — for example, only posting emails above a certain urgency level?",
        answer:
          "Yes. GAIA can assess email urgency using AI classification and only route emails that meet your defined threshold to Teams. This prevents your Teams channels from being flooded with low-priority notifications.",
      },
    ],
  },

  "slack-trello": {
    slug: "slack-trello",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Trello",
    toolBSlug: "trello",
    tagline:
      "Create Trello cards from Slack messages and get board updates in Slack",
    metaTitle:
      "Slack + Trello Automation - Cards from Messages, Board Alerts | GAIA",
    metaDescription:
      "Connect Slack and Trello with GAIA. Create Trello cards from Slack messages, receive card updates in Slack channels, and manage your task board without leaving your team chat.",
    keywords: [
      "Slack Trello integration",
      "create Trello card from Slack",
      "Slack Trello automation",
      "Trello updates in Slack",
      "connect Slack and Trello",
      "Slack Trello workflow",
    ],
    intro:
      "The best ideas and most urgent action items in a team often emerge in Slack conversations, but those insights evaporate if they're not captured in Trello where work actually gets tracked. Teams develop workarounds — screenshotting Slack messages, copying them into Trello cards manually — but these habits are inconsistent and create a disconnect between where discussions happen and where work gets done.\n\nGAIA bridges Slack and Trello so that capturing work from conversation is effortless. A single emoji reaction or a quick command in Slack can turn a message into a properly structured Trello card on the right board. When Trello cards are updated — moved to a new list, given a due date, or marked complete — Slack receives a notification in the appropriate channel so the team stays informed without checking Trello manually.\n\nThis integration is ideal for product teams who ideate in Slack and execute in Trello, marketing teams managing campaign tasks, and any team that needs their task board to reflect work captured in real-time conversations.",
    useCases: [
      {
        title: "Create Trello cards with emoji reactions",
        description:
          "React to any Slack message with a designated emoji — like a clipboard or checkmark — and GAIA automatically creates a Trello card in the configured board and list with the message content as the card description, tagged with the channel and author so context is preserved.",
      },
      {
        title: "Slash command card creation with details",
        description:
          "Use a Slack slash command like '/gaia add to trello [board] [list]' to create a detailed Trello card from a Slack message, complete with due date, assignee, and labels specified inline, without leaving Slack.",
      },
      {
        title: "Trello card status updates in Slack",
        description:
          "When a Trello card is moved to a new list — such as 'In Review' or 'Done' — GAIA posts a brief update to the relevant Slack channel so the team knows work has progressed without anyone having to check the Trello board or send a manual update.",
      },
      {
        title: "Daily board summary in Slack",
        description:
          "GAIA posts a morning digest to a designated Slack channel summarizing the state of your Trello boards: cards due today, overdue items, and what was completed yesterday — giving the team a shared overview to start each day.",
      },
      {
        title: "Overdue card alerts to Slack",
        description:
          "When a Trello card's due date passes without it being moved to 'Done', GAIA sends an alert to the assigned team member's Slack DM and optionally to the team channel so overdue tasks are never silently missed.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Trello to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and authenticate your Trello account. GAIA will ask which Trello boards it should have access to and which Slack channels should receive Trello notifications.",
      },
      {
        step: "Configure card creation triggers and notification rules",
        description:
          "Define which emoji reactions or slash commands should create cards, which Slack channels map to which Trello boards and lists, and which Trello events should trigger Slack notifications. You can set up different rules for different channels and boards.",
      },
      {
        step: "GAIA keeps Slack and Trello synchronized automatically",
        description:
          "GAIA monitors Slack for triggers and Trello for events, creating cards and posting notifications as defined. Your team captures work from conversation effortlessly and always knows the state of the Trello board from Slack.",
      },
    ],
    faqs: [
      {
        question:
          "Can multiple team members create Trello cards from Slack, or only admins?",
        answer:
          "Any team member in the configured Slack workspace can create Trello cards using the defined triggers. GAIA respects Trello board permissions, so cards will only be created on boards the triggering user has access to.",
      },
      {
        question:
          "Can I choose which Slack channel gets notified for specific Trello boards?",
        answer:
          "Yes. You can map each Trello board to a specific Slack channel for notifications. For example, your Marketing board updates can go to #marketing while your Engineering board goes to #engineering.",
      },
      {
        question: "Does GAIA attach the Slack message link to the Trello card?",
        answer:
          "Yes. GAIA embeds a link back to the original Slack message in the Trello card description so anyone reading the card can navigate directly to the conversation where the task originated for full context.",
      },
    ],
  },

  "slack-drive": {
    slug: "slack-drive",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Google Drive",
    toolBSlug: "google-drive",
    tagline:
      "Save Slack files to Google Drive and access Drive documents from Slack",
    metaTitle:
      "Slack + Google Drive Automation - File Sync, Drive Access in Slack | GAIA",
    metaDescription:
      "Connect Slack and Google Drive with GAIA. Automatically save Slack file uploads to Drive folders, share Drive documents in Slack, and keep your team's files organized and accessible.",
    keywords: [
      "Slack Google Drive integration",
      "save Slack files to Drive",
      "Slack Drive automation",
      "Google Drive Slack workflow",
      "connect Slack and Google Drive",
      "Slack file management Drive",
    ],
    intro:
      "Files shared in Slack are convenient in the moment but difficult to find later. Slack's search can surface messages, but files buried in channels expire on free plans and are scattered across hundreds of conversations without any organizational structure. Meanwhile, Google Drive sits mostly empty of the assets that were shared in Slack because moving files from Slack to Drive requires manual downloading and uploading.\n\nGAIA connects Slack and Google Drive so files flow between them automatically. When a file is uploaded to a Slack channel, GAIA saves it to the correct Drive folder, named consistently and organized by channel, project, or date. When a teammate asks for a Drive file in Slack, GAIA can retrieve and share the link instantly. Your team gets the spontaneity of Slack file sharing with the organization and permanence of Google Drive.\n\nThis is especially useful for design and creative teams sharing assets in Slack, project teams distributing documents across channels, and operations teams who need a permanent record of files discussed in Slack.",
    useCases: [
      {
        title: "Auto-save Slack channel uploads to Drive folders",
        description:
          "Every file uploaded to designated Slack channels is automatically saved by GAIA to the corresponding Google Drive folder. Design assets shared in #design go to the Design Assets Drive folder, project documents in #project-x go to that project's Drive folder, and so on — without anyone having to manually move files.",
      },
      {
        title: "Retrieve Drive files from Slack with natural language",
        description:
          "Ask GAIA in Slack 'share the Q2 marketing brief from Drive' and GAIA searches your Drive, finds the document, and posts the shareable link directly in the channel — eliminating the need to switch to Drive, search, and copy the link back to Slack.",
      },
      {
        title: "Drive file update notifications in Slack",
        description:
          "When a key Google Drive document is updated — a shared brief, a contract, or a live dashboard — GAIA posts a notification in the relevant Slack channel with a direct link to the updated file so the team is always working from the latest version.",
      },
      {
        title: "Slack message to Drive document",
        description:
          "When a Slack thread contains a completed discussion, decision, or meeting notes, GAIA can convert it into a properly formatted Google Doc saved to the team Drive, making it searchable and shareable beyond the Slack channel.",
      },
      {
        title: "Drive folder briefs shared to Slack",
        description:
          "At the start of a project, GAIA can share a structured summary of a Drive project folder to the relevant Slack channel — listing key documents, recent updates, and important files — so the whole team has a quick reference without navigating Drive.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Google Drive to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and connect your Google account for Drive access. Specify which Slack channels should have file auto-save enabled and which Drive folders they should map to.",
      },
      {
        step: "Set your file routing and notification preferences",
        description:
          "Define which Slack channels map to which Drive folders, what naming conventions to apply to saved files, and which Drive events should trigger Slack notifications. You can set different rules for different file types.",
      },
      {
        step: "GAIA keeps your files synchronized between Slack and Drive",
        description:
          "Files uploaded to Slack are saved to Drive automatically and Drive updates are surfaced in Slack. Your team gets persistent, organized file access without any manual file management overhead.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA save all files from a Slack channel or only specific types?",
        answer:
          "You can configure GAIA to save all files from a channel or only specific file types such as PDFs, images, or documents. You can also exclude files below a certain size or from specific senders if needed.",
      },
      {
        question:
          "Will GAIA overwrite a Drive file if the same file is uploaded again in Slack?",
        answer:
          "GAIA checks for an existing file with the same name in the target Drive folder. If found, it can either create a new version of the Drive file or save the new upload with a version suffix, depending on your configuration.",
      },
      {
        question:
          "Can GAIA handle Google Drive shared drives, not just personal My Drive?",
        answer:
          "Yes. GAIA supports both personal My Drive and Google Shared Drives. You can map Slack channels to folders within a Shared Drive so the entire team has ownership of the automatically saved files.",
      },
    ],
  },

  "slack-discord": {
    slug: "slack-discord",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Discord",
    toolBSlug: "discord",
    tagline:
      "Bridge Slack and Discord to cross-post announcements across both communities",
    metaTitle:
      "Slack + Discord Bridge - Cross-Post Messages, Sync Communities | GAIA",
    metaDescription:
      "Connect Slack and Discord with GAIA. Cross-post announcements between Slack workspaces and Discord servers, bridge team and community communications, and keep both platforms in sync.",
    keywords: [
      "Slack Discord integration",
      "Slack Discord bridge",
      "cross-post Slack to Discord",
      "Slack Discord automation",
      "connect Slack and Discord",
      "Slack Discord sync",
    ],
    intro:
      "Many organizations operate on both Slack for internal team communication and Discord for their developer community, customer community, or public presence. Keeping both platforms informed requires manually copying and posting the same announcements, updates, and alerts twice — a tedious process that often leads to one platform receiving information later or in a less polished format than the other.\n\nGAIA bridges Slack and Discord so that information flows between them according to your rules. Product announcements posted in a Slack channel can be automatically cross-posted to a Discord announcement channel. Community questions escalated in Discord can appear in the appropriate Slack support channel. Status updates from your engineering team in Slack can be relayed to your public Discord status channel in real time. Both communities stay informed without doubling your communication overhead.\n\nThis is particularly valuable for developer tools companies, open-source projects, gaming studios, and creator businesses that maintain an internal Slack team while building an engaged Discord community.",
    useCases: [
      {
        title: "Cross-post product announcements from Slack to Discord",
        description:
          "When your team posts a product announcement or release update in a designated Slack channel, GAIA automatically formats and cross-posts it to your Discord announcements channel so your community learns about new features at the same time as your internal team, without anyone having to manually copy the message.",
      },
      {
        title: "Escalate Discord community questions to Slack support",
        description:
          "When a Discord member asks a question that requires internal team input — a billing issue, a complex technical question, or a partnership inquiry — GAIA routes the question to the appropriate Slack channel so the right internal team member can respond, and posts the answer back to Discord when resolved.",
      },
      {
        title: "Engineering status updates to Discord",
        description:
          "When your engineering team posts a service status update in Slack, GAIA relays a community-appropriate version to your Discord status channel so your users are kept informed about incidents, maintenance windows, and resolutions without requiring your team to compose separate communications.",
      },
      {
        title: "Event announcements synchronized across platforms",
        description:
          "When you schedule a community event, webinar, or live session and post the details in Slack, GAIA cross-posts the event details to Discord with proper formatting, ensuring your Discord community can register and participate just as easily as those on Slack.",
      },
      {
        title: "Unified alert monitoring across both platforms",
        description:
          "Critical system alerts posted to a Slack #ops channel are mirrored to a private Discord channel for on-call team members who may be monitoring Discord. This ensures your on-call rotation is covered regardless of which platform team members are active in.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Discord to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and grant GAIA bot access to your Discord server. Specify which Slack channels and Discord channels should participate in the bridge.",
      },
      {
        step: "Define your cross-posting rules",
        description:
          "Configure which Slack channels post to which Discord channels, whether messages should be posted verbatim or reformatted for the destination audience, and any filters for message type, sender, or content.",
      },
      {
        step: "GAIA bridges your Slack and Discord communities automatically",
        description:
          "GAIA monitors both platforms and routes messages according to your rules. Announcements, alerts, and updates flow between Slack and Discord seamlessly, keeping both communities informed without duplicated manual work.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA avoid posting bot messages from Discord back to Slack, creating echo loops?",
        answer:
          "Yes. GAIA tracks which messages it has originated and will not re-post messages that came from its own cross-posting actions. You can also configure it to ignore messages from other bot users to prevent cross-platform echo loops.",
      },
      {
        question:
          "Can GAIA reformat messages for the different tone of each platform?",
        answer:
          "Yes. GAIA can apply different formatting rules for Slack and Discord. For example, a technical internal Slack message can be rewritten in a more community-friendly tone before being posted to Discord, or markdown formatting can be adjusted for each platform's rendering engine.",
      },
      {
        question:
          "Does GAIA support bridging specific Slack DMs to Discord threads?",
        answer:
          "GAIA focuses on channel-to-channel bridging. Direct message bridging is not supported by default for privacy reasons, but escalation workflows — where a Discord user's question is routed to a Slack channel — are fully supported.",
      },
    ],
  },

  "slack-figma": {
    slug: "slack-figma",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Get Figma design updates and comment alerts delivered directly in Slack",
    metaTitle:
      "Slack + Figma Automation - Design Reviews and Comment Alerts | GAIA",
    metaDescription:
      "Connect Slack and Figma with GAIA. Get notified in Slack when Figma designs are updated or commented on, manage design reviews from Slack, and keep designers and stakeholders aligned.",
    keywords: [
      "Slack Figma integration",
      "Figma comment notification Slack",
      "Slack Figma automation",
      "design review Slack Figma",
      "connect Slack and Figma",
      "Figma update alert Slack",
    ],
    intro:
      "Design feedback lives in Figma comments, but the designers and stakeholders who need to act on it are often in Slack. Checking Figma for new comments is a context switch that breaks focus, and email notifications from Figma are easy to miss in a full inbox. The result is delayed design reviews, stale comments that nobody has addressed, and stakeholders who feel out of the loop on design progress.\n\nGAIA connects Slack and Figma so that design activity surfaces where your team is already paying attention. New comments on a Figma file post to the relevant Slack channel so reviewers are notified immediately. When a designer publishes a new version, a Slack notification goes out with a thumbnail preview and direct link to the updated frame. Design approval requests can be managed directly from Slack without opening Figma.\n\nThis integration is built for product design teams, product managers reviewing designs, and development teams who need to be notified when designs are ready for handoff — all without adding Figma notification overhead to their email inboxes.",
    useCases: [
      {
        title: "Figma comment alerts to Slack",
        description:
          "When a stakeholder or reviewer leaves a comment on a Figma file, GAIA posts a notification to the designer's Slack DM and the relevant project channel, including the comment text, the frame it was left on, and a direct link to the comment so the designer can respond without hunting through Figma.",
      },
      {
        title: "Design version publish notifications",
        description:
          "When a designer publishes a new version of a Figma file, GAIA sends a structured Slack notification to the project channel with the version description, a preview image, and a link to the updated file so developers and product managers know when designs have changed and can review the updates immediately.",
      },
      {
        title: "Design review request workflow in Slack",
        description:
          "When a designer is ready for review, they can post a design review request directly from Slack with the Figma link and review instructions. GAIA notifies the designated reviewers, tracks who has reviewed and commented, and posts a summary of feedback back to the channel.",
      },
      {
        title: "Dev handoff notifications",
        description:
          "When a Figma file is moved to a 'Ready for Development' status or a specific frame is marked for handoff, GAIA notifies the assigned developers in Slack with the relevant Figma links, component specs, and any designer notes so implementation can begin immediately.",
      },
      {
        title: "Unresolved comment reminders",
        description:
          "GAIA monitors Figma files for unresolved comments older than a defined threshold and sends reminders to the relevant designer or reviewer in Slack so design feedback never gets forgotten or left unaddressed before a deadline.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Figma to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and connect your Figma account. Specify which Figma files or projects GAIA should monitor and which Slack channels should receive notifications.",
      },
      {
        step: "Configure your notification preferences",
        description:
          "Choose which Figma events trigger Slack notifications — comments, version publishes, status changes, or handoff markers — and map them to the appropriate Slack channels or individual DMs. You can set different rules per project or file.",
      },
      {
        step: "GAIA delivers Figma activity to Slack automatically",
        description:
          "GAIA monitors your Figma files for the configured events and posts structured notifications to Slack as they occur. Your team stays informed about design progress without checking Figma manually.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA notify only specific people in Slack when they are mentioned in a Figma comment?",
        answer:
          "Yes. When a Figma comment tags a specific person using @mention, GAIA sends a direct Slack message to that person in addition to the channel notification, so they are personally alerted even if they missed the channel post.",
      },
      {
        question: "Does GAIA work with all Figma plan types?",
        answer:
          "GAIA requires Figma's webhook or API access, which is available on Figma Professional plans and above. Figma Starter plans have limited API access that may restrict some notification features.",
      },
      {
        question:
          "Can GAIA include a preview image of the Figma frame in the Slack notification?",
        answer:
          "Yes. For version publish and design review notifications, GAIA can include a rendered thumbnail of the relevant Figma frame directly in the Slack message so reviewers can preview the design at a glance before clicking through to Figma.",
      },
    ],
  },

  "slack-stripe": {
    slug: "slack-stripe",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Stripe",
    toolBSlug: "stripe",
    tagline:
      "Get real-time Stripe payment alerts and revenue summaries in Slack",
    metaTitle:
      "Slack + Stripe Automation - Payment Alerts and Revenue in Slack | GAIA",
    metaDescription:
      "Connect Slack and Stripe with GAIA. Receive real-time payment notifications in Slack, get revenue milestone alerts, monitor failed charges, and keep your team informed of financial events.",
    keywords: [
      "Slack Stripe integration",
      "Stripe payment notification Slack",
      "Slack Stripe automation",
      "revenue alert Slack",
      "connect Slack and Stripe",
      "Stripe Slack webhook",
    ],
    intro:
      "Stripe processes your revenue in real time, but that data lives in the Stripe dashboard where most of your team never goes. Sales teams want to celebrate new customers. Finance wants to know about failed charges immediately. Leadership wants revenue milestones surfaced as they happen. Currently, all of this requires either manually checking Stripe or waiting for a weekly report that is already outdated.\n\nGAIA connects Stripe and Slack so that payment events are surfaced in the channels where your team is already paying attention. New subscriptions post to #sales for a real-time win celebration. Failed payments alert your customer success team in #support so they can proactively reach out. Revenue milestones trigger automated announcements. Your team gets a live pulse on the business without anyone having to maintain dashboards or relay information manually.\n\nThis integration is essential for SaaS companies, subscription businesses, and e-commerce teams where revenue events require coordinated responses from sales, finance, customer success, and leadership.",
    useCases: [
      {
        title: "New customer payment alerts in Slack",
        description:
          "When a new customer completes their first Stripe payment or activates a subscription, GAIA posts a celebration notification to your #sales or #wins Slack channel with the customer name, plan, and MRR impact so the whole team can share in the win and customer success can begin onboarding immediately.",
      },
      {
        title: "Failed payment alerts to customer success",
        description:
          "When a Stripe charge fails, GAIA immediately posts an alert to your #support or #customer-success Slack channel with the customer's name, plan, failed amount, and failure reason so your team can reach out proactively before the customer even realizes there is a problem.",
      },
      {
        title: "Revenue milestone announcements",
        description:
          "Configure GAIA to post to your #general or #wins channel when Stripe MRR crosses key milestones — $10K, $50K, $100K — so the whole company gets to celebrate growth moments in real time rather than waiting for a quarterly review.",
      },
      {
        title: "Daily and weekly revenue digests",
        description:
          "GAIA posts a structured daily revenue summary to your #finance channel every morning: new MRR, churned MRR, net new revenue, total active subscriptions, and any anomalies detected — giving your finance and leadership teams a daily financial pulse without opening Stripe.",
      },
      {
        title: "Chargeback and dispute alerts",
        description:
          "When a Stripe dispute or chargeback is opened, GAIA sends an immediate alert to your #finance or #ops Slack channel with the transaction details and dispute deadline so your team can begin assembling evidence before the response window closes.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Stripe to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and provide your Stripe API key. GAIA uses read-only Stripe access by default and Stripe webhook events to receive real-time payment notifications.",
      },
      {
        step: "Configure your payment event routing",
        description:
          "Specify which Stripe events should post to which Slack channels, what information to include in each notification, and what thresholds or conditions apply for milestone alerts and digest schedules.",
      },
      {
        step: "GAIA delivers Stripe events to Slack in real time",
        description:
          "GAIA listens to Stripe webhooks and posts formatted notifications to the configured Slack channels as payment events occur. Your team gets a live view of business revenue without anyone acting as a manual relay from the Stripe dashboard.",
      },
    ],
    faqs: [
      {
        question:
          "Can I control which Slack channels receive which types of Stripe events?",
        answer:
          "Yes. You can route different Stripe events to different channels. New subscriptions can go to #sales, failed payments to #support, disputes to #finance, and revenue summaries to #leadership — ensuring each team gets the relevant financial information without noise.",
      },
      {
        question:
          "Can GAIA suppress notifications for small test transactions in Stripe?",
        answer:
          "Yes. GAIA can filter out Stripe test mode events and can apply minimum threshold filters so that low-value transactions below a defined amount do not generate Slack notifications, keeping your channels focused on meaningful payment events.",
      },
      {
        question:
          "Does GAIA support Stripe Connect for platforms with multiple sub-accounts?",
        answer:
          "GAIA supports standard Stripe accounts fully. For Stripe Connect platforms, basic payment notifications are supported but deep sub-account analytics are on the roadmap. Contact the GAIA team for specific Connect use cases.",
      },
    ],
  },

  "slack-salesforce": {
    slug: "slack-salesforce",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Salesforce",
    toolBSlug: "salesforce",
    tagline:
      "Surface Salesforce CRM updates in Slack and create records from conversations",
    metaTitle:
      "Slack + Salesforce Automation - CRM Updates in Slack, Record Creation | GAIA",
    metaDescription:
      "Connect Slack and Salesforce with GAIA. Get CRM opportunity updates in Slack, create Salesforce tasks and leads from Slack messages, and keep your sales team aligned without switching platforms.",
    keywords: [
      "Slack Salesforce integration",
      "Salesforce updates in Slack",
      "Slack Salesforce automation",
      "create Salesforce record from Slack",
      "connect Slack and Salesforce",
      "Salesforce Slack CRM workflow",
    ],
    intro:
      "Sales teams use Slack to coordinate deal strategy, share competitive intelligence, and align on next steps — but the actual CRM data lives in Salesforce and is rarely consulted during Slack conversations. This disconnect means decisions are made without current CRM context, and insights shared in Slack never make it back into Salesforce where they belong. CRM data quality suffers and deals slip because the system of record is divorced from where the team actually collaborates.\n\nGAIA bridges Slack and Salesforce so that CRM context is available in Slack conversations and work done in Slack flows back into Salesforce automatically. When a rep discusses a deal in Slack, GAIA can pull the latest Salesforce Opportunity data into the thread. When a decision is made, GAIA creates the appropriate Salesforce task, note, or status update from the conversation. Salesforce alerts — stage changes, renewal dates, new leads — arrive in the right Slack channels in real time.\n\nThis is essential for enterprise sales teams, revenue operations managers, and account management teams who need their CRM to stay current without burdening sales reps with manual data entry.",
    useCases: [
      {
        title: "Salesforce opportunity updates in Slack",
        description:
          "When a Salesforce Opportunity advances to a new stage, has its close date changed, or is updated by a rep, GAIA posts a notification to the relevant Slack channel with the deal name, stage, amount, and what changed — so sales management has a real-time pipeline view without running Salesforce reports.",
      },
      {
        title: "Create Salesforce tasks from Slack messages",
        description:
          "When a rep types a follow-up commitment in Slack — 'need to send the proposal by Thursday' — GAIA creates a Salesforce task assigned to the rep with the correct due date and links it to the relevant Opportunity, ensuring no commitment made in Slack is lost from the CRM.",
      },
      {
        title: "Query Salesforce from Slack without leaving the app",
        description:
          "Sales reps can ask GAIA in Slack 'what is the current stage of the Acme deal?' or 'show me my pipeline for this quarter' and GAIA returns a formatted summary pulled live from Salesforce so reps can access CRM data in the flow of their Slack workflow.",
      },
      {
        title: "New lead alerts in Slack",
        description:
          "When a new Lead is created in Salesforce — from a web form, marketing campaign, or manual entry — GAIA posts an alert to your #sales or #sdr Slack channel with the lead details so SDRs can follow up immediately while the lead is warm.",
      },
      {
        title: "Deal renewal and expiration reminders",
        description:
          "GAIA monitors Salesforce contract and opportunity close dates and sends proactive reminders to the account owner's Slack DM and the team channel 30, 14, and 7 days before renewal or expiration so no deal renewal is missed due to a forgotten calendar entry.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Salesforce to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and connect your Salesforce organization. GAIA uses Salesforce's OAuth integration and requests the minimum permissions needed to read and write Leads, Contacts, Accounts, Opportunities, and Tasks.",
      },
      {
        step: "Configure CRM event routing and Slack commands",
        description:
          "Define which Salesforce record types and field changes should trigger Slack notifications, which Slack channels should receive each type of alert, and what Slack commands or triggers should create Salesforce records.",
      },
      {
        step: "GAIA keeps Slack and Salesforce connected in real time",
        description:
          "GAIA monitors Salesforce for the configured events and Slack for commands and commitments, routing information bidirectionally so your CRM stays accurate and your team has CRM context in Slack without context-switching.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA pull Salesforce data for a specific account directly into a Slack channel?",
        answer:
          "Yes. You can ask GAIA to post a Salesforce account summary — including open opportunities, recent activity, key contacts, and contract status — to any Slack channel. This is especially useful for preparing for customer calls when the team is coordinating in Slack.",
      },
      {
        question:
          "Does GAIA support Salesforce sandboxes for testing the integration?",
        answer:
          "Yes. GAIA supports both Salesforce production and sandbox environments. You can test your Slack-Salesforce workflows in a sandbox before enabling them in production to ensure the integration behaves as expected.",
      },
      {
        question:
          "Can GAIA update existing Salesforce records from Slack, not just create new ones?",
        answer:
          "Yes. GAIA can update existing Salesforce records based on Slack commands. For example, a rep can type 'update Acme deal stage to Proposal Sent' in Slack and GAIA will find the correct Salesforce Opportunity and update the stage, logging the change as an activity.",
      },
    ],
  },

  "slack-airtable": {
    slug: "slack-airtable",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Airtable",
    toolBSlug: "airtable",
    tagline:
      "Update Airtable records from Slack and get database alerts in your channels",
    metaTitle:
      "Slack + Airtable Automation - Database Updates from Slack | GAIA",
    metaDescription:
      "Connect Slack and Airtable with GAIA. Create and update Airtable records from Slack messages, receive database change notifications in Slack, and manage structured data from your team chat.",
    keywords: [
      "Slack Airtable integration",
      "update Airtable from Slack",
      "Slack Airtable automation",
      "Airtable notifications in Slack",
      "connect Slack and Airtable",
      "Airtable Slack database workflow",
    ],
    intro:
      "Airtable is a powerful way to organize structured data for operations, project management, and tracking — but keeping its records current requires team members to regularly log into Airtable and manually update entries. When teams are already coordinating in Slack, asking them to context-switch to Airtable for routine updates creates friction that leads to outdated records and databases that no longer reflect reality.\n\nGAIA bridges Slack and Airtable so that routine record updates happen in Slack and data changes surface in Slack automatically. Team members can create new Airtable records, update existing ones, and query database contents from Slack without ever opening Airtable. When important records are created or updated in Airtable — a new client onboarded, a project milestone reached, an inventory threshold crossed — Slack gets notified so the right people can act immediately.\n\nThis integration is ideal for operations teams running Airtable-based processes, project managers using Airtable for project tracking, HR teams managing onboarding checklists, and any team that needs their database to stay current without burdening people with context-switching.",
    useCases: [
      {
        title: "Create Airtable records from Slack with a slash command",
        description:
          "Team members can use a Slack command to create new Airtable records on the fly — logging a new client, submitting a content request, or reporting a bug — without leaving Slack. GAIA collects the required fields conversationally and creates the record with all data populated correctly.",
      },
      {
        title: "Update record status from Slack reactions or commands",
        description:
          "When a project task is completed, a team member can react to the associated Slack message with a checkmark emoji and GAIA updates the corresponding Airtable record status to 'Done' — keeping the database current with minimal effort from the team.",
      },
      {
        title: "Airtable record change notifications in Slack",
        description:
          "When an important Airtable record is updated — a client status changes, a project deadline shifts, or an inventory count drops below threshold — GAIA posts a structured notification to the relevant Slack channel so the team can act on the change immediately.",
      },
      {
        title: "Query Airtable data from Slack",
        description:
          "Team members can ask GAIA in Slack 'show me all open projects due this week' or 'how many leads did we add this month?' and GAIA queries the Airtable database and returns a formatted summary directly in the Slack thread without anyone needing to open Airtable.",
      },
      {
        title: "New record alerts for time-sensitive entries",
        description:
          "When a new high-priority record is created in Airtable — a new enterprise lead, a critical bug report, or an urgent client request — GAIA sends an immediate Slack alert to the appropriate channel or individual so response time is minimized.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Airtable to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and connect your Airtable account. Specify which Airtable bases and tables GAIA should have read and write access to, and which Slack channels should participate in the integration.",
      },
      {
        step: "Configure your commands and notification rules",
        description:
          "Define what Slack commands or triggers should create or update Airtable records, which Airtable field changes should trigger Slack notifications, and which channels or users should be notified for each event type.",
      },
      {
        step: "GAIA keeps Slack and Airtable synchronized automatically",
        description:
          "GAIA monitors both Slack and Airtable, creating and updating records from Slack activity and posting notifications to Slack for Airtable events. Your database stays current and your team stays informed without context-switching.",
      },
    ],
    faqs: [
      {
        question:
          "Can multiple team members update the same Airtable record from different Slack channels?",
        answer:
          "Yes. Multiple team members can update records via Slack commands. GAIA handles concurrent updates gracefully and will alert if a conflict is detected — for example, if two people try to set a record to different statuses at the same time.",
      },
      {
        question:
          "Can GAIA filter Airtable notifications to avoid flooding Slack with every small change?",
        answer:
          "Yes. You can configure notification rules to only trigger for specific field changes, record types, or conditions — such as only notifying when a record's status changes to 'Urgent' or when a numeric field exceeds a defined threshold.",
      },
      {
        question:
          "Does GAIA support Airtable linked record fields and lookup fields?",
        answer:
          "GAIA can read linked record fields and display their values in Slack queries. Creating linked records from Slack is supported for simple cases. Complex multi-table relationships may require additional configuration through GAIA's settings.",
      },
    ],
  },

  "slack-teams": {
    slug: "slack-teams",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Microsoft Teams",
    toolBSlug: "microsoft-teams",
    tagline:
      "Bridge Slack and Microsoft Teams for organizations using both platforms",
    metaTitle:
      "Slack + Microsoft Teams Bridge - Cross-Platform Messaging | GAIA",
    metaDescription:
      "Connect Slack and Microsoft Teams with GAIA. Cross-post messages between platforms, bridge teams using different collaboration tools, and keep Slack and Teams users aligned automatically.",
    keywords: [
      "Slack Microsoft Teams integration",
      "Slack Teams bridge",
      "cross-post Slack to Teams",
      "Slack Teams automation",
      "connect Slack and Microsoft Teams",
      "Slack Teams message sync",
    ],
    intro:
      "Mergers, acquisitions, and multi-vendor environments often leave organizations running both Slack and Microsoft Teams simultaneously, with different departments, teams, or partner organizations standardized on each platform. Keeping both sides informed requires manually copying messages, maintaining dual presence, or missing communications entirely — none of which are acceptable in a fast-moving business.\n\nGAIA bridges Slack and Microsoft Teams so that information flows between them according to your organizational rules. Announcements posted in a Slack channel can be automatically mirrored to a Teams channel. Escalations raised in Teams can appear in the relevant Slack channel. Shared project teams using different platforms can collaborate without either side losing visibility into key communications.\n\nThis integration is critical for enterprise organizations navigating platform migrations, companies that have acquired Slack-using startups into a Teams-first parent organization, and businesses whose external partners use a different platform than their internal teams.",
    useCases: [
      {
        title: "Bridge project channels across Slack and Teams",
        description:
          "When a cross-functional project team has members on both Slack and Teams, GAIA creates a synchronized channel bridge so that messages posted in the Slack project channel appear in the Teams project channel and vice versa, allowing both sides to collaborate without platform limitations.",
      },
      {
        title: "Company announcement mirroring",
        description:
          "When leadership posts a company-wide announcement in Slack, GAIA automatically mirrors it to the equivalent Teams channel so employees on both platforms receive the same information simultaneously without requiring a second manual post.",
      },
      {
        title: "External partner communication relay",
        description:
          "When your company uses Teams but your agency or technology partner uses Slack, GAIA relays messages between your Teams project channel and their Slack channel, enabling seamless collaboration without either party needing to adopt the other's platform.",
      },
      {
        title: "Escalation routing from Teams to Slack",
        description:
          "When a critical escalation is raised in a Teams channel, GAIA routes it to the corresponding Slack channel where the senior team typically operates, ensuring high-priority issues reach the right decision-makers regardless of which platform they are working in.",
      },
      {
        title: "Migration-period dual posting",
        description:
          "During a platform migration from Slack to Teams or vice versa, GAIA can ensure that all communications are posted to both platforms simultaneously so no team members miss information during the transition period, regardless of which platform they have adopted.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Microsoft Teams to GAIA",
        description:
          "Authorize GAIA in your Slack workspace and your Microsoft 365 tenant. GAIA uses Microsoft Graph API for Teams and the Slack API for Slack, requesting only the permissions needed to read and post messages in the specified channels.",
      },
      {
        step: "Configure your channel bridge rules",
        description:
          "Define which Slack channels should be bridged to which Teams channels, the direction of message flow (one-way or bidirectional), and any formatting or filtering rules to apply. You can configure separate rules for different teams or projects.",
      },
      {
        step: "GAIA synchronizes communications between Slack and Teams",
        description:
          "GAIA monitors both platforms and relays messages according to your bridge rules. Users on each platform see relevant communications from the other side in real time without needing to maintain dual presence or check both apps.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA prevent echo loops where a bridged message gets re-posted infinitely?",
        answer:
          "Yes. GAIA marks all messages it originates to prevent re-bridging. Messages posted by GAIA to Teams will not be forwarded back to Slack, and vice versa, ensuring a clean one-directional or bidirectional sync without infinite loops.",
      },
      {
        question:
          "Does GAIA support file and attachment sharing between Slack and Teams?",
        answer:
          "Text messages are bridged fully. File attachments are handled by posting a link to the original file rather than uploading a copy to the destination platform, since Teams and Slack use different file storage backends. Both sides can access the linked file.",
      },
      {
        question:
          "Is this bridge suitable as a permanent solution or only during migrations?",
        answer:
          "Both. GAIA supports permanent Slack-Teams bridges for organizations with a stable dual-platform setup, as well as temporary migration-period bridges that can be decommissioned once all users have transitioned to the target platform.",
      },
    ],
  },

  "gmail-figma": {
    slug: "gmail-figma",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Figma",
    toolBSlug: "figma",
    tagline:
      "Connect design feedback loops between Gmail and Figma so nothing gets lost in translation",
    metaTitle:
      "Gmail + Figma Automation - Email Design Feedback to Figma | GAIA",
    metaDescription:
      "Automate Gmail and Figma with GAIA. Convert email feedback into Figma comments, notify stakeholders of design updates by email, and keep design reviews moving without manual handoffs.",
    keywords: [
      "Gmail Figma integration",
      "email design feedback Figma",
      "Gmail Figma automation",
      "Figma comment from email",
      "connect Gmail and Figma",
      "design review email workflow",
    ],
    intro:
      "Design review cycles are notorious for feedback fragmentation. Stakeholders send design comments over email because that's the tool they're comfortable with, while designers work in Figma and need feedback directly on the canvas. The result is designers manually transcribing email feedback into Figma comments, stakeholders unsure whether their input was received, and review cycles that drag on longer than they should.\n\nGAIA bridges this gap by connecting Gmail feedback to Figma. When a stakeholder emails design feedback on a specific file or frame, GAIA can add that feedback as a comment on the correct Figma file, tagging the responsible designer. When a designer marks feedback as resolved in Figma or publishes a new version, GAIA can notify the stakeholder by email so they know to review the update.\n\nFor product and design teams working with non-technical stakeholders who will never open Figma, this automation means feedback actually lands where designers can act on it—and stakeholders stay informed without needing to learn a new tool.",
    useCases: [
      {
        title: "Convert email feedback into Figma comments",
        description:
          "When a stakeholder emails design feedback referencing a specific screen or flow, GAIA extracts the feedback and adds it as a comment on the relevant Figma file frame, tagging the designer responsible for that section.",
      },
      {
        title: "Notify stakeholders when designs are updated",
        description:
          "When a new version of a Figma file is published or a comment thread is resolved, GAIA sends an email to the relevant stakeholders with a direct link to the updated frame and a summary of what changed.",
      },
      {
        title: "Design approval request emails",
        description:
          "When a designer is ready for review, GAIA sends a formatted email to the approvers with a thumbnail, the Figma share link, the design brief summary, and a deadline for feedback, kickstarting the review cycle.",
      },
      {
        title: "Client design handoff email generation",
        description:
          "When a Figma project is marked ready for handoff, GAIA drafts a client-facing email with the file link, export instructions, and any relevant notes from the design brief, ready for the account manager to send.",
      },
      {
        title: "Feedback aggregation from multiple email reviewers",
        description:
          "When multiple stakeholders email feedback on the same design, GAIA consolidates all comments into a single structured Figma comment thread with each reviewer attributed, preventing comment duplication and chaos.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Figma to GAIA",
        description:
          "Authenticate your Gmail account and Figma workspace in GAIA's settings. GAIA accesses Figma files you specify and monitors Gmail for feedback-related email threads.",
      },
      {
        step: "Map email conversations to Figma files",
        description:
          "Tell GAIA which email threads or projects correspond to which Figma files. You can link by project name, client name, or specific Gmail label so GAIA routes feedback to the right canvas.",
      },
      {
        step: "Feedback flows between email and Figma automatically",
        description:
          "Email feedback becomes Figma comments, Figma updates trigger email notifications, and the review cycle moves forward without designers and stakeholders having to manually bridge the two tools.",
      },
    ],
    faqs: [
      {
        question: "How does GAIA know which Figma file an email refers to?",
        answer:
          "GAIA uses context from the email—project name, client name, subject line—and your configured mappings to identify the correct Figma file. You can also include a Figma file URL in the email to make the match unambiguous.",
      },
      {
        question:
          "Can GAIA add comments to specific frames rather than the whole file?",
        answer:
          "Yes, when the email feedback references a specific screen by name or description, GAIA will place the comment on the most relevant frame. For general feedback without a specific frame reference, the comment is added at the file level.",
      },
      {
        question: "Do stakeholders need a Figma account for this to work?",
        answer:
          "No. Stakeholders only interact via email. GAIA translates their email feedback into Figma comments using its own authenticated Figma connection, so external stakeholders never need to open Figma.",
      },
      {
        question: "Can GAIA send design files or exports as email attachments?",
        answer:
          "GAIA can include Figma share links and exported image previews in emails. For full file exports (PDF, PNG, SVG), GAIA can trigger a Figma export and attach the result to the outbound email where the API supports it.",
      },
    ],
  },

  "gmail-loom": {
    slug: "gmail-loom",
    toolA: "Gmail",
    toolASlug: "gmail",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Attach Loom video context to email workflows and never lose recorded insights in your inbox",
    metaTitle:
      "Gmail + Loom Automation - Email and Video Messaging Workflow | GAIA",
    metaDescription:
      "Automate Gmail and Loom with GAIA. Send Loom recordings triggered by emails, transcribe video content into email summaries, and keep async video communication organized.",
    keywords: [
      "Gmail Loom integration",
      "Loom video email automation",
      "Gmail Loom workflow",
      "send Loom from email",
      "connect Gmail and Loom",
      "Loom email summary",
    ],
    intro:
      "Loom recordings and email threads often carry different parts of the same conversation. A client emails a question that would take paragraphs to answer in text; a Loom video would explain it in two minutes. A team member records a Loom walkthrough of a problem; the recipients need to email it to external stakeholders with proper context. These two async communication formats rarely work together smoothly.\n\nGAIA connects Gmail and Loom to make video and email work as a unified async communication layer. When you receive an email that warrants a video response, GAIA can prompt you to record a Loom and automatically send the link with a transcript excerpt in reply. When a Loom video is shared with you, GAIA can generate a text summary and file it in Gmail with the relevant thread so the content is searchable.\n\nFor customer success teams, sales professionals, and async-first remote teams, this integration means video context is never isolated from the email conversations that surround it—and you spend less time deciding whether to type a long reply or record a video.",
    useCases: [
      {
        title: "Trigger Loom recording reminders from email threads",
        description:
          "When an email arrives that GAIA identifies as better suited for a video response—complex explanations, product demos, onboarding walkthroughs—GAIA flags it and prompts you to record a Loom, then handles sending the link as a reply.",
      },
      {
        title: "Summarize Loom videos received by email into text",
        description:
          "When someone emails you a Loom link, GAIA generates a text summary of the video content using the Loom transcript and adds it to the email thread as a note, so you can reference key points without rewatching.",
      },
      {
        title: "Share Loom recordings with external email recipients",
        description:
          "When a Loom is created internally for client communication, GAIA drafts the outbound email with the Loom link, a text summary excerpt, and the relevant context from previous email threads, ready to send with one click.",
      },
      {
        title: "Archive Loom content into searchable email threads",
        description:
          "GAIA takes Loom recordings shared across various channels and files their transcript summaries into the relevant Gmail thread, creating a single searchable record of both written and video communication.",
      },
      {
        title: "Automated follow-up after Loom views",
        description:
          "When GAIA detects that a recipient has viewed your Loom recording (via view notifications), it can draft a follow-up email asking for questions or next steps, keeping the conversation moving.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Gmail and Loom to GAIA",
        description:
          "Authenticate your Gmail account and Loom workspace in GAIA's settings. GAIA accesses your Loom library and Gmail inbox to coordinate content between them.",
      },
      {
        step: "Define your video-email workflow preferences",
        description:
          "Tell GAIA when to suggest video responses, how to format Loom summaries in email, and how to handle incoming Loom links. You set the rules in plain language.",
      },
      {
        step: "Video and email work together automatically",
        description:
          "GAIA handles the translation between Loom content and email threads, keeping async communication cohesive and making sure video context is never siloed from the conversations that need it.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA automatically transcribe Loom videos or use Loom's built-in transcript?",
        answer:
          "GAIA uses Loom's native transcript where available (Loom Business and above includes auto-transcription). For recordings without transcripts, GAIA can summarize based on the video title, description, and any captions.",
      },
      {
        question: "Can GAIA send a Loom reply directly from Gmail?",
        answer:
          "GAIA facilitates the workflow: it identifies the email needing a video response, prompts you to record, and then sends the Loom link as an email reply once you've completed the recording. The recording step itself happens in Loom.",
      },
      {
        question: "Does this work for shared Loom workspaces used by a team?",
        answer:
          "Yes. GAIA can be configured to monitor shared Loom workspaces and route video summaries or notifications to the appropriate team member's Gmail based on the video's assigned owner or topic.",
      },
      {
        question:
          "Can GAIA track whether email recipients have watched the Loom?",
        answer:
          "If Loom provides view analytics via its API, GAIA can monitor view status and trigger follow-up email drafts when a recipient has watched the recording. This depends on your Loom plan's analytics capabilities.",
      },
    ],
  },

  "slack-google-calendar": {
    slug: "slack-google-calendar",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Google Calendar",
    toolBSlug: "google-calendar",
    tagline:
      "Keep your Slack team informed of calendar events and reduce meeting no-shows automatically",
    metaTitle:
      "Slack + Google Calendar Automation - Calendar to Slack Sync | GAIA",
    metaDescription:
      "Automate Slack and Google Calendar with GAIA. Post meeting reminders to Slack channels, update your status from calendar events, and schedule meetings directly from Slack conversations.",
    keywords: [
      "Slack Google Calendar integration",
      "Slack calendar automation",
      "Google Calendar Slack reminders",
      "Slack meeting notifications",
      "connect Slack and Google Calendar",
      "calendar to Slack sync",
    ],
    intro:
      "Calendar events and Slack conversations are deeply connected in practice but completely disconnected in software. A meeting gets added to Google Calendar, but nobody on Slack knows about it unless someone manually announces it. A Slack discussion concludes with a decision to schedule a meeting, but that requires leaving Slack and opening Calendar. Status information about who's in a meeting versus available sits in Google Calendar but doesn't appear in Slack.\n\nGAIA connects Slack and Google Calendar so these two tools reinforce each other. Upcoming meetings can be announced in the right Slack channels automatically. Slack statuses can reflect your current calendar status—in a meeting, heads-down block, or out of office—without manual updates. Meetings can be scheduled from a Slack conversation by simply asking GAIA to find a time that works.\n\nFor distributed teams where Slack is the operational heartbeat, having calendar context surfaced automatically means fewer missed meetings, better coordination around availability, and a Slack status that's actually accurate.",
    useCases: [
      {
        title: "Post daily meeting schedules to team Slack channels",
        description:
          "Each morning, GAIA posts a summary of the day's scheduled meetings to the relevant Slack channels, so the team knows what's on the agenda and can coordinate around focus time and meeting blocks.",
      },
      {
        title: "Automatic Slack status from Google Calendar",
        description:
          "GAIA reads your Google Calendar and automatically updates your Slack status when you're in a meeting ('In a meeting until 3pm'), on a focus block ('Do not disturb'), or out of office ('OOO until Monday').",
      },
      {
        title: "Schedule Google Calendar meetings from Slack",
        description:
          "When a Slack thread concludes with a decision to meet, ask GAIA to find a time that works for all participants, create the Google Calendar event, and post the event link back to the Slack thread.",
      },
      {
        title: "Pre-meeting reminders in Slack",
        description:
          "GAIA sends a Slack DM reminder 10 minutes before scheduled meetings with the event title, attendees, video link, and any relevant prep notes from the calendar event description.",
      },
      {
        title: "Alert channels when key team members are unavailable",
        description:
          "When a team lead or key contributor has an all-day event or extended meeting block, GAIA notifies the relevant Slack channel so the team knows in advance and can plan accordingly.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Google Calendar to GAIA",
        description:
          "Authenticate your Slack workspace and Google Calendar account in GAIA's settings. GAIA accesses calendar events and can post to Slack channels and DMs you authorize.",
      },
      {
        step: "Configure your calendar-to-Slack preferences",
        description:
          "Tell GAIA which calendars to monitor, which Slack channels should receive which types of notifications, and how far in advance reminders should be sent. Define status update rules in plain language.",
      },
      {
        step: "Calendar and Slack stay in sync automatically",
        description:
          "GAIA monitors your Google Calendar and updates Slack proactively. Meeting reminders, status updates, and scheduling requests all flow automatically without you having to bridge the two tools manually.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA update Slack statuses for all team members or just the connected user?",
        answer:
          "GAIA updates Slack status for each user who connects their own Google Calendar. For team-wide status updates, each team member authenticates their own Calendar and Slack accounts, and GAIA manages their statuses individually.",
      },
      {
        question: "Which Google Calendar events trigger Slack notifications?",
        answer:
          "You configure the triggers. Common setups include all events on a team calendar, events matching specific keywords (all-hands, client meeting, launch), or events involving specific attendees. GAIA filters based on your rules.",
      },
      {
        question: "Can GAIA handle Google Calendar invites sent via Slack?",
        answer:
          "Yes. You can ask GAIA in a Slack message to schedule a meeting with specific people, and GAIA will check calendar availability, create the event, send invites through Google Calendar, and post the event summary back to Slack.",
      },
      {
        question: "Does GAIA work with shared and resource calendars?",
        answer:
          "GAIA can monitor shared team calendars and resource calendars (like meeting rooms) in addition to personal calendars. This is useful for posting conference room availability or shared team schedule updates to Slack.",
      },
    ],
  },

  "slack-hubspot": {
    slug: "slack-hubspot",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "HubSpot",
    toolBSlug: "hubspot",
    tagline:
      "Surface HubSpot deal and contact updates in Slack so your sales team never misses a signal",
    metaTitle: "Slack + HubSpot Automation - CRM Alerts in Slack | GAIA",
    metaDescription:
      "Automate Slack and HubSpot with GAIA. Get deal stage alerts in Slack, log Slack conversations to HubSpot contacts, and keep your sales team informed without switching between tools.",
    keywords: [
      "Slack HubSpot integration",
      "HubSpot deal alerts Slack",
      "Slack HubSpot automation",
      "CRM notifications Slack",
      "connect Slack and HubSpot",
      "HubSpot Slack workflow",
    ],
    intro:
      "Sales teams spend their days in Slack but their pipeline lives in HubSpot. When a deal advances, a contact submits a form, or a prospect's score crosses a threshold, that signal lives in HubSpot—invisible to the team collaborating in Slack. Meanwhile, important context shared in Slack deal threads never makes it back into HubSpot contact records or deal notes.\n\nGAIA connects Slack and HubSpot so the right information reaches the right people at the right time. Deal stage changes, new high-value leads, and pipeline milestones surface in Slack channels automatically. Slack conversations about a deal can be logged to HubSpot with a simple command. Sales managers get pipeline visibility in the tool they monitor most, and reps get CRM intelligence without leaving Slack.\n\nFor revenue teams where speed matters, having HubSpot signals in Slack means faster response times, better-informed team conversations, and a CRM that actually benefits from the Slack discussions happening around it.",
    useCases: [
      {
        title: "Deal stage change alerts in Slack",
        description:
          "When a HubSpot deal advances to a new stage—proposal sent, contract out, closed won, closed lost—GAIA posts a formatted alert to the #sales Slack channel so the team celebrates wins and learns from losses in real time.",
      },
      {
        title: "New lead notifications by territory or owner",
        description:
          "When a new lead is created in HubSpot, GAIA posts a Slack notification to the deal owner or the appropriate territory channel with the lead's key details, company, and lead score so reps can prioritize follow-up immediately.",
      },
      {
        title: "Log Slack deal discussions to HubSpot",
        description:
          "After a Slack thread discussing a deal strategy or a client situation, ask GAIA to log the key points as a HubSpot note on the relevant contact or deal record, keeping the CRM informed without manual copy-pasting.",
      },
      {
        title: "Pipeline summary reports to Slack",
        description:
          "GAIA posts a weekly pipeline report to the #sales-leadership channel summarizing deals by stage, total pipeline value, deals at risk, and upcoming close dates, giving leadership CRM visibility without logging into HubSpot.",
      },
      {
        title: "High-intent activity alerts",
        description:
          "When a HubSpot contact visits your pricing page, opens a proposal email, or reaches a lead score threshold, GAIA sends a real-time Slack alert to the deal owner so they can follow up at exactly the right moment.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and HubSpot to GAIA",
        description:
          "Authenticate your Slack workspace and HubSpot portal in GAIA's settings. GAIA connects to your HubSpot deals, contacts, and activity feeds and can post to the Slack channels you authorize.",
      },
      {
        step: "Configure your CRM alert rules",
        description:
          "Tell GAIA which HubSpot events should trigger Slack notifications, which channels should receive which alerts, and what information to include in each notification. Define Slack-to-HubSpot logging preferences as well.",
      },
      {
        step: "HubSpot intelligence flows into Slack automatically",
        description:
          "GAIA monitors HubSpot and posts relevant updates to Slack in real time. Your sales team stays informed and aligned without splitting their attention between two platforms constantly.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA notify different Slack channels for different HubSpot pipelines?",
        answer:
          "Yes. You can configure GAIA to route alerts from different HubSpot pipelines or deal stages to specific Slack channels. Enterprise deals go to #enterprise-sales, SMB deals to #smb-sales, and so on.",
      },
      {
        question: "Can I query HubSpot data directly from Slack?",
        answer:
          "Yes. You can ask GAIA in Slack to look up a contact, check a deal's current stage, or pull the latest activity on an account. GAIA queries HubSpot and returns the answer in the Slack thread.",
      },
      {
        question: "Can GAIA create HubSpot tasks from Slack messages?",
        answer:
          "Yes. You can instruct GAIA to create a HubSpot task associated with a contact or deal directly from a Slack message, setting the due date, owner, and description based on the conversation context.",
      },
      {
        question:
          "Does GAIA work with HubSpot custom properties and pipelines?",
        answer:
          "GAIA works with standard HubSpot objects and properties natively. For custom properties and pipelines, you can describe the field names and GAIA will include them in notifications and write to them when logging from Slack.",
      },
    ],
  },

  "slack-zoom": {
    slug: "slack-zoom",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Zoom",
    toolBSlug: "zoom",
    tagline:
      "Start, schedule, and follow up on Zoom meetings without ever leaving Slack",
    metaTitle: "Slack + Zoom Automation - Zoom Meetings from Slack | GAIA",
    metaDescription:
      "Automate Slack and Zoom with GAIA. Schedule Zoom meetings from Slack threads, post meeting summaries back to channels, and keep your team coordinated around video calls without app switching.",
    keywords: [
      "Slack Zoom integration",
      "schedule Zoom from Slack",
      "Slack Zoom automation",
      "Zoom meeting Slack workflow",
      "connect Slack and Zoom",
      "Zoom summary Slack",
    ],
    intro:
      "Slack is where team decisions get made and Zoom is where conversations happen, but the handoff between them is clunky. Scheduling a Zoom meeting from Slack requires app-switching, link-sharing, and calendar juggling. When a Zoom meeting ends, the decisions and action items discussed rarely make it back into the relevant Slack channel where the team continues to work.\n\nGAIA connects Slack and Zoom to make video meetings a native part of your Slack workflow. When a Slack conversation requires a real-time discussion, ask GAIA to schedule a Zoom meeting, find availability, and post the link to the channel. After the meeting ends, GAIA can post a summary of the discussion and action items back to the Slack thread so anyone who missed it is immediately caught up.\n\nFor remote and hybrid teams, this integration means the context gap between Zoom meetings and Slack work disappears. What's decided in Zoom lands back in Slack automatically, and scheduling Zoom from Slack is as easy as mentioning it in a message.",
    useCases: [
      {
        title: "Schedule Zoom meetings from Slack conversations",
        description:
          "When a Slack thread reaches a point where a meeting is needed, ask GAIA to schedule a Zoom call with the thread participants. GAIA checks availability, creates the Zoom meeting, and posts the invite link back to the channel.",
      },
      {
        title: "Post Zoom meeting summaries to Slack channels",
        description:
          "After a Zoom meeting ends, GAIA generates a summary of the discussion and key action items and posts it to the relevant Slack channel so the team has a written record without needing to take manual notes.",
      },
      {
        title: "Instant Zoom link for ongoing Slack discussions",
        description:
          "When a Slack back-and-forth gets too complicated for text, ask GAIA for a quick Zoom link. GAIA generates an instant meeting link and posts it to the thread so participants can jump on a call in seconds.",
      },
      {
        title: "Pre-meeting Slack reminders",
        description:
          "GAIA sends Slack DMs to meeting participants 10 minutes before scheduled Zoom calls with the meeting title, agenda, and join link, reducing no-shows without requiring calendar reminder configuration.",
      },
      {
        title: "Meeting recording notifications in Slack",
        description:
          "When a Zoom cloud recording is available, GAIA posts a notification in the relevant Slack channel with a link to the recording and a text summary, ensuring everyone can access meeting content even if they missed it.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Zoom to GAIA",
        description:
          "Authenticate your Slack workspace and Zoom account in GAIA's settings. GAIA integrates with both platforms to coordinate scheduling, meeting creation, and post-meeting content sharing.",
      },
      {
        step: "Define how meetings flow between Slack and Zoom",
        description:
          "Configure which Slack channels can trigger meeting scheduling, how post-meeting summaries should be formatted, and which channels receive recording notifications. Set preferences in plain language.",
      },
      {
        step: "Meetings and Slack work together seamlessly",
        description:
          "GAIA handles scheduling from Slack, posting meeting context, and routing post-meeting content back to the right channels. The gap between Zoom discussions and Slack work closes automatically.",
      },
    ],
    faqs: [
      {
        question:
          "Can GAIA start an instant Zoom meeting from a Slack command?",
        answer:
          "Yes. You can ask GAIA in any Slack channel or DM to start a Zoom meeting immediately. GAIA creates the meeting and posts the join link within seconds, no calendar scheduling required.",
      },
      {
        question: "Does GAIA use Zoom transcripts for meeting summaries?",
        answer:
          "When Zoom cloud transcription is enabled on your account (available on Zoom Business and above), GAIA uses the actual transcript to generate accurate meeting summaries. For accounts without transcription, GAIA generates summaries from meeting metadata and any notes shared.",
      },
      {
        question:
          "Can GAIA post the Zoom summary to a specific Slack channel rather than where it was scheduled?",
        answer:
          "Yes. You can configure GAIA to post summaries to a dedicated #meeting-notes channel, the channel where the meeting was scheduled, or both. You can also request a specific channel at scheduling time.",
      },
      {
        question: "Does this work for recurring Zoom meetings?",
        answer:
          "GAIA can schedule recurring Zoom meetings from a Slack request and post summaries after each occurrence. For recurring meetings, GAIA tracks each session separately and posts summaries to the designated channel after every meeting.",
      },
    ],
  },

  "slack-loom": {
    slug: "slack-loom",
    toolA: "Slack",
    toolASlug: "slack",
    toolB: "Loom",
    toolBSlug: "loom",
    tagline:
      "Make Loom videos a first-class part of your Slack workflow with automatic summaries and routing",
    metaTitle: "Slack + Loom Automation - Loom Videos in Slack Workflow | GAIA",
    metaDescription:
      "Automate Slack and Loom with GAIA. Get instant Loom video summaries in Slack, route recordings to the right channels, and keep async video communication organized within your team's workflow.",
    keywords: [
      "Slack Loom integration",
      "Loom video Slack automation",
      "Slack Loom summary",
      "Loom notifications Slack",
      "connect Slack and Loom",
      "async video Slack workflow",
    ],
    intro:
      "Loom recordings are a powerful async communication tool, but they create a new coordination problem: who has seen the video, which channel should it go in, and what were the key takeaways for people who don't have time to watch? When Looms are shared ad-hoc in Slack, they often sit unviewed or their content never gets discussed because extracting context from a video mid-Slack-thread requires too much friction.\n\nGAIA makes Loom videos a productive part of your Slack workflow by handling the translation between the two. When a Loom is shared in Slack, GAIA generates a text summary and adds it as a reply so everyone gets the key points instantly. When a new Loom is created in your workspace, GAIA routes it to the appropriate Slack channel based on the content or creator. Team members can respond to a Loom's content directly in Slack, and GAIA keeps the conversation organized.\n\nFor async-first teams where Loom is a primary communication format, this integration means video content is no longer a black box in Slack—it's a structured, searchable, actionable part of the team's communication flow.",
    useCases: [
      {
        title: "Auto-summarize Loom links shared in Slack",
        description:
          "When a team member shares a Loom link in any Slack channel, GAIA generates a concise text summary of the video content and replies in the thread so everyone can get the key points without watching the full recording.",
      },
      {
        title: "Route new Loom recordings to the right Slack channels",
        description:
          "When a Loom is created in your workspace, GAIA analyzes the title, description, and content to route it to the most relevant Slack channel automatically—product updates to #product, customer feedback recordings to #customer-success.",
      },
      {
        title: "Extract action items from Loom recordings",
        description:
          "GAIA processes Loom transcripts to identify action items, decisions, and commitments mentioned in the recording, and posts them as a structured list in the Slack thread so nothing is lost in the video.",
      },
      {
        title: "Notify Slack when Loom recordings are viewed",
        description:
          "When a shared Loom recording is viewed by all intended recipients, GAIA can post a Slack notification confirming everyone has seen the video, helping async teams confirm information has been received.",
      },
      {
        title: "Weekly Loom digest to team channels",
        description:
          "GAIA compiles a weekly digest of Loom recordings created by and for your team, posts it to the relevant Slack channel with summaries of each video, and ensures no recorded update gets missed.",
      },
    ],
    howItWorks: [
      {
        step: "Connect Slack and Loom to GAIA",
        description:
          "Authenticate your Slack workspace and Loom account in GAIA's settings. GAIA monitors your Loom workspace and the Slack channels you designate for automatic processing.",
      },
      {
        step: "Set your Loom-to-Slack workflow rules",
        description:
          "Tell GAIA how to handle new Loom recordings—which channels to route them to, whether to auto-summarize, and what to extract from transcripts. Define rules in plain language based on your team's workflow.",
      },
      {
        step: "Loom content becomes active in Slack automatically",
        description:
          "As Loom recordings are created and shared, GAIA processes them, routes them to the right channels, and surfaces their content in text form so video communication becomes a searchable part of your Slack history.",
      },
    ],
    faqs: [
      {
        question:
          "Does GAIA summarize all Loom links or only from specific workspaces?",
        answer:
          "You configure the scope. GAIA can summarize all Loom links shared in monitored channels, only recordings from your organization's Loom workspace, or only Looms matching specific criteria like title keywords or creator.",
      },
      {
        question: "What Loom plan is needed for GAIA to access transcripts?",
        answer:
          "Loom's auto-transcription is available on Business plans and above. For Starter plan recordings without transcripts, GAIA summarizes based on the video title, description, and any captions included by the creator.",
      },
      {
        question:
          "Can GAIA prompt team members to record a Loom from within Slack?",
        answer:
          "Yes. You can ask GAIA in Slack to suggest a Loom recording for a specific topic or to a specific person. GAIA will generate a suggested recording prompt and can send a Slack DM to the relevant person encouraging them to record.",
      },
      {
        question:
          "Does this work with Loom recordings shared from outside my organization?",
        answer:
          "GAIA can summarize public Loom links shared in Slack regardless of whether they're from your organization, as long as the recordings are publicly accessible. For private Loom recordings, access depends on the sharing settings of the video.",
      },
    ],
  },
};
