"use client";

import { m, useInView } from "motion/react";
import { useRef } from "react";

const INTEGRATIONS = [
  "Gmail",
  "Slack",
  "GitHub",
  "Notion",
  "Linear",
  "HubSpot",
  "Google Calendar",
  "Jira",
  "Asana",
  "Todoist",
  "Zoom",
  "Dropbox",
  "Figma",
  "Stripe",
  "Shopify",
  "Discord",
  "Telegram",
  "Trello",
  "Intercom",
  "Salesforce",
];

export default function IntegrationsDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });

  return (
    <div ref={ref} className="w-full">
      <m.div
        className="rounded-full bg-[#00bbff]/20 border border-[#00bbff]/30 px-6 py-2 text-sm font-medium text-[#00bbff] mx-auto w-fit mb-4"
        initial={{ opacity: 0, scale: 0.9 }}
        animate={inView ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.9 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
      >
        GAIA
      </m.div>
      <div className="grid grid-cols-4 gap-2">
        {INTEGRATIONS.map((name, index) => (
          <m.span
            key={name}
            className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-zinc-300 font-medium text-center"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={
              inView ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.85 }
            }
            transition={{
              duration: 0.25,
              ease: "easeOut",
              delay: 0.3 + index * 0.04,
            }}
          >
            {name}
          </m.span>
        ))}
      </div>
    </div>
  );
}
