"use client";

import { Chip } from "@heroui/chip";
import { m, useInView } from "motion/react";
import { useRef } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const INTEGRATIONS = [
  { name: "Gmail", category: "gmail" },
  { name: "Slack", category: "slack" },
  { name: "GitHub", category: "github" },
  { name: "Notion", category: "notion" },
  { name: "Linear", category: "linear" },
  { name: "HubSpot", category: "hubspot" },
  { name: "Google Calendar", category: "googlecalendar" },
  { name: "Asana", category: "asana" },
  { name: "Todoist", category: "todoist" },
  { name: "Zoom", category: "zoom" },
  { name: "Figma", category: "figma" },
  { name: "Stripe", category: "stripe" },
  { name: "Discord", category: "discord" },
  { name: "Telegram", category: "telegram" },
  { name: "Trello", category: "trello" },
  { name: "Airtable", category: "airtable" },
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
      <div className="flex flex-wrap gap-2 justify-center">
        {INTEGRATIONS.map((integration, index) => {
          const icon = getToolCategoryIcon(integration.category, {
            width: 14,
            height: 14,
            showBackground: false,
          });
          return (
            <m.div
              key={integration.name}
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
              <Chip
                size="sm"
                variant="flat"
                classNames={{
                  base: "bg-zinc-800 border-0",
                  content: "text-zinc-300 text-xs font-medium",
                }}
                startContent={
                  icon ? <span className="ml-1">{icon}</span> : undefined
                }
              >
                {integration.name}
              </Chip>
            </m.div>
          );
        })}
      </div>
    </div>
  );
}
