import { Chip } from "@heroui/chip";
import { SquareLock01Icon } from "@icons";
import type React from "react";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

interface CategoryIntegrationStatusProps {
  category: string;
  // Number of locked tools shown under this category in the dropdown.
  lockedCount: number;
}

export const CategoryIntegrationStatus: React.FC<
  CategoryIntegrationStatusProps
> = ({ category, lockedCount }) => {
  const { integrations } = useIntegrations();

  if (category === "all") return null;

  // Check integration status using category as integration ID
  const integration = integrations?.find(
    (i) => i.id.toLowerCase() === category.toLowerCase(),
  );

  // Show green dot if connected
  if (integration?.status === "connected")
    return <span className="h-1.5 w-1.5 rounded-full bg-green-500" />;

  // Show orange dot if created (added but not connected)
  if (integration?.status === "created")
    return <span className="h-1.5 w-1.5 rounded-full bg-orange-500" />;

  // Show lock if tools are locked (integration not connected)
  if (lockedCount !== 0)
    return (
      <Chip
        size="sm"
        variant="flat"
        color="danger"
        className="flex aspect-square w-fit items-center justify-center"
        radius="full"
      >
        <SquareLock01Icon className="h-3 w-3" />
      </Chip>
    );

  return null;
};
