"use client";

import { ListBox, Popover, Select, Switch } from "@heroui/react";
import { CpuIcon } from "@icons";
import Image from "next/image";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { DEV_MODEL_OPTIONS } from "@/features/chat/constants/devModels";
import { isDevelopment } from "@/lib/environment";
import { useComposerModelSelection } from "@/stores/composerStore";

interface ModelLogoProps {
  readonly src: string;
  readonly alt: string;
  readonly size: number;
}

function ModelLogo({ src, alt, size }: ModelLogoProps) {
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

interface ModelSelectProps {
  readonly label: string;
  readonly selectedId: string;
  readonly onSelect: (id: string) => void;
  readonly isDisabled: boolean;
}

function ModelSelect({
  label,
  selectedId,
  onSelect,
  isDisabled,
}: ModelSelectProps) {
  const current = DEV_MODEL_OPTIONS.find((m) => m.id === selectedId);

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-medium tracking-wide text-zinc-500 uppercase">
        {label}
      </span>
      <Select
        aria-label={`${label} agent model`}
        selectedKey={selectedId}
        onSelectionChange={(key) => {
          if (typeof key === "string") onSelect(key);
        }}
        isDisabled={isDisabled}
        variant="secondary"
        className="w-full"
      >
        <Select.Trigger className="h-9 min-h-9 cursor-pointer bg-zinc-800">
          {current ? (
            <ModelLogo src={current.logo} alt={current.provider} size={16} />
          ) : null}
          <GaiaSelectValue>{current?.name ?? "Model"}</GaiaSelectValue>
          <Select.Indicator className="text-zinc-500" />
        </Select.Trigger>
        <Select.Popover className="bg-zinc-800">
          <ListBox>
            {DEV_MODEL_OPTIONS.map((m) => (
              <ListBox.Item
                key={m.id}
                id={m.id}
                textValue={m.name}
                className="gap-2 rounded-lg"
              >
                <ModelLogo src={m.logo} alt={m.provider} size={18} />
                <span className="text-xs text-zinc-200">{m.name}</span>
              </ListBox.Item>
            ))}
          </ListBox>
        </Select.Popover>
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
    <Popover>
      <GaiaButton
        shape="pill"
        isIconOnly
        size="sm"
        variant="ghost"
        aria-label="Dev model selector"
        // Tint primary when a non-default model is pinned, so it's obvious at a
        // glance that the dev override is active.
        className={
          useDefaultModels ? "text-zinc-400 hover:text-primary" : "text-primary"
        }
      >
        <CpuIcon width={20} height={20} />
      </GaiaButton>
      <Popover.Content
        placement="bottom end"
        offset={8}
        className="w-[260px] bg-zinc-900 p-3"
      >
        <div className="flex w-full flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold tracking-wide text-zinc-300 uppercase">
              Dev models
            </span>
            <Switch
              size="sm"
              isSelected={useDefaultModels}
              onChange={setUseDefaultModels}
              aria-label="Use plan-default models"
            >
              <Switch.Content>
                <Switch.Control>
                  <Switch.Thumb />
                </Switch.Control>
                <span className="text-[11px] text-zinc-400">Defaults</span>
              </Switch.Content>
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
      </Popover.Content>
    </Popover>
  );
}
