"use client";

import { Avatar } from "@heroui/avatar";
import { Card, CardBody, CardHeader } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import Image from "next/image";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { RaisedButton } from "@/components";
import { wallpapers } from "@/config/wallpapers";
import { useLoginModalActions } from "@/features/auth/hooks/useLoginModal";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import ShareButton from "@/features/use-cases/components/ShareButton";
import {
  DateTimeIcon,
  GitForkIcon,
  LayersIcon,
  PackageOpenIcon,
  UserCircle02Icon,
} from "@/icons";
import { useUserStore } from "@/stores/userStore";

interface IntegrationDetailClientProps {
  integration: PublicIntegrationResponse;
}

export function IntegrationDetailClient({
  integration,
}: IntegrationDetailClientProps) {
  const [isAdding, setIsAdding] = useState(false);
  const [isAdded, setIsAdded] = useState(false);

  // Check if user is authenticated (has email in store)
  const userEmail = useUserStore((state) => state.email);
  const isAuthenticated = Boolean(userEmail);

  // Login modal controls
  const { openModal: openLoginModal } = useLoginModalActions();

  // Fetch user's integrations (only when authenticated) to check for duplicates
  const { data: userIntegrationsData } = useQuery({
    queryKey: ["integrations", "user"],
    queryFn: integrationsApi.getUserIntegrations,
    enabled: isAuthenticated,
  });

  // Check if user already has this integration (match by integrationId)
  const alreadyHasIntegration = useMemo(() => {
    if (!userIntegrationsData?.integrations) return false;
    return userIntegrationsData.integrations.some(
      (ui) => ui.integration.integrationId === integration.integrationId,
    );
  }, [userIntegrationsData, integration.integrationId]);

  const handleAdd = async () => {
    // Already added in this session
    if (isAdded) return;

    // Check authentication first - open login modal if not authenticated
    if (!isAuthenticated) {
      openLoginModal();
      return;
    }

    // Deduplication check (redundant safety, button should be disabled)
    if (alreadyHasIntegration) {
      toast.info("You already have this integration in your GAIA");
      return;
    }

    setIsAdding(true);
    const loadingToast = toast.loading("Adding integration...");

    try {
      const result = await integrationsApi.addIntegration(
        integration.integrationId,
      );

      // If redirecting to OAuth, dismiss the loading toast
      // The browser will navigate away
      if (result.status === "redirecting") {
        toast.dismiss(loadingToast);
        return;
      }

      // Integration connected successfully
      toast.dismiss(loadingToast);
      toast.success(`Successfully added ${result.name}!`);
      setIsAdded(true);
    } catch {
      toast.dismiss(loadingToast);
      toast.error("Failed to add integration.");
    } finally {
      setIsAdding(false);
    }
  };

  // Prepare breadcrumbs matching use-case page format
  const breadcrumbs = [
    { label: "Home", href: "/" },
    { label: "Marketplace", href: "/marketplace" },
    {
      label:
        integration.category.charAt(0).toUpperCase() +
        integration.category.slice(1),
    },
  ];

  return (
    <div className="relative">
      <Image
        src={wallpapers.integration.webp}
        alt="GAIA Marketplace Wallpaper"
        priority
        fill
        className="mask-[linear-gradient(to_bottom,transparent_0%,black_20%,black_80%,transparent_100%)] object-cover opacity-15 z-0 w-screen fixed h-screen left-0 top-0 max-h-screen"
      />
      <div className="flex min-h-screen w-screen justify-center overflow-y-auto pt-34 pb-20 relative z-1">
        <div className="container mx-auto w-full max-w-5xl space-y-5">
          {/* Breadcrumbs */}
          <div className="mb-3 text-sm text-zinc-500">
            <Breadcrumbs>
              {breadcrumbs.map((crumb) => (
                <BreadcrumbItem key={crumb.label} href={crumb.href}>
                  {crumb.label}
                </BreadcrumbItem>
              ))}
            </Breadcrumbs>
          </div>

          {/* Header with title and actions */}
          <div className="flex w-full items-start justify-between gap-2">
            <div className="flex-1 space-y-2">
              <div className="flex items-center gap-4">
                <div className="flex h-16 w-16 items-center justify-center">
                  {getToolCategoryIcon(
                    integration.integrationId,
                    { size: 48, width: 48, height: 48, showBackground: false },
                    integration.iconUrl || undefined,
                  ) || (
                    <div className="flex h-16 w-16 aspect-square items-center justify-center rounded-xl bg-zinc-700 font-medium text-zinc-300">
                      <PackageOpenIcon width={48} height={48} />
                    </div>
                  )}
                </div>
                <h1 className="text-5xl font-normal text-foreground">
                  {integration.name}
                </h1>
              </div>
              {integration.description && (
                <p className="text-lg leading-relaxed text-zinc-500 max-w-5xl mt-6">
                  {integration.description}
                </p>
              )}
            </div>

            <div className="flex items-center gap-3">
              <ShareButton
                id={integration.integrationId}
                basePath="/marketplace"
              />
              <RaisedButton
                color="#00bbff"
                className="shrink-0 text-black!"
                onClick={handleAdd}
                disabled={isAdding || isAdded || alreadyHasIntegration}
              >
                {isAdded || alreadyHasIntegration
                  ? "Already in your GAIA"
                  : isAdding
                    ? "Adding..."
                    : "Add to your GAIA"}
              </RaisedButton>
            </div>
          </div>

          <div className="flex flex-wrap items-start gap-4">
            <div className="flex items-center gap-2 rounded-xl bg-zinc-900/50 backdrop-blur-md px-4 py-3">
              <LayersIcon width={24} height={24} className="text-zinc-400" />
              <div>
                <div className="text-xs text-zinc-500">Category</div>
                <div className="text-sm text-zinc-300">
                  {integration.category.charAt(0).toUpperCase() +
                    integration.category.slice(1)}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-xl bg-zinc-900/50 backdrop-blur-md px-4 py-3">
              {integration.creator?.picture ? (
                <Avatar
                  src={integration.creator?.picture || undefined}
                  name={integration.creator?.name || undefined}
                  size="sm"
                  className="h-6 w-6"
                />
              ) : (
                <UserCircle02Icon
                  width={24}
                  height={24}
                  className="text-zinc-400"
                />
              )}
              <div>
                <div className="text-xs text-zinc-500">Created by</div>
                <div className="text-sm text-zinc-300">
                  {integration.creator?.name || "Unknown"}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-xl bg-zinc-900/50 backdrop-blur-md px-4 py-3">
              <GitForkIcon width={24} height={24} className="text-zinc-400" />
              <div>
                <div className="text-xs text-zinc-500">Clones</div>
                <div className="text-sm text-zinc-300">
                  {integration.cloneCount}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-xl bg-zinc-900/50 backdrop-blur-md px-4 py-3">
              <DateTimeIcon width={24} height={24} className="text-zinc-400" />
              <div>
                <div className="text-xs text-zinc-500">Published</div>
                <div className="text-sm text-zinc-300">
                  {formatDistanceToNow(new Date(integration.publishedAt), {
                    addSuffix: true,
                  })}
                </div>
              </div>
            </div>
          </div>

          <Card className="bg-zinc-900/50 backdrop-blur-md outline-0 border-none rounded-3xl">
            <CardHeader>
              <h2 className="text-lg font-normal">
                Available Tools ({integration.toolCount})
              </h2>
            </CardHeader>
            <CardBody className="grid grid-cols-2 gap-4">
              {integration.tools.map((tool) => (
                <div key={tool.name} className="bg-zinc-800/50 p-3 rounded-xl">
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
    </div>
  );
}
