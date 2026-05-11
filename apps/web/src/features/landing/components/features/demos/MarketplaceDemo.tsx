"use client";

import { Download01Icon } from "@icons";
import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface MarketplaceCard {
  name: string;
  creator: string;
  description: string;
  clones: string;
  category: string;
  iconCategory: string;
  tags: string[];
}

const CARDS: MarketplaceCard[] = [
  {
    name: "GitHub PR Digest",
    creator: "@devtools_co",
    description: "Weekly summary of open PRs posted to your Slack channel",
    clones: "1.2k",
    category: "Automation",
    iconCategory: "github",
    tags: ["GitHub", "Slack"],
  },
  {
    name: "Stripe Revenue Digest",
    creator: "@revops_labs",
    description: "Daily MRR, churn, and new subscription summary via email",
    clones: "891",
    category: "Finance",
    iconCategory: "stripe",
    tags: ["Stripe", "Gmail"],
  },
  {
    name: "Linear Standup Bot",
    creator: "@mkaye",
    description: "Pulls in-progress issues and posts a standup digest to Slack",
    clones: "643",
    category: "Productivity",
    iconCategory: "linear",
    tags: ["Linear", "Slack"],
  },
  {
    name: "Email to Task",
    creator: "@automator_io",
    description:
      "Converts flagged emails into GAIA tasks with priority and due date",
    clones: "512",
    category: "Automation",
    iconCategory: "gmail",
    tags: ["Gmail", "Tasks"],
  },
  {
    name: "Notion Meeting Notes",
    creator: "@notionhacks",
    description: "Summarizes Google Meet transcripts and saves to Notion",
    clones: "334",
    category: "Productivity",
    iconCategory: "notion",
    tags: ["Notion", "Meet"],
  },
  {
    name: "HubSpot Deal Alert",
    creator: "@crm_crew",
    description: "Pings Slack when high-value deals move stages in HubSpot",
    clones: "278",
    category: "Sales",
    iconCategory: "hubspot",
    tags: ["HubSpot", "Slack"],
  },
];

export default function MarketplaceDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });

  return (
    <div ref={ref} className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {CARDS.map((card, index) => (
        <m.div
          key={card.name}
          initial={{ opacity: 0, y: 16 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
          transition={{ duration: 0.4, delay: index * 0.08, ease: "easeOut" }}
          className="rounded-2xl bg-zinc-800 p-4 flex flex-col gap-2.5"
        >
          {/* Header */}
          <div className="flex items-start gap-3">
            <div className="shrink-0 mt-0.5">
              {getToolCategoryIcon(card.iconCategory, {
                width: 22,
                height: 22,
              })}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-zinc-100">
                  {card.name}
                </span>
                <span className="rounded-full bg-zinc-700/60 px-2 py-0.5 text-[10px] text-zinc-400 shrink-0">
                  {card.category}
                </span>
              </div>
              <p className="text-[11px] text-zinc-500 mt-0.5">{card.creator}</p>
            </div>
          </div>

          {/* Description */}
          <p className="text-xs text-zinc-400 leading-relaxed">
            {card.description}
          </p>

          {/* Footer */}
          <div className="flex items-center justify-between mt-auto pt-1">
            <div className="flex items-center gap-1.5">
              {card.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-md bg-zinc-700/50 px-1.5 py-0.5 text-[10px] text-zinc-500"
                >
                  {tag}
                </span>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-zinc-500 flex items-center gap-1">
                <Download01Icon className="size-3" />
                {card.clones}
              </span>
              <button
                type="button"
                className="rounded-lg bg-[#00bbff]/10 text-[#00bbff] text-xs px-3 py-1 font-medium hover:bg-[#00bbff]/20 transition-colors"
              >
                Install
              </button>
            </div>
          </div>
        </m.div>
      ))}
    </div>
  );
}
