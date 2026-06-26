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

import type { Integration } from "@/features/integrations/types";

interface ConnectedActionsProps {
  integration: Integration;
  useIconOnly: boolean;
  isOwnIntegration: boolean;
  hasDisconnect: boolean;
  disconnectLabel: string;
  disconnectIcon: React.ReactNode;
  isDisconnecting: boolean;
  isPublishing: boolean;
  onDisconnect: () => void;
  onPublish: () => void;
  onShare: () => void;
}

/** Actions for a connected integration: disconnect, marketplace, publish, share. */
export function ConnectedActions({
  integration,
  useIconOnly,
  isOwnIntegration,
  hasDisconnect,
  disconnectLabel,
  disconnectIcon,
  isDisconnecting,
  isPublishing,
  onDisconnect,
  onPublish,
  onShare,
}: ConnectedActionsProps) {
  return (
    <ButtonGroup variant="flat" className="w-full" fullWidth>
      {hasDisconnect && (
        <Tooltip content={`${disconnectLabel} this integration`}>
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            color="danger"
            onPress={onDisconnect}
            isLoading={isDisconnecting}
            isDisabled={isDisconnecting}
            aria-label={disconnectLabel}
            startContent={isDisconnecting ? undefined : disconnectIcon}
          >
            {!useIconOnly && disconnectLabel}
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

      {isOwnIntegration && integration.isPublic && (
        <Tooltip content="Unpublish from Marketplace">
          <Button
            isIconOnly={useIconOnly}
            color="warning"
            className="w-full"
            onPress={onPublish}
            isLoading={isPublishing}
            isDisabled={isPublishing}
            aria-label="Unpublish"
            startContent={
              !isPublishing ? (
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

      {isOwnIntegration && !integration.isPublic && (
        <Tooltip content="Publish to Community Marketplace">
          <Button
            isIconOnly={useIconOnly}
            className="w-full"
            color="primary"
            onPress={onPublish}
            isLoading={isPublishing}
            isDisabled={isPublishing}
            aria-label="Publish"
            startContent={
              !isPublishing ? <GlobalIcon width={18} height={18} /> : undefined
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
