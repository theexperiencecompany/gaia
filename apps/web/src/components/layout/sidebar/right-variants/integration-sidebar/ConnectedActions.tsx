"use client";

import {
  Button,
  ButtonGroup,
  type ButtonProps,
  buttonVariants,
  Tooltip,
} from "@heroui/react";
import {
  GlobalIcon,
  LinkSquareIcon,
  RemoveCircleIcon,
  Share08Icon,
} from "@icons";
import Link from "next/link";

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

/** Renders the tooltip trigger's props onto the button itself, so the button
 * stays a direct child of the ButtonGroup (and keeps its grouped styling). */
function asButton(
  props: React.DetailedHTMLProps<
    React.HTMLAttributes<HTMLDivElement>,
    HTMLDivElement
  >,
  buttonProps: ButtonProps,
) {
  return (
    <Button {...(props as unknown as ButtonProps)} {...buttonProps}>
      {buttonProps.children}
    </Button>
  );
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
          <Tooltip.Trigger
            render={(props) =>
              asButton(props, {
                isIconOnly: useIconOnly,
                className: "w-full",
                onPress: disconnect.onDisconnect,
                isPending: disconnect.isPending,
                isDisabled: disconnect.isPending,
                "aria-label": disconnect.label,
                variant: "danger",
                children: (
                  <>
                    {!disconnect.isPending && disconnect.icon}
                    {!useIconOnly && disconnect.label}
                  </>
                ),
              })
            }
          />
          <Tooltip.Content>{`${disconnect.label} this integration`}</Tooltip.Content>
        </Tooltip>
      )}

      {integration.isPublic && (
        <Tooltip>
          <Tooltip.Trigger
            render={(props) => (
              <Link
                {...(props as unknown as React.ComponentProps<typeof Link>)}
                className={buttonVariants({
                  variant: "primary",
                  isIconOnly: useIconOnly,
                  className: "w-full",
                })}
                href={marketplacePath(integration.slug)}
                aria-label="View on Marketplace"
              >
                <LinkSquareIcon
                  width={18}
                  height={18}
                  className="outline-none!"
                />
                {!useIconOnly && "View"}
              </Link>
            )}
          />
          <Tooltip.Content>View on Marketplace</Tooltip.Content>
        </Tooltip>
      )}

      {isOwnIntegration && integration.isPublic && publish && (
        <Tooltip>
          <Tooltip.Trigger
            render={(props) =>
              asButton(props, {
                isIconOnly: useIconOnly,
                className: "w-full",
                onPress: publish.onPublish,
                isPending: publish.isPending,
                isDisabled: publish.isPending,
                "aria-label": "Unpublish",
                variant: "primary",
                children: (
                  <>
                    {!publish.isPending && (
                      <RemoveCircleIcon
                        width={18}
                        height={18}
                        className="outline-none!"
                      />
                    )}
                    {!useIconOnly && "Unpublish"}
                  </>
                ),
              })
            }
          />
          <Tooltip.Content>Unpublish from Marketplace</Tooltip.Content>
        </Tooltip>
      )}

      {isOwnIntegration && !integration.isPublic && publish && (
        <Tooltip>
          <Tooltip.Trigger
            render={(props) =>
              asButton(props, {
                isIconOnly: useIconOnly,
                className: "w-full",
                onPress: publish.onPublish,
                isPending: publish.isPending,
                isDisabled: publish.isPending,
                "aria-label": "Publish",
                variant: "primary",
                children: (
                  <>
                    {!publish.isPending && (
                      <GlobalIcon width={18} height={18} />
                    )}
                    {!useIconOnly && "Publish"}
                  </>
                ),
              })
            }
          />
          <Tooltip.Content>Publish to Community Marketplace</Tooltip.Content>
        </Tooltip>
      )}

      {integration.isPublic && (
        <Tooltip>
          <Tooltip.Trigger
            render={(props) =>
              asButton(props, {
                isIconOnly: useIconOnly,
                className: "w-full",
                onPress: onShare,
                "aria-label": "Share",
                variant: "primary",
                children: (
                  <>
                    <Share08Icon width={18} height={18} />
                    {!useIconOnly && "Share"}
                  </>
                ),
              })
            }
          />
          <Tooltip.Content>Copy share link to clipboard</Tooltip.Content>
        </Tooltip>
      )}
    </ButtonGroup>
  );
}
