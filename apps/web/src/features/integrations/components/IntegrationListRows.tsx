import { Chip } from "@heroui/react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { chipVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { InstanceSetupNotice } from "@/features/integrations/components/InstanceSetupNotice";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { marketplacePath } from "@/features/integrations/lib/marketplaceSlug";
import type {
  Integration,
  SuggestedIntegration,
} from "@/features/integrations/types";
import { toast } from "@/lib/toast";

interface IntegrationRowProps {
  integration: Integration;
  onConnect: (integrationId: string) => Promise<unknown>;
}

/** One of the user's integrations: opens its settings, with Connect while it is not connected. */
export function IntegrationRow({
  integration,
  onConnect,
}: IntegrationRowProps) {
  const router = useRouter();
  const isConnected = integration.status === "connected";
  // Use backend's 'available' field for platform integrations
  const isAvailable = integration.source === "custom" || integration.available;

  const connect = async () => {
    try {
      await onConnect(integration.id);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  return (
    <div className="group flex items-start gap-3 p-3 transition-colors hover:bg-zinc-700">
      <button
        type="button"
        className="flex min-w-0 flex-1 cursor-pointer items-start gap-3 text-left"
        onClick={() =>
          router.push(`/integrations?id=${encodeURIComponent(integration.id)}`)
        }
      >
        <div className="shrink-0 pt-0.5">
          <IntegrationIcon
            integrationId={integration.id}
            iconUrl={integration.iconUrl}
            category={integration.category}
            size={20}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">
              {integration.name}
            </span>
            {isConnected && (
              <Chip size="sm" variant="soft" color="success">
                Connected
              </Chip>
            )}
          </div>
          <p className="mt-1 text-xs text-zinc-400">
            {integration.description}
          </p>
        </div>
      </button>

      {!isConnected && integration.instanceSetupRequired && (
        <InstanceSetupNotice />
      )}

      {!isConnected && isAvailable && !integration.instanceSetupRequired && (
        <GaiaButton
          variant="accent-soft"
          size="sm"
          className="shrink-0 text-xs"
          onPress={connect}
        >
          Connect
        </GaiaButton>
      )}
    </div>
  );
}

/** Add a community integration to the user's account, following its OAuth redirect when it needs one. */
function useAddSuggested(
  suggestion: SuggestedIntegration,
  onConnected: () => Promise<unknown>,
) {
  const [isAdding, setIsAdding] = useState(false);

  const add = async () => {
    setIsAdding(true);
    const toastId = toast.loading(`Adding ${suggestion.name}...`);
    try {
      const result = await integrationsApi.addIntegration(suggestion.id);
      if (result.status === "connected") {
        toast.success(`${suggestion.name} connected successfully`, {
          id: toastId,
        });
        await onConnected();
      } else if (result.status === "redirect" && result.redirectUrl) {
        toast.dismiss(toastId);
        window.location.href = result.redirectUrl;
      } else {
        toast.error(`Failed to connect ${suggestion.name}`, { id: toastId });
      }
    } catch (error) {
      toast.error(
        `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
        { id: toastId },
      );
    } finally {
      setIsAdding(false);
    }
  };

  return { isAdding, add };
}

interface SuggestedIntegrationRowProps {
  suggestion: SuggestedIntegration;
  onConnected: () => Promise<unknown>;
}

/** A community integration the user can add: opens its marketplace page, with Add. */
export function SuggestedIntegrationRow({
  suggestion,
  onConnected,
}: SuggestedIntegrationRowProps) {
  const router = useRouter();
  const { isAdding, add } = useAddSuggested(suggestion, onConnected);

  return (
    <div className="group flex items-start gap-3 p-3 transition-colors hover:bg-zinc-700">
      <button
        type="button"
        className="flex min-w-0 flex-1 cursor-pointer items-start gap-3 text-left"
        onClick={() =>
          router.push(marketplacePath(encodeURIComponent(suggestion.slug)))
        }
      >
        <div className="shrink-0 pt-0.5">
          <IntegrationIcon
            integrationId={suggestion.id}
            iconUrl={suggestion.iconUrl}
            size={20}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">
              {suggestion.name}
            </span>
            <Chip
              size="sm"
              variant="soft"
              color="accent"
              className={chipVariants({ hue: "secondary" })}
            >
              Community
            </Chip>
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-zinc-400">
            {suggestion.description}
          </p>
        </div>
      </button>

      <GaiaButton
        variant="accent-soft"
        size="sm"
        className="shrink-0 text-xs"
        isPending={isAdding}
        onPress={add}
      >
        {isAdding ? "Adding..." : "Add"}
      </GaiaButton>
    </div>
  );
}
