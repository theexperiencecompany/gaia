import { Accordion, AccordionItem } from "@heroui/accordion";
import type { Selection } from "@heroui/react";
import { type ReactNode, useState } from "react";

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
      {/* @ts-ignore - HeroUI Accordion has overly complex union types */}
      <Accordion
        className="w-full max-w-(--breakpoint-sm) px-0"
        defaultExpandedKeys={defaultKeys}
        itemClasses={{ trigger: "cursor-pointer" }}
        onSelectionChange={(keys) => {
          setIsExpanded(keys instanceof Set && keys.has("1"));
        }}
      >
        <AccordionItem
          key="1"
          aria-label={`${label} List`}
          indicator={null}
          title={
            <div className="flex items-center gap-2 text-sm font-normal text-zinc-400 transition hover:text-white">
              {icon}
              <div>
                {isExpanded ? "Hide" : "Show"} {getCountLabel()}
              </div>
            </div>
          }
          className="w-screen max-w-(--breakpoint-sm) px-0"
          isCompact
        >
          {children}
        </AccordionItem>
      </Accordion>
    </div>
  );
}
