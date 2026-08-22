"use client";

import { Button, ButtonGroup } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import {
  GlobalIcon,
  LinkSquareIcon,
  RemoveCircleIcon,
  Share08Icon,
} from "@icons";
import Link from "next/link";

import { useIntegrationOwnership } from "@/features/integrations/hooks/useIntegrationOwnership";
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
    <ButtonGroup variant="flat" className="w-full" fullWidth>
      {disconnect && (
        <Tooltip content={`${disconnect.label} this integration`}>
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            color="danger"
            onPress={disconnect.onDisconnect}
            isLoading={disconnect.isPending}
            isDisabled={disconnect.isPending}
            aria-label={disconnect.label}
            startContent={disconnect.isPending ? undefined : disconnect.icon}
          >
            {!useIconOnly && disconnect.label}
          </Button>
        </Tooltip>
      )}

      {integration.isPublic && (
        <Tooltip content="View on Marketplace">
          <Button
            className="w-full"
            isIconOnly={useIconOnly}
            as={Link}
            href={`/marketplace/${integration.slug}`}
            color="primary"
            aria-label="View on Marketplace"
            startContent={
              <LinkSquareIcon
                width={18}
                height={18}
                className="outline-none!"
              />
            }
          >
            {!useIconOnly && "View"}
          </Button>
        </Tooltip>
      )}

      {isOwnIntegration && integration.isPublic && publish && (
        <Tooltip content="Unpublish from Marketplace">
          <Button
            isIconOnly={useIconOnly}
            color="warning"
            className="w-full"
            onPress={publish.onPublish}
            isLoading={publish.isPending}
            isDisabled={publish.isPending}
            aria-label="Unpublish"
            startContent={
              !publish.isPending ? (
                <RemoveCircleIcon
                  width={18}
                  height={18}
                  className="outline-none!"
                />
              ) : undefined
            }
          >
            {!useIconOnly && "Unpublish"}
          </Button>
        </Tooltip>
      )}

      {isOwnIntegration && !integration.isPublic && publish && (
        <Tooltip content="Publish to Community Marketplace">
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            color="primary"
            onPress={publish.onPublish}
            isLoading={publish.isPending}
            isDisabled={publish.isPending}
            aria-label="Publish"
            startContent={
              !publish.isPending ? (
                <GlobalIcon width={18} height={18} />
              ) : undefined
            }
          >
            {!useIconOnly && "Publish"}
          </Button>
        </Tooltip>
      )}

      {integration.isPublic && (
        <Tooltip content="Copy share link to clipboard">
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            color="default"
            onPress={onShare}
            aria-label="Share"
            startContent={<Share08Icon width={18} height={18} />}
          >
            {!useIconOnly && "Share"}
          </Button>
        </Tooltip>
      )}
    </ButtonGroup>
  );
}
