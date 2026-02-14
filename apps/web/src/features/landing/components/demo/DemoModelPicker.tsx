"use client";

import { Select, SelectItem, SelectSection } from "@heroui/react";
import { BubbleChatSparkIcon } from "@icons";
import Image from "next/image";
import { useState } from "react";
import { DEMO_MODELS, MODEL_PROVIDERS } from "./demoConstants";

export default function DemoModelPicker() {
  const [selected, setSelected] = useState("claude-sonnet-4-5-20250929");
  const current = DEMO_MODELS.find((m) => m.id === selected);

  return (
    <Select
      selectedKeys={new Set([selected])}
      onSelectionChange={(keys) => {
        const k = Array.from(keys)[0];
        if (k && typeof k === "string") setSelected(k);
      }}
      variant="flat"
      aria-label={current?.name ?? "AI Model"}
      disallowEmptySelection
      className="w-fit! max-w-none!"
      popoverProps={{
        classNames: { content: "min-w-[340px] max-w-none bg-zinc-800" },
      }}
      classNames={{
        trigger:
          "cursor-pointer bg-transparent transition hover:bg-zinc-800! !min-w-fit !w-auto !max-w-none whitespace-nowrap px-2 pr-9 h-8",
        value: "text-zinc-400! text-xs font-medium whitespace-nowrap !w-auto",
        base: "!max-w-none !w-auto",
        innerWrapper: "!w-auto !max-w-none",
        mainWrapper: "!w-auto !max-w-none",
        selectorIcon: "text-zinc-500 h-4 w-4",
      }}
      scrollShadowProps={{ isEnabled: false }}
      startContent={
        <BubbleChatSparkIcon className="text-zinc-500" width={18} height={18} />
      }
      renderValue={() => <span>{current?.name ?? "Model"}</span>}
    >
      {MODEL_PROVIDERS.map((provider) => (
        <SelectSection
          key={provider}
          classNames={{
            heading:
              "flex w-full sticky top-0 z-20 py-2 px-2 bg-zinc-800 text-zinc-200 text-xs font-medium",
          }}
          title={provider}
        >
          {DEMO_MODELS.filter((m) => m.provider === provider).map((m) => (
            <SelectItem
              key={m.id}
              textValue={m.name}
              classNames={{
                base: "py-2.5 px-2 data-[hover=true]:bg-zinc-700/50 gap-3 items-start rounded-xl",
                title: "text-zinc-200",
              }}
              startContent={
                <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-zinc-700/50">
                  <Image
                    src={m.logo}
                    alt={m.provider}
                    width={20}
                    height={20}
                    loading="lazy"
                    className="h-5 w-5 rounded object-contain"
                  />
                </div>
              }
            >
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-zinc-100">
                    {m.name}
                  </span>
                  {m.is_default && (
                    <span className="rounded-full bg-green-500/20 px-1.5 py-0.5 text-[10px] text-green-400">
                      Default
                    </span>
                  )}
                  {m.tier === "pro" && (
                    <span className="rounded-full bg-yellow-500/20 px-1.5 py-0.5 text-[10px] text-yellow-400">
                      Pro
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-400">{m.description}</p>
              </div>
            </SelectItem>
          ))}
        </SelectSection>
      ))}
    </Select>
  );
}
