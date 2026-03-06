import {
  Alert01Icon,
  ArrowRight02Icon,
  CheckListIcon,
  CheckmarkCircle02Icon,
} from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

export default function StakeholderUpdateCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("gmail", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="flex-1 text-sm font-medium text-zinc-100">
          Weekly Stakeholder Update — Week of March 3
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          Draft ready
        </span>
      </div>

      <div className="rounded-xl bg-zinc-900 p-3">
        <p className="flex items-center gap-1 text-xs font-medium text-zinc-200">
          <CheckListIcon width={12} height={12} className="text-zinc-400" />
          This Week in Product
        </p>
        <p className="text-xs text-zinc-400 mt-1">
          Sprint 24: 64% complete (14/22 tickets)
        </p>

        <p className="flex items-center gap-1 text-xs font-medium text-zinc-200 mt-2 mb-0.5">
          <CheckmarkCircle02Icon
            width={12}
            height={12}
            className="text-emerald-400"
          />
          Shipped:
        </p>
        <p className="text-xs text-zinc-300">
          • Dark mode (v2.4.1) — 3 weeks early
        </p>
        <p className="text-xs text-zinc-300">
          • Search timeout fix — user-reported resolution
        </p>

        <p className="flex items-center gap-1 text-xs font-medium text-zinc-200 mt-2 mb-0.5">
          <ArrowRight02Icon width={12} height={12} className="text-zinc-400" />
          Next Week:
        </p>
        <p className="text-xs text-zinc-300">
          • Mobile checkout (targeting Mar 14)
        </p>
        <p className="text-xs text-zinc-300">• Auth refactor completion</p>

        <p className="flex items-center gap-1 text-xs font-medium text-zinc-200 mt-2 mb-0.5">
          <Alert01Icon width={12} height={12} className="text-red-400" />
          Needs Decision:
        </p>
        <p className="text-xs text-zinc-300">
          • Payment error UI spec — blocking mobile checkout
        </p>

        <p className="text-xs text-zinc-400 mt-2">Next review: March 13</p>
      </div>

      <span className="mt-2 inline-block rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary">
        Ready to send · 3 recipients
      </span>
    </div>
  );
}
