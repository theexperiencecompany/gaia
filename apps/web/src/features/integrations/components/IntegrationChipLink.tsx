import { Chip } from "@heroui/react";

import { SiteLink } from "@/components/seo/SiteLink";
import { toneVariants } from "@/components/shared/tone";
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
        variant="secondary"
        size="md"
        className={toneVariants({ tone: "dim" })}
      >
        {getToolCategoryIcon(
          integration.integrationId,
          { size: 16, width: 16, height: 16, showBackground: false },
          integration.iconUrl,
        )}
        <Chip.Label>{integration.name}</Chip.Label>
      </Chip>
    </SiteLink>
  );
}
