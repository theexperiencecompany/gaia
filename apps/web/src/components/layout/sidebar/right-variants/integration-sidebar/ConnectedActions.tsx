"use client";

import { Button, ButtonGroup, Tooltip } from "@heroui/react";
import {
  GlobalIcon,
  LinkSquareIcon,
  RemoveCircleIcon,
  Share08Icon,
} from "@icons";
import { Focusable } from "react-aria-components";

import { LinkButton } from "@/components/shared/LinkButton";
import { useIntegrationOwnership } from "@/features/integrations/hooks/useIntegrationOwnership";
import { marketplacePath } from "@/features/integrations/lib/marketplaceSlug";
import type { Integration } from "@/features/integrations/types";

/** The disconnect/remove action; presence decides whether the button renders. */
interface DisconnectAction {
  label: string;
  icon: React.ReactNode;
  isPending: boolean;
  onDisconnect: () => void;
}

/** The publish/unpublish action; presence decides whether the button renders. */
interface PublishAction {
  isPending: boolean;
  onPublish: () => void;
}

interface ConnectedActionsProps {
  integration: Integration;
  /** Collapse buttons to icon-only when three or more actions are visible. */
  useIconOnly: boolean;
  disconnect?: DisconnectAction | null;
  publish?: PublishAction | null;
  onShare: () => void;
}

/** Actions for a connected integration: disconnect, marketplace, publish, share. */
export function ConnectedActions({
  integration,
  useIconOnly,
  disconnect = null,
  publish = null,
  onShare,
}: ConnectedActionsProps) {
  const { isOwnIntegration } = useIntegrationOwnership(integration);

  return (
    <ButtonGroup variant="tertiary" className="w-full" fullWidth>
      {disconnect && (
        <Tooltip>
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            onPress={disconnect.onDisconnect}
            isPending={disconnect.isPending}
            isDisabled={disconnect.isPending}
            aria-label={disconnect.label}
            variant="danger"
          >
            {!disconnect.isPending && disconnect.icon}
            {!useIconOnly && disconnect.label}
          </Button>
          <Tooltip.Content>{`${disconnect.label} this integration`}</Tooltip.Content>
        </Tooltip>
      )}

      {integration.isPublic && (
        <Tooltip>
          <Focusable>
            <LinkButton
              variant="primary"
              isIconOnly={useIconOnly}
              className="w-full"
              href={marketplacePath(integration.slug)}
              aria-label="View on Marketplace"
            >
              <LinkSquareIcon
                width={18}
                height={18}
                className="outline-none!"
              />
              {!useIconOnly && "View"}
            </LinkButton>
          </Focusable>
          <Tooltip.Content>View on Marketplace</Tooltip.Content>
        </Tooltip>
      )}

      {isOwnIntegration && integration.isPublic && publish && (
        <Tooltip>
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            onPress={publish.onPublish}
            isPending={publish.isPending}
            isDisabled={publish.isPending}
            aria-label="Unpublish"
            variant="primary"
          >
            {!publish.isPending && (
              <RemoveCircleIcon
                width={18}
                height={18}
                className="outline-none!"
              />
            )}
            {!useIconOnly && "Unpublish"}
          </Button>
          <Tooltip.Content>Unpublish from Marketplace</Tooltip.Content>
        </Tooltip>
      )}

      {isOwnIntegration && !integration.isPublic && publish && (
        <Tooltip>
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            onPress={publish.onPublish}
            isPending={publish.isPending}
            isDisabled={publish.isPending}
            aria-label="Publish"
            variant="primary"
          >
            {!publish.isPending && <GlobalIcon width={18} height={18} />}
            {!useIconOnly && "Publish"}
          </Button>
          <Tooltip.Content>Publish to Community Marketplace</Tooltip.Content>
        </Tooltip>
      )}

      {integration.isPublic && (
        <Tooltip>
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            onPress={onShare}
            aria-label="Share"
            variant="primary"
          >
            <Share08Icon width={18} height={18} />
            {!useIconOnly && "Share"}
          </Button>
          <Tooltip.Content>Copy share link to clipboard</Tooltip.Content>
        </Tooltip>
      )}
    </ButtonGroup>
  );
}
