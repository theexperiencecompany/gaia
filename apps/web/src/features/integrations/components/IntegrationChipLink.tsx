import { Chip } from "@heroui/chip";

import { SiteLink } from "@/components/seo/SiteLink";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { marketplacePath } from "@/features/integrations/lib/marketplaceSlug";
import type { CommunityIntegration } from "@/features/integrations/types";

interface IntegrationChipLinkProps {
  readonly integration: CommunityIntegration;
}

/** A compact link to an integration's marketplace page: its icon and name. */
export function IntegrationChipLink({ integration }: IntegrationChipLinkProps) {
  return (
    <SiteLink href={marketplacePath(integration.slug)}>
      <Chip
        variant="flat"
        size="md"
        className="bg-zinc-800 text-zinc-300"
        startContent={getToolCategoryIcon(
          integration.integrationId,
          { size: 16, width: 16, height: 16, showBackground: false },
          integration.iconUrl,
        )}
      >
        {integration.name}
      </Chip>
    </SiteLink>
  );
}
