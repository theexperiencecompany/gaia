import type { Selection } from "@heroui/react";
import { Accordion } from "@heroui/react";
import { type ReactNode, useState } from "react";
import {
  ACCORDION_INDICATOR,
  ACCORDION_PANEL_COMPACT,
  ACCORDION_TRIGGER_COMPACT,
} from "@/lib/heroui/accordionParity";

interface CollapsibleListWrapperProps {
  children: ReactNode;
  icon: ReactNode;
  count: number;
  label: string;
  isCollapsible?: boolean;
  defaultExpanded?: boolean;
}

export default function CollapsibleListWrapper({
  children,
  icon,
  count,
  label,
  isCollapsible = true,
  defaultExpanded = true,
}: CollapsibleListWrapperProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  const getCountLabel = () => {
    if (label === "Person/People") {
      return `${count} ${count === 1 ? "Person" : "People"}`;
    }
    return `${count} ${label}${count !== 1 ? "s" : ""}`;
  };

  if (!isCollapsible) {
    return <div className="w-full">{children}</div>;
  }

  const defaultKeys: Selection = defaultExpanded ? new Set(["1"]) : new Set([]);

  return (
    <div className="w-full">
      <Accordion
        className="w-full max-w-(--breakpoint-sm)"
        defaultExpandedKeys={defaultKeys}
        onExpandedChange={(keys) => {
          setIsExpanded(keys instanceof Set && keys.has("1"));
        }}
      >
        <Accordion.Item id="1" className="w-screen max-w-(--breakpoint-sm)">
          <Accordion.Heading>
            <Accordion.Trigger
              className={`cursor-pointer ${ACCORDION_TRIGGER_COMPACT}`}
            >
              <div className="flex items-center gap-2 text-sm font-normal text-zinc-400 transition hover:text-white">
                {icon}
                <div>
                  {isExpanded ? "Hide" : "Show"} {getCountLabel()}
                </div>
              </div>
              <Accordion.Indicator className={ACCORDION_INDICATOR} />
            </Accordion.Trigger>
          </Accordion.Heading>
          <Accordion.Panel className={ACCORDION_PANEL_COMPACT}>
            {children}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </div>
  );
}
