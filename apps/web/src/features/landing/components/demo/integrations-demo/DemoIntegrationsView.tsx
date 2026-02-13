"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { useMemo, useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { Search01Icon, Unlink04Icon } from "@/icons";
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

  return (
    <div
      className="flex min-h-16 cursor-pointer items-center gap-4 overflow-hidden rounded-2xl bg-zinc-800/0 px-4 py-3 hover:bg-zinc-800 transition-all duration-200"
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
        <div className="font-medium">{integration.name}</div>
        <div className="truncate text-sm font-light text-zinc-400">
          {integration.description}
        </div>
      </div>
      <div className="shrink-0">
        {isConnected ? (
          <Chip size="sm" variant="flat" color="success">
            Connected
          </Chip>
        ) : (
          <Button
            variant="flat"
            color="primary"
            className="text-sm text-primary"
          >
            Connect
          </Button>
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

  return (
    <div
      className="flex h-full w-[300px] shrink-0 flex-col border-l border-zinc-800 overflow-y-auto"
      style={{ backgroundColor: "#141414" }}
    >
      <div className="px-6 pt-4 pb-0 flex justify-end">
        <Button
          isIconOnly
          size="sm"
          variant="light"
          onPress={onClose}
          className="text-zinc-400"
        >
          ✕
        </Button>
      </div>
      <div className="px-6 pb-6 flex flex-col gap-4">
        <div className="flex items-center gap-3">
          {getToolCategoryIcon(integration.id, {
            size: 40,
            width: 40,
            height: 40,
          })}
        </div>

        {isConnected && (
          <Chip size="sm" variant="flat" color="success">
            Connected
          </Chip>
        )}

        <h2 className="text-2xl font-semibold">{integration.name}</h2>
        <p className="text-sm font-light text-zinc-400">
          {integration.description}
        </p>

        {isConnected ? (
          <Button
            variant="flat"
            color="danger"
            size="sm"
            className="w-full"
            startContent={<Unlink04Icon width={16} height={16} />}
          >
            Disconnect
          </Button>
        ) : (
          <Button color="primary" size="sm" className="w-full">
            Connect
          </Button>
        )}

        {integration.tools && integration.tools.length > 0 && (
          <div className="mt-4">
            <h4 className="text-sm font-medium text-zinc-300 mb-3">
              Available Tools
            </h4>
            <div className="flex flex-wrap gap-2">
              {integration.tools.map((tool) => (
                <Chip key={tool} variant="bordered" color="default" size="sm">
                  {tool}
                </Chip>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function DemoIntegrationsView() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedIntegration, setSelectedIntegration] =
    useState<DemoIntegration | null>(null);

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
    if (integration) setSelectedIntegration(integration);
  };

  return (
    <div className="flex h-full">
      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-6">
        {/* Search */}
        <div className="mb-6">
          <Input
            placeholder="Search integrations..."
            value={searchQuery}
            onValueChange={setSearchQuery}
            startContent={
              <Search01Icon className="text-zinc-500" width={18} height={18} />
            }
            classNames={{
              inputWrapper: "bg-zinc-800/50 border-zinc-700",
            }}
            size="sm"
            isClearable
            onClear={() => setSearchQuery("")}
          />
        </div>

        {/* Category Filter */}
        <div className="mb-6 flex flex-wrap gap-2">
          {DEMO_CATEGORIES.map((cat) => (
            <Chip
              key={cat}
              variant={selectedCategory === cat ? "solid" : "flat"}
              color={selectedCategory === cat ? "primary" : "default"}
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
                  <Chip size="sm" variant="flat" color="primary">
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
                  <Chip size="sm" variant="flat" color="default">
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
              <Chip size="sm" variant="flat" color="default">
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
          onClose={() => setSelectedIntegration(null)}
        />
      )}
    </div>
  );
}
