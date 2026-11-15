import { Chip } from "@heroui/react";
import type { ImageProps } from "next/image";
import { toneVariants } from "@/components/shared/tone";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

export default function IntegrationStrip({
  integrations,
  loading,
}: {
  integrations: { id: string; label: string }[];
  loading?: ImageProps["loading"];
}) {
  return (
    <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
      {integrations.map((integration) => (
        <Chip
          key={integration.id}
          variant="secondary"
          size="sm"
          className={toneVariants({ tone: "dim" })}
        >
          <span className="mx-1 flex items-center">
            {getToolCategoryIcon(integration.id, {
              width: 18,
              height: 18,
              showBackground: false,
              loading,
            })}
          </span>
          <Chip.Label>{integration.label}</Chip.Label>
        </Chip>
      ))}
    </div>
  );
}
