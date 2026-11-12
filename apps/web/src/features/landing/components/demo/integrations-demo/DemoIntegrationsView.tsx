"use client";

import { Button, ButtonGroup, Chip, InputGroup } from "@heroui/react";
import {
  ArrowRight02Icon,
  Cancel01Icon,
  ConnectIcon,
  GlobalIcon,
  InternetIcon,
  Search01Icon,
  Share08Icon,
  Unlink04Icon,
  ZapIcon,
} from "@icons";
import { useEffect, useMemo, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  CATEGORY_LABELS,
  DEMO_CATEGORIES,
  DEMO_INTEGRATIONS,
  type DemoIntegration,
} from "./integrationsDemoConstants";

function DemoIntegrationRow({
  integration,
  onClick,
}: {
  integration: DemoIntegration;
  onClick: (id: string) => void;
}) {
  const isConnected = integration.status === "connected";
  const isPublic = integration.isPublic;

  return (
    <div className="flex min-h-16 items-center gap-4 overflow-hidden rounded-2xl bg-zinc-800/0 px-4 py-3 hover:bg-zinc-800 transition-colors duration-200">
      <button
        type="button"
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-4 text-left"
        onClick={() => onClick(integration.id)}
      >
        <div className="shrink-0">
          {getToolCategoryIcon(integration.id, {
            size: 32,
            width: 32,
            height: 32,
            showBackground: false,
          })}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <span className="font-medium">{integration.name}</span>
            {isPublic && (
              <Chip size="sm" variant="soft" color="accent">
                Community
              </Chip>
            )}
          </div>
          <div className="truncate text-sm font-light text-zinc-400">
            {integration.description}
          </div>
        </div>
      </button>
      <div className="shrink-0">
        {isConnected ? (
          <Chip size="sm" variant="soft" color="success">
            Connected
          </Chip>
        ) : (
          <GaiaButton
            variant="accent-soft"
            size="sm"
            className="text-sm text-primary"
          >
            Connect
          </GaiaButton>
        )}
      </div>
    </div>
  );
}

function DemoIntegrationSidebar({
  integration,
  onClose,
}: {
  integration: DemoIntegration;
  onClose: () => void;
}) {
  const isConnected = integration.status === "connected";
  const isPublic = integration.isPublic;
  const isCustom = integration.source === "custom";

  // Count how many action buttons will show to decide icon-only vs text
  const buttonCount = [
    isConnected, // Disconnect
    isConnected && isPublic, // View on Marketplace
    isConnected && isCustom && !isPublic, // Publish
    isConnected && isPublic, // Share
  ].filter(Boolean).length;
  const useIconOnly = buttonCount >= 3;

  return (
    <div
      className="flex h-full w-[300px] shrink-0 flex-col border-l border-zinc-800"
      style={{ backgroundColor: "#141414" }}
    >
      {/* Close button */}
      <div className="flex w-full items-end justify-end px-6 pt-4 pb-0">
        <Button
          onPress={onClose}
          variant="ghost"
          isIconOnly
          size="sm"
          aria-label="Close"
        >
          <Cancel01Icon className="size-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-5">
        <div className="flex flex-col gap-3">
          {/* Icon */}
          <div className="w-fit">
            {getToolCategoryIcon(integration.id, {
              size: 40,
              width: 40,
              height: 40,
              showBackground: false,
            })}
          </div>

          {/* Status chips */}
          <div className="flex items-center gap-2">
            {isConnected && (
              <Chip size="sm" variant="soft" color="success">
                Connected
              </Chip>
            )}
            {!isConnected && (
              <Chip size="sm" variant="soft" color="default">
                Not Connected
              </Chip>
            )}
            {isCustom && (
              <Chip
                size="sm"
                variant="soft"
                className="text-xs font-light text-zinc-400"
              >
                Custom
              </Chip>
            )}
          </div>

          {/* Title */}
          <h1 className="text-2xl font-semibold text-zinc-100">
            {integration.name}
          </h1>

          {/* Description */}
          <p className="text-sm leading-relaxed font-light text-zinc-400">
            {integration.description}
          </p>

          {/* Action buttons */}
          {!isConnected ? (
            <Button className="w-full font-medium" size="md" variant="primary">
              Connect
            </Button>
          ) : (
            <ButtonGroup variant="secondary" className="w-full" fullWidth>
              <Button
                isIconOnly={useIconOnly}
                className="w-full"
                aria-label="Disconnect"
                variant="danger"
              >
                <Unlink04Icon width={18} height={18} />
                {!useIconOnly && "Disconnect"}
              </Button>
              {isPublic && (
                <Button
                  isIconOnly={useIconOnly}
                  className="w-full"
                  aria-label="View on Marketplace"
                  variant="primary"
                >
                  <InternetIcon width={18} height={18} />
                  {!useIconOnly && "View"}
                </Button>
              )}
              {isCustom && !isPublic && (
                <Button
                  isIconOnly={useIconOnly}
                  className="w-full"
                  aria-label="Publish"
                  variant="primary"
                >
                  <GlobalIcon width={18} height={18} />
                  {!useIconOnly && "Publish"}
                </Button>
              )}
              {isPublic && (
                <GaiaButton
                  variant="default-solid"
                  isIconOnly={useIconOnly}
                  className="w-full"
                  aria-label="Share"
                >
                  <Share08Icon width={18} height={18} />
                  {!useIconOnly && "Share"}
                </GaiaButton>
              )}
            </ButtonGroup>
          )}

          {/* Available Tools */}
          {integration.tools && integration.tools.length > 0 && (
            <div className="mt-2">
              <h2 className="mb-2 text-xs font-medium text-zinc-400">
                Available Tools ({integration.tools.length})
              </h2>
              <div className="flex flex-wrap gap-2">
                {integration.tools.map((tool) => (
                  <Chip
                    key={tool}
                    variant="soft"
                    size="sm"
                    className={shapeVariants({
                      shape: "pill",
                      className: "font-light text-zinc-300",
                    })}
                  >
                    {tool}
                  </Chip>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface DemoIntegrationsViewProps {
  externalSelectedId?: string | null;
  onSelectionChange?: (id: string | null) => void;
}

export default function DemoIntegrationsView({
  externalSelectedId,
  onSelectionChange,
}: DemoIntegrationsViewProps = {}) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedIntegration, setSelectedIntegration] =
    useState<DemoIntegration | null>(null);

  // Sync from external selection (e.g. left sidebar click)
  useEffect(() => {
    if (externalSelectedId !== undefined) {
      const integration =
        externalSelectedId === null
          ? null
          : (DEMO_INTEGRATIONS.find((i) => i.id === externalSelectedId) ??
            null);
      setSelectedIntegration(integration);
    }
  }, [externalSelectedId]);

  const filteredIntegrations = useMemo(() => {
    let result = DEMO_INTEGRATIONS;

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (i) =>
          i.name.toLowerCase().includes(query) ||
          i.description.toLowerCase().includes(query),
      );
    }

    if (selectedCategory !== "all") {
      result = result.filter((i) => i.category === selectedCategory);
    }

    return result;
  }, [searchQuery, selectedCategory]);

  const featuredIntegrations = useMemo(
    () => filteredIntegrations.filter((i) => i.isFeatured),
    [filteredIntegrations],
  );

  const integrationsByCategory = useMemo(() => {
    const grouped: Record<string, DemoIntegration[]> = {};
    for (const cat of DEMO_CATEGORIES.filter((c) => c !== "all")) {
      const items = filteredIntegrations
        .filter((i) => i.category === cat)
        .sort((a, b) => {
          if (a.status === "connected" && b.status !== "connected") return -1;
          if (a.status !== "connected" && b.status === "connected") return 1;
          return a.name.localeCompare(b.name);
        });
      if (items.length > 0) grouped[cat] = items;
    }
    return grouped;
  }, [filteredIntegrations]);

  const handleIntegrationClick = (id: string) => {
    const integration = DEMO_INTEGRATIONS.find((i) => i.id === id);
    if (integration) {
      setSelectedIntegration(integration);
      onSelectionChange?.(id);
    }
  };

  return (
    <div className="flex h-full w-full">
      {/* Main content */}
      <div className="min-w-0 flex-1 overflow-y-auto p-6">
        {/* Community Banner */}
        <div className="mb-6">
          <div className="relative overflow-hidden rounded-3xl bg-zinc-800/50">
            <div className="relative z-10 flex items-center justify-between gap-6 p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/20">
                  <ConnectIcon className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <h3 className="text-lg font-medium text-white">
                    Integration Marketplace
                  </h3>
                  <p className="text-sm text-zinc-400">
                    Discover community integrations or create your own custom
                    tools.
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 gap-3">
                <Button variant="tertiary" size="sm">
                  Browse Marketplace
                  <ArrowRight02Icon className="h-4 w-4" />
                </Button>
                <Button size="sm" variant="primary">
                  <ZapIcon className="h-4 w-4" />
                  Create Custom
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* Search */}
        <div className="mb-6">
          <InputGroup className="bg-zinc-800/50 border-zinc-700">
            <InputGroup.Prefix>
              <Search01Icon className="text-zinc-500" width={18} height={18} />
            </InputGroup.Prefix>
            <InputGroup.Input
              placeholder="Search integrations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <InputGroup.Suffix>
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => setSearchQuery("")}
                className="cursor-pointer text-zinc-500 hover:text-zinc-300"
              >
                <Cancel01Icon width={18} height={18} />
              </button>
            </InputGroup.Suffix>
          </InputGroup>
        </div>

        {/* Category Filter */}
        <div className="mb-6 flex flex-wrap gap-2">
          {DEMO_CATEGORIES.map((cat) => (
            <Chip
              key={cat}
              variant={selectedCategory === cat ? "primary" : "soft"}
              color={selectedCategory === cat ? "accent" : "default"}
              className="cursor-pointer select-none"
              onClick={() => setSelectedCategory(cat)}
            >
              {CATEGORY_LABELS[cat] || cat}
            </Chip>
          ))}
        </div>

        {/* Integrations List */}
        {selectedCategory === "all" ? (
          <>
            {/* Featured */}
            {featuredIntegrations.length > 0 && !searchQuery && (
              <div className="mb-8">
                <div className="mb-4 flex items-center gap-3 pl-4">
                  <h2 className="text-base font-semibold">Featured</h2>
                  <Chip size="sm" variant="soft" color="accent">
                    {featuredIntegrations.length}
                  </Chip>
                </div>
                <div className="flex flex-col gap-2">
                  {featuredIntegrations.map((integration) => (
                    <DemoIntegrationRow
                      key={integration.id}
                      integration={integration}
                      onClick={handleIntegrationClick}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* By Category */}
            {Object.entries(integrationsByCategory).map(([category, items]) => (
              <div key={category} className="mb-8">
                <div className="mb-4 flex items-center gap-3 pl-4">
                  <h2 className="text-base font-semibold">
                    {CATEGORY_LABELS[category] || category}
                  </h2>
                  <Chip size="sm" variant="soft" color="default">
                    {items.length}
                  </Chip>
                </div>
                <div className="flex flex-col gap-2">
                  {items.map((integration) => (
                    <DemoIntegrationRow
                      key={integration.id}
                      integration={integration}
                      onClick={handleIntegrationClick}
                    />
                  ))}
                </div>
              </div>
            ))}
          </>
        ) : (
          <div className="mb-8">
            <div className="mb-4 flex items-center gap-3 pl-4">
              <h2 className="text-base font-semibold">
                {CATEGORY_LABELS[selectedCategory] || selectedCategory}
              </h2>
              <Chip size="sm" variant="soft" color="default">
                {filteredIntegrations.length}
              </Chip>
            </div>
            <div className="flex flex-col gap-2">
              {filteredIntegrations.map((integration) => (
                <DemoIntegrationRow
                  key={integration.id}
                  integration={integration}
                  onClick={handleIntegrationClick}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right Sidebar */}
      {selectedIntegration && (
        <DemoIntegrationSidebar
          integration={selectedIntegration}
          onClose={() => {
            setSelectedIntegration(null);
            onSelectionChange?.(null);
          }}
        />
      )}
    </div>
  );
}
