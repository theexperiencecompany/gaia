"use client";

import { Card, CardBody, CardFooter, CardHeader } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Avatar } from "@heroui/avatar";
import Link from "next/link";
import type { CommunityIntegration } from "../types";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { formatDistanceToNow } from "date-fns";

interface PublicIntegrationCardProps {
  integration: CommunityIntegration;
}

export const PublicIntegrationCard: React.FC<PublicIntegrationCardProps> = ({
  integration,
}) => {
  return (
    <Link href={`/integrations/${integration.slug}`}>
      <Card
        className="h-full transition-all hover:scale-[1.02] hover:shadow-lg"
        isPressable
      >
        <CardHeader className="flex gap-3">
          {/* Integration icon */}
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-800">
            {getToolCategoryIcon(
              integration.integrationId,
              { size: 28, showBackground: false },
              integration.iconUrl || undefined,
            )}
          </div>

          <div className="flex flex-1 flex-col">
            <p className="text-md font-semibold text-zinc-100">
              {integration.name}
            </p>
            <Chip size="sm" variant="flat" color="primary" className="w-fit">
              {integration.category}
            </Chip>
          </div>
        </CardHeader>

        <CardBody className="pt-0">
          <p className="line-clamp-2 text-sm text-zinc-400">
            {integration.description}
          </p>

          {/* Tools preview */}
          <div className="mt-3 flex flex-wrap gap-1">
            {integration.tools.slice(0, 3).map((tool) => (
              <Chip
                key={tool.name}
                size="sm"
                variant="bordered"
                className="text-xs"
              >
                {tool.name}
              </Chip>
            ))}
            {integration.tools.length > 3 && (
              <Chip size="sm" variant="bordered" className="text-xs">
                +{integration.tools.length - 3} more
              </Chip>
            )}
          </div>
        </CardBody>

        <CardFooter className="flex justify-between text-xs text-zinc-500">
          <div className="flex items-center gap-2">
            <Avatar
              src={integration.creator.picture || undefined}
              name={integration.creator.name}
              size="sm"
              className="h-5 w-5"
            />
            <span>{integration.creator.name}</span>
          </div>

          <div className="flex items-center gap-3">
            <span>{integration.cloneCount} clones</span>
            <span>
              {formatDistanceToNow(new Date(integration.publishedAt), {
                addSuffix: true,
              })}
            </span>
          </div>
        </CardFooter>
      </Card>
    </Link>
  );
};
