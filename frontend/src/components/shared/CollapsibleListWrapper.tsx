import { Accordion, AccordionItem } from "@heroui/accordion";
import { ReactNode, useState } from "react";

interface CollapsibleListWrapperProps {
  children: ReactNode;
  icon: ReactNode;
  count: number;
  label: string; // e.g., "Email", "Contact", "Person/People", "Event"
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

  // Determine plural form
  const getCountLabel = () => {
    if (label === "Person/People") {
      return `${count} ${count === 1 ? "Person" : "People"}`;
    }
    return `${count} ${label}${count !== 1 ? "s" : ""}`;
  };

  if (!isCollapsible) {
    return <div className="w-full">{children}</div>;
  }

  return (
    <div className="w-full">
      <Accordion
        className="w-full max-w-(--breakpoint-sm) px-0"
        defaultExpandedKeys={defaultExpanded ? ["1"] : []}
        itemClasses={{ trigger: "cursor-pointer" }}
      >
        <AccordionItem
          key="1"
          aria-label={`${label} List`}
          indicator={<></>}
          title={
            <div className="flex items-center gap-2 text-sm font-normal text-zinc-400 transition hover:text-white">
              {icon}
              <div>
                {isExpanded ? "Hide" : "Show"} {getCountLabel()}
              </div>
            </div>
          }
          onPress={() => setIsExpanded((prev) => !prev)}
          className="w-screen max-w-(--breakpoint-sm) px-0"
          isCompact
        >
          {children}
        </AccordionItem>
      </Accordion>
    </div>
  );
}
