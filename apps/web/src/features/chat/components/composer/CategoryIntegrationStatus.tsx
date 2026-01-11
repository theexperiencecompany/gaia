import { Chip } from "@heroui/chip";
import type React from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { SquareLock01Icon } from "@/icons";

import { useToolsWithIntegrations } from "../../hooks/useToolsWithIntegrations";

interface CategoryIntegrationStatusProps {
  category: string;
}

export const CategoryIntegrationStatus: React.FC<
  CategoryIntegrationStatusProps
> = ({ category }) => {
  const { getToolsForCategory } = useToolsWithIntegrations();
  const { integrations } = useIntegrations();

  if (category === "all") return null;

  const categoryTools = getToolsForCategory(category);
  const lockedCount = categoryTools.filter((tool) => tool.isLocked).length;
  const totalCount = categoryTools.length;

  if (totalCount === 0) return null;

  // Check if any tool requires an integration and get its status
  const toolWithIntegration = categoryTools.find(
    (tool) => tool.integration?.requiredIntegration,
  );
  const integration = integrations?.find(
    (i) => i.id === toolWithIntegration?.integration?.requiredIntegration,
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
