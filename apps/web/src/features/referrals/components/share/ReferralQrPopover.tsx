"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Tooltip } from "@heroui/tooltip";
import { QrCodeIcon } from "@icons";
import { REFERRAL_UI_COPY } from "../../referralCopy";
import { ReferralQrCode } from "./ReferralQrCode";

interface ReferralQrPopoverProps {
  url: string;
  onOpened: () => void;
}

export function ReferralQrPopover({ url, onOpened }: ReferralQrPopoverProps) {
  return (
    <Popover
      placement="bottom"
      onOpenChange={(open) => {
        if (open) onOpened();
      }}
    >
      <Tooltip content={REFERRAL_UI_COPY.qrCode} delay={300}>
        {/* Tooltip needs a focusable wrapper around a Popover trigger. */}
        <div>
          <PopoverTrigger>
            <Button
              isIconOnly
              aria-label={REFERRAL_UI_COPY.qrCode}
              variant="flat"
              radius="full"
              className="size-10 min-w-10 text-zinc-300"
            >
              <QrCodeIcon width={18} height={18} />
            </Button>
          </PopoverTrigger>
        </div>
      </Tooltip>
      <PopoverContent className="rounded-2xl bg-zinc-800 p-4">
        <ReferralQrCode url={url} size={176} />
        <p className="mt-3 max-w-44 text-center text-xs text-pretty text-zinc-400">
          {REFERRAL_UI_COPY.qrHint}
        </p>
      </PopoverContent>
    </Popover>
  );
}
