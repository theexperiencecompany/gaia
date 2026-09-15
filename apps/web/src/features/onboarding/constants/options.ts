/**
 * The onboarding option lists, `as const` so their values are a compile-time
 * union (`./options.types.ts`): a need added here without a chip style, or a
 * style for a need that no longer exists, fails to compile.
 */

import type { NeedOption, ProfessionOption } from "../types";

export const professionOptions = [
  { label: "Founder / CEO", value: "founder" },
  { label: "Executive", value: "executive" },
  { label: "Sales", value: "sales" },
  { label: "Product", value: "product" },
  { label: "Creative", value: "creative" },
  { label: "Engineering", value: "engineering" },
  { label: "Marketing", value: "marketing" },
  { label: "Finance", value: "finance" },
  { label: "Student", value: "student" },
  { label: "Other", value: "other" },
] as const satisfies readonly ProfessionOption[];

/**
 * Q2 options everyone sees: pains in the user's words, each a different job
 * GAIA can start on, so the picks mean something downstream (the seeded
 * thread's chips, the connect-link order, the bot's opener).
 * `value` mirrors the backend `OnboardingNeed` StrEnum
 * (`apps/api/app/models/user_models.py`) one-for-one — the API rejects
 * anything outside that set, so the two lists must stay in lockstep. The
 * first-person phrasing lives in `first_message.py` next to the enum.
 */
export const needOptions = [
  { value: "inbox", label: "Inbox out of control" },
  { value: "calendar", label: "Walking into meetings cold" },
  { value: "mornings", label: "Mornings start behind" },
  { value: "reminders", label: "Things I keep forgetting" },
  { value: "grunt_work", label: "Grunt work every week" },
  { value: "tools", label: "Too many tools to juggle" },
] as const satisfies readonly NeedOption[];

/**
 * Two extra pains per Q1 role, shown first and marked as personalised. Keys
 * are `professionOptions` values; mirrors `ROLE_NEEDS` on the API, which
 * rejects a role need sent with a different profession.
 */
export const roleNeedOptions = {
  founder: [
    { value: "founder_team_updates", label: "Team updates I chase" },
    { value: "founder_competitors", label: "Competitors I never track" },
  ],
  executive: [
    { value: "executive_reports", label: "Reports I never read" },
    { value: "executive_decisions", label: "Decisions piling up" },
  ],
  sales: [
    { value: "sales_leads", label: "Leads going cold" },
    { value: "sales_call_research", label: "Research before every call" },
  ],
  product: [
    { value: "product_feedback", label: "Feedback scattered everywhere" },
    { value: "product_specs", label: "Specs that take forever" },
  ],
  marketing: [
    { value: "marketing_content", label: "Content always behind" },
    { value: "marketing_reports", label: "Reports by hand" },
  ],
  engineering: [
    { value: "engineering_prs", label: "PRs waiting on me" },
    { value: "engineering_notifications", label: "Drowning in notifications" },
  ],
  finance: [
    { value: "finance_numbers", label: "Chasing people for numbers" },
    { value: "finance_reports", label: "Same report every week" },
  ],
  creative: [
    { value: "creative_revisions", label: "Client revisions piling up" },
    { value: "creative_deadlines", label: "Deadlines sneaking up" },
  ],
  student: [
    { value: "student_assignments", label: "Assignments piling up" },
    { value: "student_exams", label: "Exams I'm not ready for" },
  ],
} as const satisfies Partial<
  Record<(typeof professionOptions)[number]["value"], readonly NeedOption[]>
>;

/** Q2's catch-all. Not a backend need: it opens a field whose text is sent as
 * `other_need`, so this value never lands in `selectedNeeds`. */
export const OTHER_NEED = "something_else";
