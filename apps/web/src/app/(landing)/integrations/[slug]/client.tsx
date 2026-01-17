"use client";

import { useState } from "react";
import { Button } from "@heroui/button";
import { Card, CardBody, CardHeader } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Avatar } from "@heroui/avatar";
import { toast } from "sonner";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";

import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { ArrowLeft01Icon, Copy01Icon, Download01Icon, CheckmarkCircle02Icon } from "@/icons";

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
        {/* Back link */}
        <Link
          href="/integrations"
          className="mb-8 inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-200"
        >
          <ArrowLeft01Icon width={16} height={16} />
          Back to Community
        </Link>

        {/* Header */}
        <div className="mb-8 flex items-start gap-6">
          <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-zinc-800">
            {getToolCategoryIcon(
              integration.integrationId,
              { size: 48, showBackground: false },
              integration.iconUrl || undefined
            )}
          </div>

          <div className="flex-1">
            <div className="mb-2 flex items-center gap-3">
              <h1 className="text-3xl font-semibold text-white">
                {integration.name}
              </h1>
              <Chip size="sm" color="primary" variant="flat">
                {integration.category}
              </Chip>
            </div>

            <p className="mb-4 text-zinc-400">{integration.description}</p>

            <div className="flex items-center gap-4 text-sm text-zinc-500">
              <div className="flex items-center gap-2">
                <Avatar
                  src={integration.creator?.picture || undefined}
                  name={integration.creator?.name || undefined}
                  size="sm"
                  className="h-5 w-5"
                />
                <span>by {integration.creator?.name || "Unknown"}</span>
              </div>
              <span>{integration.cloneCount} clones</span>
              <span>
                Published{" "}
                {formatDistanceToNow(new Date(integration.publishedAt), {
                  addSuffix: true,
                })}
              </span>
            </div>
          </div>
        </div>

        {/* Action buttons */}
        <div className="mb-8 flex gap-3">
          <Button
            color={isCloned ? "success" : "primary"}
            size="lg"
            onPress={handleClone}
            isLoading={isCloning}
            isDisabled={isCloned}
            startContent={
              isCloned ? (
                <CheckmarkCircle02Icon width={20} height={20} />
              ) : (
                <Download01Icon width={20} height={20} />
              )
            }
          >
            {isCloned ? "Added to Workspace" : "Add to Workspace"}
          </Button>
          <Button
            variant="flat"
            size="lg"
            onPress={handleShare}
            startContent={<Copy01Icon width={20} height={20} />}
          >
            Share
          </Button>
        </div>

        {/* Tools section */}
        <Card className="mb-6">
          <CardHeader>
            <h2 className="text-lg font-semibold">
              Available Tools ({integration.toolCount})
            </h2>
          </CardHeader>
          <CardBody>
            <div className="space-y-3">
              {integration.tools.map((tool) => (
                <div key={tool.name} className="rounded-lg bg-zinc-900 p-3">
                  <p className="font-medium text-zinc-200">{tool.name}</p>
                  {tool.description && (
                    <p className="mt-1 text-sm text-zinc-400">
                      {tool.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

        {/* Connection info */}
        {integration.mcpConfig && (
          <Card>
            <CardHeader>
              <h2 className="text-lg font-semibold">Connection Details</h2>
            </CardHeader>
            <CardBody>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Server</span>
                  <span className="font-mono text-xs text-zinc-200">
                    {new URL(integration.mcpConfig.serverUrl).hostname}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Authentication</span>
                  <Chip size="sm" variant="flat">
                    {integration.mcpConfig.requiresAuth
                      ? integration.mcpConfig.authType || "OAuth"
                      : "None"}
                  </Chip>
                </div>
              </div>
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}
