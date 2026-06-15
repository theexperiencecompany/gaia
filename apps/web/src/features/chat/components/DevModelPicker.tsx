"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { AiBrainIcon, CpuIcon } from "@icons";
import {
  DEV_MODEL_OPTIONS,
  devModelLabel,
} from "@/features/chat/constants/devModels";
import { isDevelopment } from "@/lib/fetchAll";
import { useComposerDevModels } from "@/stores/composerStore";

const NULL_KEY = "__default__";

interface AgentModelDropdownProps {
  icon: React.ReactNode;
  prefix: string;
  selected: string | null;
  onSelect: (model: string | null) => void;
}

function AgentModelDropdown({
  icon,
  prefix,
  selected,
  onSelect,
}: AgentModelDropdownProps) {
  return (
    <Dropdown placement="bottom-end">
      <DropdownTrigger>
        <Button
          size="sm"
          variant="flat"
          radius="full"
          startContent={icon}
          className="h-7 bg-zinc-800/80 text-xs text-zinc-300"
        >
          {prefix}: {devModelLabel(selected)}
        </Button>
      </DropdownTrigger>
      <DropdownMenu
        aria-label={`${prefix} model`}
        selectionMode="single"
        selectedKeys={[selected ?? NULL_KEY]}
        onAction={(key) =>
          onSelect(key === NULL_KEY ? null : (String(key) as string))
        }
      >
        {DEV_MODEL_OPTIONS.map((option) => (
          <DropdownItem key={option.id ?? NULL_KEY}>
            {option.label}
          </DropdownItem>
        ))}
      </DropdownMenu>
    </Dropdown>
  );
}

/**
 * Dev-only (ENV=development) picker to override the comms and executor agent
 * models independently via OpenRouter, for benchmarking models per task.
 * Renders nothing in production.
 */
export function DevModelPicker() {
  const {
    selectedCommsModel,
    selectedExecutorModel,
    setSelectedCommsModel,
    setSelectedExecutorModel,
  } = useComposerDevModels();

  if (!isDevelopment()) return null;

  return (
    <div className="mr-1 flex items-center gap-1">
      <AgentModelDropdown
        icon={<AiBrainIcon className="h-4 w-4" />}
        prefix="Comms"
        selected={selectedCommsModel}
        onSelect={setSelectedCommsModel}
      />
      <AgentModelDropdown
        icon={<CpuIcon className="h-4 w-4" />}
        prefix="Exec"
        selected={selectedExecutorModel}
        onSelect={setSelectedExecutorModel}
      />
    </div>
  );
}
