import { Chip } from "@heroui/chip";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

export default function IntegrationStrip({
  integrations,
}: {
  integrations: { id: string; label: string }[];
}) {
  return (
    <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
      {integrations.map((integration) => (
        <Chip
          key={integration.id}
          variant="flat"
          size="sm"
          className="bg-zinc-800 text-zinc-300"
          startContent={
            <span className="mx-1 flex items-center">
              {getToolCategoryIcon(integration.id, {
                width: 18,
                height: 18,
                showBackground: false,
              })}
            </span>
          }
        >
          {integration.label}
        </Chip>
      ))}
    </div>
  );
}
