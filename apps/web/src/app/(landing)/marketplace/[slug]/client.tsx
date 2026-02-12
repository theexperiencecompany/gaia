"use client";

import { Avatar } from "@heroui/avatar";
import { Card, CardBody, CardHeader } from "@heroui/card";
import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";
import { Spinner } from "@heroui/spinner";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { RaisedButton } from "@/components";
import { wallpapers } from "@/config/wallpapers";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import ShareButton from "@/features/use-cases/components/ShareButton";
import {
  DateTimeIcon,
  GitForkIcon,
  LayersIcon,
  PackageOpenIcon,
  UserCircle02Icon,
} from "@/icons";

interface IntegrationDetailClientProps {
  integration: PublicIntegrationResponse;
}

export function IntegrationDetailClient({
  integration,
}: IntegrationDetailClientProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [isAdding, setIsAdding] = useState(false);
  const [isAdded, setIsAdded] = useState(false);
  const [bearerModalOpen, setBearerModalOpen] = useState(false);

  // Auth check
  const { isAuthenticated, openLoginModal } = useAuth();

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

      // If redirecting to OAuth, update toast but keep loading state
      // The browser will navigate away, so we don't dismiss
      if (result.status === "redirecting") {
        toast.loading("Redirecting to authorize...", { id: loadingToast });
        return;
      }

      // Bearer token required - show modal
      if (result.status === "bearer_required") {
        toast.dismiss(loadingToast);
        setBearerModalOpen(true);
        setIsAdding(false);
        return;
      }

      // Integration connected successfully
      toast.dismiss(loadingToast);
      toast.success(`Successfully added ${result.name}!`);
      setIsAdded(true);

      setTimeout(() => {
        router.push(
          `/integrations?id=${integration.integrationId}&refresh=true`,
        );
      }, 1000);
    } catch {
      toast.dismiss(loadingToast);
      toast.error("Failed to add integration.");
      setIsAdding(false);
    }
  };

  const handleBearerSubmit = async (_id: string, token: string) => {
    const loadingToast = toast.loading("Connecting...");
    try {
      const result = await integrationsApi.addIntegration(
        integration.integrationId,
        token,
      );
      if (result.status === "connected") {
        toast.success(`Successfully added ${integration.name}!`, {
          id: loadingToast,
        });
        setIsAdded(true);
        queryClient.invalidateQueries({ queryKey: ["integrations"] });
        setTimeout(() => {
          router.push(
            `/integrations?id=${integration.integrationId}&refresh=true`,
          );
        }, 1000);
      } else {
        toast.error(result.message || "Connection failed", {
          id: loadingToast,
        });
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Connection failed",
        { id: loadingToast },
      );
      throw error;
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
                <div className="flex max-w-12 min-w-12 min-h-12 max-h-12 items-center justify-center rounded-lg overflow-hidden">
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
                <h1 className="text-5xl font-medium text-foreground">
                  {integration.name}
                </h1>
              </div>
              <p className="text-lg leading-relaxed text-zinc-500 max-w-5xl mt-6">
                {integration.description ||
                  `Connect ${integration.name} to your AI assistant and automate your ${integration.category} workflows.`}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <ShareButton
                id={integration.integrationId}
                basePath="/marketplace"
              />
              {alreadyHasIntegration ? (
                <RaisedButton
                  color="#00bbff"
                  className="shrink-0 text-black!"
                  onClick={() =>
                    router.push(`/integrations?id=${integration.integrationId}`)
                  }
                >
                  View Integration
                </RaisedButton>
              ) : (
                <RaisedButton
                  color="#00bbff"
                  className="shrink-0 text-black!"
                  onClick={handleAdd}
                  disabled={isAdding || isAdded}
                >
                  {isAdding ? (
                    <>
                      <Spinner size="sm" color="default" />
                      Adding...
                    </>
                  ) : isAdded ? (
                    "Added to your GAIA"
                  ) : (
                    "Add to your GAIA"
                  )}
                </RaisedButton>
              )}
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
                <div className="text-xs text-zinc-500">Users</div>
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
            {integration.tools && integration.tools.length > 0 && (
              <CardHeader>
                <h2 className="text-lg font-normal">
                  Available Tools ({integration.toolCount})
                </h2>
              </CardHeader>
            )}
            <CardBody>
              {integration.tools && integration.tools.length > 0 ? (
                <div className="grid grid-cols-2 gap-4">
                  {integration.tools.map((tool) => (
                    <div
                      key={tool.name}
                      className="bg-zinc-800/50 p-3 rounded-xl"
                    >
                      <p className="font-medium text-zinc-200">
                        {tool.name
                          .replace(/_/g, " ")
                          .replace(/-/g, " ")
                          .replace(/\b\w/g, (c) => c.toUpperCase())}
                      </p>
                      {tool.description && (
                        <p className="text-sm text-zinc-400">
                          {tool.description}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <PackageOpenIcon
                    width={48}
                    height={48}
                    className="text-foreground-300 mb-4"
                  />
                  <p className="text-foreground-400 max-w-md text-sm">
                    This integration might not have tools available yet because
                    no one has connected to it, or the tools haven&apos;t been
                    synced. Try refreshing the page.
                  </p>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <BearerTokenModal
        isOpen={bearerModalOpen}
        onClose={() => setBearerModalOpen(false)}
        integrationId={integration.integrationId}
        integrationName={integration.name}
        onSubmit={handleBearerSubmit}
      />
    </div>
  );
}
