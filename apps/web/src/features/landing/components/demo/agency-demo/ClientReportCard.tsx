import {
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Loading03Icon,
  Target02Icon,
} from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const COMPLETED_ITEMS = [
  "Homepage and hero section — dev complete, QA passed",
  "6 inner pages responsive across all breakpoints",
  "Performance: Lighthouse score 94 (was 71)",
];

const IN_PROGRESS_ITEMS = [
  "Contact and blog sections (80% complete)",
  "CMS integration with existing content",
];

const NEXT_WEEK_ITEMS = [
  "Final dev handoff and client staging review",
  "UAT with TechCorp team (Thursday)",
];

export default function ClientReportCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-center gap-2">
        {getToolCategoryIcon("gmail", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="flex-1 text-sm font-medium text-zinc-100">
          Weekly Status Report — TechCorp
        </span>
        <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-400">
          Draft ready
        </span>
      </div>

      <div className="mt-3 rounded-xl bg-zinc-900 p-3">
        <p className="mb-2 text-xs text-zinc-400">
          Project: Website Redesign — Phase 2
          <br />
          Week ending: March 6, 2026
        </p>

        <p className="mb-0.5 mt-2 flex items-center gap-1 text-xs font-medium text-zinc-200">
          <CheckmarkCircle02Icon
            width={12}
            height={12}
            className="text-emerald-400"
          />
          Completed this week:
        </p>
        {COMPLETED_ITEMS.map((item) => (
          <p key={item} className="text-xs text-zinc-400">
            • {item}
          </p>
        ))}

        <p className="mb-0.5 mt-2 flex items-center gap-1 text-xs font-medium text-zinc-200">
          <Loading03Icon width={12} height={12} className="text-amber-400" />
          In Progress:
        </p>
        {IN_PROGRESS_ITEMS.map((item) => (
          <p key={item} className="text-xs text-zinc-400">
            • {item}
          </p>
        ))}

        <p className="mb-0.5 mt-2 flex items-center gap-1 text-xs font-medium text-zinc-200">
          <Calendar03Icon width={12} height={12} className="text-zinc-400" />
          Next Week:
        </p>
        {NEXT_WEEK_ITEMS.map((item) => (
          <p key={item} className="text-xs text-zinc-400">
            • {item}
          </p>
        ))}

        <p className="mb-0.5 mt-2 flex items-center gap-1 text-xs font-medium text-zinc-200">
          <Target02Icon width={12} height={12} className="text-zinc-400" />
          Timeline:
        </p>
        <p className="text-xs text-emerald-400">
          On track — launch target March 22
        </p>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] text-primary">
          cc: project@techcorp.com
        </span>
      </div>
    </div>
  );
}
