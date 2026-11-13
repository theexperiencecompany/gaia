/**
 * Icon and pastel tint for each onboarding option chip, keyed by the option
 * `value` in `professionOptions` / `needOptions`. Tints are whole class
 * strings so Tailwind can see them; a chip lifts to the solid tint when picked.
 */

import {
  AlarmClockIcon,
  Analytics01Icon,
  BookOpen01Icon,
  Briefcase01Icon,
  Calendar01Icon,
  ChartBarLineIcon,
  ChartIncreaseIcon,
  CheckListIcon,
  CodeIcon,
  Comment01Icon,
  File01Icon,
  Flag01Icon,
  GitPullRequestIcon,
  HourglassIcon,
  InboxIcon,
  Layers01Icon,
  Megaphone01Icon,
  Message01Icon,
  Mortarboard01Icon,
  Notification01Icon,
  PaintBoardIcon,
  PencilEdit01Icon,
  PencilEdit02Icon,
  PuzzleIcon,
  Rocket01Icon,
  Search01Icon,
  SparklesIcon,
  SunriseIcon,
  Target01Icon,
  TaskEdit01Icon,
  TelescopeIcon,
  UserCheck01Icon,
  UserGroupIcon,
  UserMultipleIcon,
  WorkflowSquare01Icon,
} from "@icons";
import type { ComponentType, SVGProps } from "react";

import type { OptionValue } from "./options.types";

export interface OptionTint {
  /** Resting look: translucent pastel fill, tinted text and icon. */
  idle: string;
  /** Picked look: solid pastel fill, dark text and icon. */
  active: string;
}

const TINTS = {
  rose: {
    idle: "bg-rose-400/15 text-rose-200",
    active: "bg-rose-300 text-rose-950",
  },
  amber: {
    idle: "bg-amber-400/15 text-amber-200",
    active: "bg-amber-300 text-amber-950",
  },
  emerald: {
    idle: "bg-emerald-400/15 text-emerald-200",
    active: "bg-emerald-300 text-emerald-950",
  },
  violet: {
    idle: "bg-violet-400/15 text-violet-200",
    active: "bg-violet-300 text-violet-950",
  },
  pink: {
    idle: "bg-pink-400/15 text-pink-200",
    active: "bg-pink-300 text-pink-950",
  },
  sky: {
    idle: "bg-sky-400/15 text-sky-200",
    active: "bg-sky-300 text-sky-950",
  },
  orange: {
    idle: "bg-orange-400/15 text-orange-200",
    active: "bg-orange-300 text-orange-950",
  },
  teal: {
    idle: "bg-teal-400/15 text-teal-200",
    active: "bg-teal-300 text-teal-950",
  },
  indigo: {
    idle: "bg-indigo-400/15 text-indigo-200",
    active: "bg-indigo-300 text-indigo-950",
  },
  fuchsia: {
    idle: "bg-fuchsia-400/15 text-fuchsia-200",
    active: "bg-fuchsia-300 text-fuchsia-950",
  },
} satisfies Record<string, OptionTint>;

export interface OptionStyle {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  tint: OptionTint;
}

export const OPTION_STYLE: Record<OptionValue, OptionStyle> = {
  // professions
  founder: { icon: Rocket01Icon, tint: TINTS.rose },
  executive: { icon: Briefcase01Icon, tint: TINTS.amber },
  sales: { icon: UserMultipleIcon, tint: TINTS.emerald },
  product: { icon: PuzzleIcon, tint: TINTS.violet },
  creative: { icon: PaintBoardIcon, tint: TINTS.pink },
  engineering: { icon: CodeIcon, tint: TINTS.sky },
  marketing: { icon: Megaphone01Icon, tint: TINTS.orange },
  finance: { icon: ChartIncreaseIcon, tint: TINTS.teal },
  student: { icon: Mortarboard01Icon, tint: TINTS.indigo },
  other: { icon: SparklesIcon, tint: TINTS.fuchsia },

  // needs
  inbox: { icon: InboxIcon, tint: TINTS.sky },
  calendar: { icon: Calendar01Icon, tint: TINTS.violet },
  mornings: { icon: SunriseIcon, tint: TINTS.amber },
  reminders: { icon: AlarmClockIcon, tint: TINTS.emerald },
  grunt_work: { icon: WorkflowSquare01Icon, tint: TINTS.orange },
  tools: { icon: Layers01Icon, tint: TINTS.teal },
  something_else: { icon: PencilEdit01Icon, tint: TINTS.indigo },

  // role needs
  founder_team_updates: { icon: UserGroupIcon, tint: TINTS.rose },
  founder_competitors: { icon: TelescopeIcon, tint: TINTS.fuchsia },
  executive_reports: { icon: File01Icon, tint: TINTS.amber },
  executive_decisions: { icon: Flag01Icon, tint: TINTS.rose },
  sales_leads: { icon: Target01Icon, tint: TINTS.emerald },
  sales_call_research: { icon: Search01Icon, tint: TINTS.teal },
  product_feedback: { icon: Comment01Icon, tint: TINTS.violet },
  product_specs: { icon: TaskEdit01Icon, tint: TINTS.pink },
  marketing_content: { icon: PencilEdit02Icon, tint: TINTS.orange },
  marketing_reports: { icon: ChartBarLineIcon, tint: TINTS.amber },
  engineering_prs: { icon: GitPullRequestIcon, tint: TINTS.sky },
  engineering_notifications: { icon: Notification01Icon, tint: TINTS.rose },
  finance_numbers: { icon: UserCheck01Icon, tint: TINTS.teal },
  finance_reports: { icon: Analytics01Icon, tint: TINTS.emerald },
  creative_revisions: { icon: Message01Icon, tint: TINTS.pink },
  creative_deadlines: { icon: HourglassIcon, tint: TINTS.orange },
  student_assignments: { icon: CheckListIcon, tint: TINTS.indigo },
  student_exams: { icon: BookOpen01Icon, tint: TINTS.violet },
};
