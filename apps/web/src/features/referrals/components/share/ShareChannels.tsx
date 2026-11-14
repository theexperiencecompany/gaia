"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import {
  Linkedin01Icon,
  Mail01Icon,
  Message01Icon,
  NewTwitterIcon,
  WhatsappIcon,
} from "@icons";
import type { ComponentType, SVGProps } from "react";
import { CHANNEL_LABELS } from "../../referralCopy";
import { LINK_CHANNELS, type LinkChannel } from "../../utils/shareTargets";
import { ReferralQrPopover } from "./ReferralQrPopover";

const CHANNEL_ICONS: Record<
  LinkChannel,
  ComponentType<SVGProps<SVGSVGElement>>
> = {
  whatsapp: WhatsappIcon,
  sms: Message01Icon,
  x: NewTwitterIcon,
  linkedin: Linkedin01Icon,
  email: Mail01Icon,
};

interface ShareChannelsProps {
  url: string;
  onChannel: (channel: LinkChannel) => void;
  onQrOpened: () => void;
}

export function ShareChannels({
  url,
  onChannel,
  onQrOpened,
}: ShareChannelsProps) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {LINK_CHANNELS.map((channel) => {
        const Icon = CHANNEL_ICONS[channel];
        return (
          <Tooltip key={channel} content={CHANNEL_LABELS[channel]} delay={300}>
            <Button
              isIconOnly
              aria-label={`Share on ${CHANNEL_LABELS[channel]}`}
              variant="flat"
              radius="full"
              className="size-10 min-w-10 text-zinc-300"
              onPress={() => onChannel(channel)}
            >
              <Icon width={18} height={18} />
            </Button>
          </Tooltip>
        );
      })}
      <ReferralQrPopover url={url} onOpened={onQrOpened} />
    </div>
  );
}
