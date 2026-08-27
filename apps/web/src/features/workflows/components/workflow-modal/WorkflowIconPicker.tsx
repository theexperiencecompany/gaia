import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Tooltip } from "@heroui/tooltip";
import { PlusSignIcon, Search01Icon } from "@icons";
import { useMemo, useState } from "react";
import { type Control, useController } from "react-hook-form";

import { cn } from "@/lib/utils";
import {
  DEFAULT_WORKFLOW_ICON_COLOR,
  searchWorkflowIcons,
  WORKFLOW_ICON_BG_ALPHA,
  WORKFLOW_ICON_CATALOG,
  WORKFLOW_ICON_COLORS,
  WORKFLOW_ICON_MAP,
  WORKFLOW_SUGGESTED_ICONS,
  type WorkflowIconDef,
  workflowIconLabel,
} from "../../constants/workflowIconCatalog";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";

interface WorkflowIconPickerProps {
  control: Control<WorkflowFormData>;
  isReadOnly?: boolean;
}

interface IconGridProps {
  icons: WorkflowIconDef[];
  selectedName: string | null | undefined;
  onPick: (def: WorkflowIconDef) => void;
}

function IconGrid({ icons, selectedName, onPick }: IconGridProps) {
  return (
    <div className="grid grid-cols-8 gap-1">
      {icons.map((def) => (
        <Tooltip
          key={def.name}
          content={workflowIconLabel(def.name)}
          delay={300}
          closeDelay={0}
          size="sm"
        >
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label={workflowIconLabel(def.name)}
            className={cn(
              "text-zinc-300",
              selectedName === def.name && "bg-zinc-700",
            )}
            onPress={() => onPick(def)}
          >
            <def.Icon size={18} />
          </Button>
        </Tooltip>
      ))}
    </div>
  );
}

export default function WorkflowIconPicker({
  control,
  isReadOnly = false,
}: WorkflowIconPickerProps) {
  const { field: iconField } = useController({ control, name: "icon" });
  const { field: colorField } = useController({ control, name: "icon_color" });
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");

  const isSearching = query.trim().length > 0;
  const results = useMemo(
    () => (isSearching ? searchWorkflowIcons(query) : WORKFLOW_ICON_CATALOG),
    [query, isSearching],
  );
  const suggested = useMemo(
    () =>
      WORKFLOW_SUGGESTED_ICONS.map((name) =>
        WORKFLOW_ICON_MAP.get(name),
      ).filter((def): def is WorkflowIconDef => !!def),
    [],
  );

  const selected = iconField.value
    ? WORKFLOW_ICON_MAP.get(iconField.value)
    : undefined;
  const color = colorField.value ?? DEFAULT_WORKFLOW_ICON_COLOR;
  const tintedBg = { backgroundColor: `${color}${WORKFLOW_ICON_BG_ALPHA}` };

  const pickIcon = (def: WorkflowIconDef) => {
    iconField.onChange(def.name);
    if (!colorField.value) {
      colorField.onChange(DEFAULT_WORKFLOW_ICON_COLOR);
    }
  };

  if (isReadOnly) {
    if (!selected) return null;
    return (
      <div
        className="-mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-lg"
        style={tintedBg}
      >
        <selected.Icon size={20} style={{ color }} />
      </div>
    );
  }

  return (
    <Popover
      isOpen={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        if (!open) setQuery("");
      }}
      placement="bottom-start"
    >
      <PopoverTrigger>
        <Button
          isIconOnly
          variant="flat"
          radius="sm"
          aria-label={selected ? "Change workflow icon" : "Add workflow icon"}
          className={cn(
            "-mt-0.5 size-10 min-w-10 shrink-0",
            !selected && "bg-zinc-800",
          )}
          style={selected ? tintedBg : undefined}
        >
          {selected ? (
            <selected.Icon size={20} style={{ color }} />
          ) : (
            <PlusSignIcon className="size-5 text-zinc-500" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 bg-zinc-800 p-3">
        <div className="flex w-full flex-col gap-3">
          <Input
            autoFocus
            size="sm"
            value={query}
            onValueChange={setQuery}
            placeholder="Search icons..."
            startContent={
              <Search01Icon className="size-4 shrink-0 text-zinc-500" />
            }
            classNames={{ inputWrapper: "bg-zinc-900" }}
          />

          <div className="flex items-center justify-between gap-1">
            {WORKFLOW_ICON_COLORS.map((swatch) => (
              <Button
                key={swatch}
                isIconOnly
                radius="full"
                aria-label={`Use color ${swatch}`}
                className={cn(
                  "size-6 min-w-6 shrink-0",
                  color === swatch &&
                    "ring-2 ring-white/80 ring-offset-2 ring-offset-zinc-800",
                )}
                style={{ backgroundColor: swatch }}
                onPress={() => colorField.onChange(swatch)}
              />
            ))}
          </div>

          <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
            {!isSearching && (
              <>
                <p className="text-xs font-medium text-zinc-500">Suggested</p>
                <IconGrid
                  icons={suggested}
                  selectedName={iconField.value}
                  onPick={pickIcon}
                />
                <p className="text-xs font-medium text-zinc-500">All icons</p>
              </>
            )}
            <IconGrid
              icons={results}
              selectedName={iconField.value}
              onPick={pickIcon}
            />
          </div>

          {results.length === 0 && (
            <p className="py-4 text-center text-xs text-zinc-500">
              No icons match your search
            </p>
          )}

          {selected && (
            <Button
              size="sm"
              variant="light"
              className="self-start text-zinc-400"
              onPress={() => {
                iconField.onChange(null);
                colorField.onChange(null);
                setIsOpen(false);
              }}
            >
              Remove icon
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
