import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const PR_ITEMS = [
  {
    id: "pr-1",
    branch: "feat/auth-refactor",
    number: "#214",
    author: "Sarah K.",
    age: "3d old",
    urgent: true,
    stats: "+847 -312 · 23 files changed · 0 approvals",
  },
  {
    id: "pr-2",
    branch: "fix/rate-limit-bypass",
    number: "#218",
    author: "Alex M.",
    age: "1d old",
    urgent: false,
    stats: "+42 -8 · security fix · 1/2 approvals",
  },
  {
    id: "pr-3",
    branch: "chore/update-deps",
    number: "#221",
    author: "Bot",
    age: "12h old",
    urgent: false,
    stats: "Dependabot update · ready to merge",
  },
  {
    id: "pr-4",
    branch: "feat/settings-modal",
    number: "#222",
    author: "Maya R.",
    age: "8h old",
    urgent: false,
    stats: "Design implementation · waiting on review",
  },
];

export default function PRReviewCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {getToolCategoryIcon("github", {
            width: 16,
            height: 16,
            showBackground: false,
          })}
          <span className="text-[11px] font-medium text-zinc-400">
            4 PRs need your review
          </span>
        </div>
        <span className="text-[11px] text-zinc-500">oldest: 3 days ago</span>
      </div>
      <div className="space-y-2">
        {PR_ITEMS.map((item) => (
          <div key={item.id} className="rounded-xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-primary">
                {item.branch}{" "}
                <span className="font-mono text-xs text-zinc-500">
                  ({item.number})
                </span>
              </span>
              {item.urgent && (
                <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">
                  Urgent
                </span>
              )}
            </div>
            <p className="mt-1 text-[11px] text-zinc-500">
              {item.author} · {item.age}
            </p>
            <p className="mt-1 text-xs text-zinc-400">{item.stats}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
