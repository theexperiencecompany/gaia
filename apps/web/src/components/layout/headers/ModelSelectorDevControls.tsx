"use client";

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectItem,
  Switch,
} from "@heroui/react";
import { CpuIcon } from "@icons";
import Image from "next/image";

import { DEV_MODEL_OPTIONS } from "@/features/chat/constants/devModels";
import { isDevelopment } from "@/lib/fetchAll";
import { useComposerModelSelection } from "@/stores/composerStore";

function ModelLogo({
  src,
  alt,
  size,
}: {
  src: string;
  alt: string;
  size: number;
}) {
  return (
    <Image
      src={src}
      alt={alt}
      width={size}
      height={size}
      loading="lazy"
      className="shrink-0 rounded object-contain"
    />
  );
}

function ModelSelect({
  label,
  selectedId,
  onSelect,
  isDisabled,
}: {
  label: string;
  selectedId: string;
  onSelect: (id: string) => void;
  isDisabled: boolean;
}) {
  const current = DEV_MODEL_OPTIONS.find((m) => m.id === selectedId);

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-medium tracking-wide text-zinc-500 uppercase">
        {label}
      </span>
      <Select
        size="sm"
        aria-label={`${label} agent model`}
        selectedKeys={new Set([selectedId])}
        onSelectionChange={(keys) => {
          const k = Array.from(keys)[0];
          if (typeof k === "string") onSelect(k);
        }}
        isDisabled={isDisabled}
        disallowEmptySelection
        variant="flat"
        className="w-full"
        popoverProps={{ classNames: { content: "bg-zinc-800" } }}
        classNames={{
          trigger:
            "h-9 min-h-9 cursor-pointer bg-zinc-800 data-[hover=true]:bg-zinc-700",
          value: "text-xs font-medium text-zinc-200",
          selectorIcon: "text-zinc-500",
        }}
        startContent={
          current ? (
            <ModelLogo src={current.logo} alt={current.provider} size={16} />
          ) : null
        }
        renderValue={() => (
          <span className="truncate">{current?.name ?? "Model"}</span>
        )}
      >
        {DEV_MODEL_OPTIONS.map((m) => (
          <SelectItem
            key={m.id}
            textValue={m.name}
            classNames={{
              base: "gap-2 rounded-lg data-[hover=true]:bg-zinc-700/60",
              title: "text-xs text-zinc-200",
            }}
            startContent={<ModelLogo src={m.logo} alt={m.provider} size={18} />}
          >
            {m.name}
          </SelectItem>
        ))}
      </Select>
    </div>
  );
}

export default function ModelSelectorDevControls() {
  const {
    useDefaultModels,
    commsModel,
    executorModel,
    setUseDefaultModels,
    setCommsModel,
    setExecutorModel,
  } = useComposerModelSelection();

  // NODE_ENV is a build-time constant, so the hook above always runs in the same
  // order — gating after it keeps the rules-of-hooks contract intact.
  if (!isDevelopment()) return null;

  return (
    <Popover placement="bottom-end" offset={8}>
      <PopoverTrigger>
        <Button
          isIconOnly
          size="sm"
          radius="full"
          variant="light"
          aria-label="Dev model selector"
          // Tint primary when a non-default model is pinned, so it's obvious at a
          // glance that the dev override is active.
          className={
            useDefaultModels
              ? "text-zinc-400 hover:text-primary"
              : "text-primary"
          }
        >
          <CpuIcon width={20} height={20} />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[260px] bg-zinc-900 p-3">
        <div className="flex w-full flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold tracking-wide text-zinc-300 uppercase">
              Dev models
            </span>
            <Switch
              size="sm"
              isSelected={useDefaultModels}
              onValueChange={setUseDefaultModels}
              aria-label="Use plan-default models"
              classNames={{ label: "text-[11px] text-zinc-400" }}
            >
              Defaults
            </Switch>
          </div>
          <ModelSelect
            label="Comms"
            selectedId={commsModel}
            onSelect={setCommsModel}
            isDisabled={useDefaultModels}
          />
          <ModelSelect
            label="Executor"
            selectedId={executorModel}
            onSelect={setExecutorModel}
            isDisabled={useDefaultModels}
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}
