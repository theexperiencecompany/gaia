import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const TOUCHPOINTS = [
  "Mar 1 — You: sent pricing proposal (opened 3×)",
  'Feb 26 — Sarah: "Looks interesting, will loop in CTO"',
  "Feb 20 — Demo call (78 min, very engaged)",
];

const TALKING_POINTS = [
  "• Reference their enterprise tier launch — scaling need",
  "• CTO objection: security/data residency (address proactively)",
  "• Offer: 30-day pilot with dedicated onboarding",
];

export default function MeetingPrepCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-0.5 flex items-center gap-2">
        {getToolCategoryIcon("googlecalendar", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="text-sm font-medium text-zinc-100">
          Meeting Brief — Sarah Chen, VP Sales @ ByteScale
        </span>
      </div>
      <p className="mb-4 text-[11px] text-zinc-500">
        11:00 AM · 30 min · Google Meet
      </p>

      <div className="space-y-3">
        <div>
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Company
          </p>
          <div className="rounded-lg bg-zinc-900 p-2.5">
            <p className="text-xs text-zinc-400">
              ByteScale · 180 employees · Series B ($24M, Dec 2024)
            </p>
            <p className="mt-1 text-xs text-zinc-300">
              Recent: Launched new enterprise tier last month
            </p>
          </div>
        </div>

        <div>
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Deal Context
          </p>
          <div className="rounded-lg bg-zinc-900 p-2.5">
            <p className="text-xs text-zinc-300">
              Stage: Proposal Sent · Value: $22,000/yr
            </p>
            <p className="mt-1 text-xs text-zinc-400">
              Days in stage: 12 · Decision: Sarah + CTO
            </p>
          </div>
        </div>

        <div>
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Last 3 touchpoints
          </p>
          <div className="rounded-lg bg-zinc-900 p-2.5">
            <div className="space-y-1">
              {TOUCHPOINTS.map((point) => (
                <p key={point} className="text-xs text-zinc-400">
                  {point}
                </p>
              ))}
            </div>
          </div>
        </div>

        <div>
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Suggested talking points
          </p>
          <div className="rounded-lg bg-zinc-900 p-2.5">
            <div className="space-y-1">
              {TALKING_POINTS.map((point) => (
                <p key={point} className="text-xs text-zinc-300">
                  {point}
                </p>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
