/**
 * Icon and pastel tint for each onboarding option chip, keyed by the option
 * `value` in `professionOptions` / `needOptions`. Tints are whole class
 * strings so Tailwind can see them; a chip lifts to the solid tint when picked.
 */

import {
  Brain01Icon,
  Briefcase01Icon,
  Calendar01Icon,
  ChartIncreaseIcon,
  CodeIcon,
  InboxIcon,
  Megaphone01Icon,
  Mortarboard01Icon,
  PaintBoardIcon,
  PuzzleIcon,
  Rocket01Icon,
  Search01Icon,
  SmartPhone01Icon,
  SparklesIcon,
  SunriseIcon,
  TaskDone01Icon,
  UserMultipleIcon,
  WorkflowSquare01Icon,
} from "@icons";
import type { ComponentType, SVGProps } from "react";

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

export const OPTION_STYLE: Record<string, OptionStyle> = {
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
  briefings: { icon: SunriseIcon, tint: TINTS.amber },
  todos: { icon: TaskDone01Icon, tint: TINTS.emerald },
  memory: { icon: Brain01Icon, tint: TINTS.pink },
  research: { icon: Search01Icon, tint: TINTS.teal },
  automation: { icon: WorkflowSquare01Icon, tint: TINTS.orange },
  reach: { icon: SmartPhone01Icon, tint: TINTS.indigo },
};
