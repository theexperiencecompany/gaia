"use client";

import { Button } from "@heroui/button";

export type ProviderMode = "hosted" | "ollama" | "skip";

const PROVIDER_MODE_TABS: readonly { key: ProviderMode; label: string }[] = [
  { key: "hosted", label: "Hosted key" },
  { key: "ollama", label: "Local Ollama · free" },
  { key: "skip", label: "Skip for now" },
];

interface ProviderModeTabsProps {
  mode: ProviderMode;
  onChange: (mode: ProviderMode) => void;
}

/** The provider step's top-level choice: a hosted key, free local Ollama, or skipping. */
export function ProviderModeTabs({ mode, onChange }: ProviderModeTabsProps) {
  return (
    <div className="flex gap-1 rounded-full bg-zinc-900 p-1">
      {PROVIDER_MODE_TABS.map((tab) => {
        const selected = mode === tab.key;
        return (
          <Button
            key={tab.key}
            size="sm"
            radius="full"
            variant={selected ? "solid" : "light"}
            color={selected ? "primary" : "default"}
            className={
              selected
                ? "flex-1 font-medium"
                : "flex-1 font-medium text-zinc-400"
            }
            onPress={() => onChange(tab.key)}
          >
            {tab.label}
          </Button>
        );
      })}
    </div>
  );
}
