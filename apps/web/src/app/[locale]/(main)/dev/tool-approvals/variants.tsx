"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Switch } from "@heroui/switch";
import { useMemo, useState } from "react";
import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";

export interface VariantProps {
  tools: IntegrationToolEntry[];
  gated: Set<string>;
  onToggle: (name: string, next: boolean) => void;
}

function ToolRow({
  tool,
  gated,
  onToggle,
  showSwitch,
}: {
  tool: IntegrationToolEntry;
  gated: Set<string>;
  onToggle: (name: string, next: boolean) => void;
  showSwitch: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="truncate text-sm text-zinc-300">{tool.label}</span>
      {showSwitch ? (
        <Switch
          size="sm"
          isSelected={gated.has(tool.name)}
          onValueChange={(v) => onToggle(tool.name, v)}
          aria-label={`Require approval for ${tool.label}`}
        />
      ) : (
        gated.has(tool.name) && (
          <Chip
            size="sm"
            variant="flat"
            color="warning"
            className="h-5 text-[10px]"
          >
            Asks first
          </Chip>
        )
      )}
    </div>
  );
}

/** A — plain tool list; approvals live behind an explicit "Manage approvals" mode. */
export function VariantManageMode({ tools, gated, onToggle }: VariantProps) {
  const [managing, setManaging] = useState(false);
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs text-zinc-500">
          {managing
            ? "Toggle which tools ask first"
            : `${gated.size} of ${tools.length} ask first`}
        </span>
        <Button size="sm" variant="flat" onPress={() => setManaging((m) => !m)}>
          {managing ? "Done" : "Manage approvals"}
        </Button>
      </div>
      {tools.map((tool) => (
        <ToolRow
          key={tool.name}
          tool={tool}
          gated={gated}
          onToggle={onToggle}
          showSwitch={managing}
        />
      ))}
    </div>
  );
}

/** B — grouped: needs-approval expanded, runs-automatically collapsed. */
export function VariantGrouped({ tools, gated, onToggle }: VariantProps) {
  const asks = tools.filter((t) => gated.has(t.name));
  const auto = tools.filter((t) => !gated.has(t.name));
  return (
    <Accordion
      selectionMode="multiple"
      isCompact
      defaultExpandedKeys={["asks"]}
      itemClasses={{ trigger: "cursor-pointer py-1" }}
    >
      <AccordionItem
        key="asks"
        title={
          <span className="text-sm text-zinc-200">
            Asks first ({asks.length})
          </span>
        }
      >
        {asks.length === 0 && (
          <p className="pb-2 text-xs text-zinc-500">Nothing needs approval.</p>
        )}
        {asks.map((tool) => (
          <ToolRow
            key={tool.name}
            tool={tool}
            gated={gated}
            onToggle={onToggle}
            showSwitch
          />
        ))}
      </AccordionItem>
      <AccordionItem
        key="auto"
        title={
          <span className="text-sm text-zinc-200">
            Runs automatically ({auto.length})
          </span>
        }
      >
        {auto.map((tool) => (
          <ToolRow
            key={tool.name}
            tool={tool}
            gated={gated}
            onToggle={onToggle}
            showSwitch
          />
        ))}
      </AccordionItem>
    </Accordion>
  );
}

/** C — search + bulk actions for huge tool lists. */
export function VariantSearchBulk({ tools, gated, onToggle }: VariantProps) {
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? tools.filter((t) => t.label.toLowerCase().includes(q)) : tools;
  }, [tools, query]);

  const setAll = (next: boolean) => {
    for (const tool of visible) onToggle(tool.name, next);
  };

  return (
    <div>
      <Input
        size="sm"
        variant="flat"
        placeholder={`Search ${tools.length} tools`}
        value={query}
        onValueChange={setQuery}
        className="mb-2"
      />
      <div className="mb-2 flex items-center gap-2">
        <Button size="sm" variant="flat" onPress={() => setAll(true)}>
          Ask for all{query ? " shown" : ""}
        </Button>
        <Button size="sm" variant="flat" onPress={() => setAll(false)}>
          Allow all{query ? " shown" : ""}
        </Button>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {visible.map((tool) => (
          <ToolRow
            key={tool.name}
            tool={tool}
            gated={gated}
            onToggle={onToggle}
            showSwitch
          />
        ))}
        {visible.length === 0 && (
          <p className="py-4 text-center text-xs text-zinc-500">
            No tools match.
          </p>
        )}
      </div>
    </div>
  );
}
