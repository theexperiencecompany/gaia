import { Chip } from "@heroui/chip";
import React from "react";

import { Lock } from "@/icons";

import { useToolsWithIntegrations } from "../../hooks/useToolsWithIntegrations";

interface CategoryIntegrationStatusProps {
  category: string;
}

export const CategoryIntegrationStatus: React.FC<
  CategoryIntegrationStatusProps
> = ({ category }) => {
  const { getToolsForCategory } = useToolsWithIntegrations();

  if (category === "all") return null;

  const categoryTools = getToolsForCategory(category);
  const lockedCount = categoryTools.filter((tool) => tool.isLocked).length;
  const totalCount = categoryTools.length;

  if (totalCount === 0) return null;

  if (lockedCount != 0)
    // All tools are locked (integration not connected)
    return (
      <Chip
        size="sm"
        variant="flat"
        color="danger"
        className="flex aspect-square w-fit items-center justify-center"
        radius="full"
      >
        <Lock className="h-3 w-3" />
      </Chip>
    );
};
