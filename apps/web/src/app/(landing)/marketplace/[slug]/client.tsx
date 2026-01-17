"use client";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import {
  CheckmarkCircle02Icon,
  ChevronLeft,
  ConnectIcon,
  Copy01Icon,
  DateTimeIcon,
  GitForkIcon,
  PackageOpenIcon,
  UserCircle02Icon,
  UserIcon,
} from "@/icons";
import { Avatar } from "@heroui/avatar";
import { Button } from "@heroui/button";
import { Card, CardBody, CardHeader } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { formatDistanceToNow } from "date-fns";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

interface IntegrationDetailClientProps {
  integration: PublicIntegrationResponse;
}

export function IntegrationDetailClient({
  integration,
}: IntegrationDetailClientProps) {
  const [isCloning, setIsCloning] = useState(false);
  const [isCloned, setIsCloned] = useState(false);

  const handleClone = async () => {
    if (isCloned) return;
    setIsCloning(true);
    try {
      const result = await integrationsApi.cloneIntegration(integration.slug);
      toast.success(`Successfully cloned ${result.name}!`);
      setIsCloned(true);
    } catch (error) {
      toast.error("Failed to clone integration. Please sign in first.");
    } finally {
      setIsCloning(false);
    }
  };

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    toast.success("Link copied to clipboard!");
  };

  return (
    <div className="min-h-screen pt-28 pb-16">
      <div className="mx-auto max-w-4xl px-6">
        <Link
          href="/marketplace"
          className="mb-8 inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-200"
        >
          <ChevronLeft width={16} height={16} />
          Back to Community
        </Link>

        {/* Header */}
        <div className="mb-8 flex items-start gap-6">
          <div className="flex h-20 w-20 items-center justify-center rounded-2xl">
            {getToolCategoryIcon(
              integration.integrationId,
              { size: 48, width: 48, height: 48, showBackground: false },
              integration.iconUrl || undefined
            ) || (
              <div className="flex h-20 w-20 aspect-square items-center justify-center rounded-xl bg-zinc-700 font-medium text-zinc-300">
                <PackageOpenIcon width={48} height={48} />
              </div>
            )}
          </div>

          <div className="flex-1">
            <div className="mb-2 flex items-center gap-3">
              <h1 className="text-3xl font-semibold text-white">
                {integration.name}
              </h1>
              <Chip size="sm" color="primary" variant="flat">
                {integration.category.slice(0, 1).toUpperCase() +
                  integration.category.slice(1)}
              </Chip>
            </div>

            <p className="mb-4 text-zinc-400">{integration.description}</p>

            <div className="flex items-center gap-4 text-sm text-zinc-500">
              <div className="flex items-center gap-2">
                {integration.creator?.picture ? (
                  <Avatar
                    src={integration.creator?.picture || undefined}
                    name={integration.creator?.name || undefined}
                    size="sm"
                    className="h-5 w-5"
                  />
                ) : (
                  <UserCircle02Icon width={20} height={20} />
                )}
                <span>by {integration.creator?.name || "Unknown"}</span>
              </div>
              <div className="flex items-center gap-1">
                <GitForkIcon width={18} height={18} />
                <span>{integration.cloneCount} clones</span>
              </div>
              <div className="flex items-center gap-1">
                <DateTimeIcon width={18} height={18} />
                <span>
                  Published{" "}
                  {formatDistanceToNow(new Date(integration.publishedAt), {
                    addSuffix: true,
                  })}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Action buttons */}
        <div className="mb-8 flex gap-3">
          <Button
            color={isCloned ? "success" : "primary"}
            onPress={handleClone}
            isLoading={isCloning}
            isDisabled={isCloned}
            startContent={
              isCloned ? (
                <CheckmarkCircle02Icon width={20} height={20} />
              ) : (
                <ConnectIcon width={20} height={20} />
              )
            }
          >
            {isCloned ? "Added to your GAIA" : "Add to your GAIA"}
          </Button>
          <Button
            variant="flat"
            onPress={handleShare}
            startContent={<Copy01Icon width={20} height={20} />}
          >
            Share
          </Button>
        </div>

        <Card className="mb-6">
          <CardHeader>
            <h2 className="text-lg font-normal">
              Available Tools ({integration.toolCount})
            </h2>
          </CardHeader>
          <CardBody className="grid grid-cols-2 gap-4">
            {integration.tools.map((tool) => (
              <div key={tool.name} className="bg-zinc-800 p-3 rounded-xl">
                <p className="font-medium text-zinc-200">
                  {tool.name
                    .replace(/_/g, " ")
                    .replace(/-/g, " ")
                    .replace(/\b\w/g, (c) => c.toUpperCase())}
                </p>
                {tool.description && (
                  <p className="text-sm text-zinc-400">{tool.description}</p>
                )}
              </div>
            ))}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
