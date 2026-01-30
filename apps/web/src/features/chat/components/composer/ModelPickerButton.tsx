import {
  Chip,
  Select,
  SelectItem,
  SelectSection,
  type SharedSelection,
} from "@heroui/react";
import Image from "next/image";
import type React from "react";
import { useMemo } from "react";
import { BubbleChatSparkIcon } from "@/components/shared/icons";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import {
  useCurrentUserModel,
  useModels,
  useSelectModel,
} from "../../hooks/useModels";

const ModelPickerButton: React.FC = () => {
  const { data: models, isLoading } = useModels();
  const selectModelMutation = useSelectModel();
  const currentModel = useCurrentUserModel();
  const user = useUser();
  const { setUser } = useUserActions();

  const handleSelectionChange = (keys: SharedSelection) => {
    const selectedKey = Array.from(keys)[0];
    if (selectedKey && typeof selectedKey === "string") {
      selectModelMutation.mutate(selectedKey);
      setUser({
        ...user,
        selected_model: selectedKey,
      });
    }
  };

  // Find the default model from the models list
  const defaultModel = useMemo(() => {
    return models?.find((model) => model.is_default);
  }, [models]);

  // Group models by provider and sort
  const groupedModels = useMemo(() => {
    if (!models) return {};

    const grouped = models.reduce(
      (acc, model) => {
        const provider = model.model_provider || "Unknown";
        if (!acc[provider]) {
          acc[provider] = [];
        }
        acc[provider].push(model);
        return acc;
      },
      {} as Record<string, typeof models>,
    );

    // Sort providers alphabetically and models within each provider
    const sortedGrouped: Record<string, typeof models> = {};
    Object.keys(grouped)
      .sort()
      .forEach((provider) => {
        sortedGrouped[provider] = grouped[provider].sort((a, b) => {
          // First, prioritize selected model
          if (currentModel?.model_id === a.model_id) return -1;
          if (currentModel?.model_id === b.model_id) return 1;

          // Then, prioritize default model
          if (a.is_default && !b.is_default) return -1;
          if (b.is_default && !a.is_default) return 1;

          // Finally, sort alphabetically by name
          return a.name.localeCompare(b.name);
        });
      });

    return sortedGrouped;
  }, [models, currentModel]);

  const headingClasses =
    "flex w-full sticky top-0 pt-4 z-20 py-2 px-2 bg-zinc-800  text-zinc-200 text-xs font-medium capitalize";

  // Don't render the button if models are still loading or not available
  if (isLoading || !models || models.length === 0) {
    return null;
  }

  const selectedModelId =
    currentModel?.model_id || defaultModel?.model_id || "";

  return (
    <Select
      placeholder="Model"
      selectedKeys={selectedModelId ? new Set([selectedModelId]) : new Set()}
      onSelectionChange={handleSelectionChange}
      isDisabled={selectModelMutation.isPending}
      variant={"flat"}
      aria-label="Select AI Model"
      className="w-fit! max-w-none!"
      popoverProps={{
        classNames: {
          content: "min-w-[370px] max-w-none bg-zinc-800",
        },
      }}
      classNames={{
        trigger:
          "cursor-pointer bg-transparent transition hover:bg-zinc-800! !min-w-fit !w-auto !max-w-none whitespace-nowrap px-2 pr-9",
        value: "text-zinc-400! text-xs font-medium whitespace-nowrap !w-auto ",
        base: "!max-w-none !w-auto",
        innerWrapper: "!w-auto !max-w-none",
        mainWrapper: "!w-auto !max-w-none",
        selectorIcon: "text-zinc-500 h-4 w-4",
      }}
      scrollShadowProps={{
        isEnabled: false,
      }}
      startContent={
        <BubbleChatSparkIcon className="text-zinc-500" width={20} height={20} />
      }
      renderValue={(items) => {
        if (!items.length) return "Model";
        const item = items[0];
        const model = models?.find((m) => m.model_id === item.key);
        return <span>{model?.name || "Model"}</span>;
      }}
    >
      {Object.entries(groupedModels).map(([provider, providerModels]) => (
        <SelectSection
          key={provider}
          classNames={{
            heading: headingClasses,
          }}
          title={provider}
        >
          {providerModels?.map((model) => {
            const isFree = model.lowest_tier.toLowerCase() === "free";

            return (
              <SelectItem
                key={model.model_id}
                textValue={`${model.name}${model.is_default ? " (Default)" : ""}`}
                classNames={{
                  base: "py-2.5 px-2 data-[hover=true]:bg-zinc-700/50 gap-3 items-start rounded-xl",
                  title: "text-zinc-200",
                  description: "text-zinc-400 mt-1",
                }}
                startContent={
                  <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-zinc-700/50 shrink-0 mt-1">
                    {model.logo_url && (
                      <Image
                        src={model.logo_url}
                        alt={model.name}
                        height={40}
                        width={40}
                        className="h-5 w-5 object-contain"
                      />
                    )}
                  </div>
                }
              >
                <div className="flex flex-col gap-0.5 w-full min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-zinc-100 truncate">
                      {model.name}
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                      {model.is_default && (
                        <Chip
                          size="sm"
                          color="success"
                          variant="flat"
                          classNames={{ content: "text-xs px-1" }}
                        >
                          Default
                        </Chip>
                      )}
                      {!isFree && (
                        <Chip
                          size="sm"
                          color="warning"
                          variant="flat"
                          classNames={{ content: "text-xs px-1" }}
                        >
                          Pro
                        </Chip>
                      )}
                    </div>
                  </div>
                  {model.description && (
                    <p className="text-xs text-zinc-400 line-clamp-3 leading-relaxed">
                      {model.description}
                    </p>
                  )}
                  {model.provider_model_name && (
                    <code className="text-[10px] text-zinc-500 font-mono mt-0.5">
                      {model.provider_model_name}
                    </code>
                  )}
                </div>
              </SelectItem>
            );
          }) || []}
        </SelectSection>
      ))}
    </Select>
  );
};

export default ModelPickerButton;
