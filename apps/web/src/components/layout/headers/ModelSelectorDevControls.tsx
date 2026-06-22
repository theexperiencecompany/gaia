"use client";

import { Select, SelectItem, Switch } from "@heroui/react";
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
    <div className="flex items-center gap-1.5">
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
        className="w-[185px]"
        popoverProps={{
          classNames: { content: "min-w-[230px] bg-zinc-800" },
        }}
        classNames={{
          trigger:
            "h-8 min-h-8 cursor-pointer bg-zinc-800 data-[hover=true]:bg-zinc-700",
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

  // NODE_ENV is build-time constant, so the hook above always runs in the same
  // order — gating after it keeps the rules-of-hooks contract intact.
  if (!isDevelopment()) return null;

  return (
    <div className="flex items-center gap-3">
      <Switch
        size="sm"
        isSelected={useDefaultModels}
        onValueChange={setUseDefaultModels}
        aria-label="Use plan-default models"
        classNames={{ label: "text-[10px] text-zinc-400" }}
      >
        Defaults
      </Switch>
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
  );
}
