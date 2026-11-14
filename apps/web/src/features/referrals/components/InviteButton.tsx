"use client";

import { Button } from "@heroui/button";
import { Tick02Icon, UserAdd01Icon } from "@icons";
import type {
  ReferralInviteStatus,
  ReferralInviteSurface,
} from "@shared/api/generated";
import { cn } from "@/lib/utils";
import { REFERRAL_UI_COPY } from "../referralCopy";
import {
  type InviteSender,
  useInvitePhase,
  useInviteStore,
} from "../stores/inviteStore";

type InviteButtonSurface = Exclude<ReferralInviteSurface, "agent">;

interface InviteButtonProps {
  email: string;
  surface: InviteButtonSurface;
  send: InviteSender;
  label?: string;
  fullWidth?: boolean;
}

/** What a settled invite reads as; own_address renders nothing at all. */
const SETTLED_LABEL: Record<
  Exclude<ReferralInviteStatus, "sent" | "own_address">,
  string
> = {
  already_invited: REFERRAL_UI_COPY.invited,
  invalid: REFERRAL_UI_COPY.cannotInvite,
  unsubscribed: REFERRAL_UI_COPY.optedOut,
};

export function InviteButton({
  email,
  surface,
  send,
  label = REFERRAL_UI_COPY.invite,
  fullWidth = false,
}: InviteButtonProps) {
  const phase = useInvitePhase(email);
  const invite = useInviteStore((s) => s.invite);
  const undo = useInviteStore((s) => s.undo);
  const width = fullWidth && "w-full";

  if (!phase || phase.phase === "sending") {
    return (
      <Button
        size="sm"
        variant="flat"
        radius="full"
        isLoading={phase?.phase === "sending"}
        className={cn("shrink-0 font-medium", width)}
        startContent={!phase && <UserAdd01Icon width={15} height={15} />}
        onPress={() => invite(email, surface, send)}
      >
        {label}
      </Button>
    );
  }

  if (phase.phase === "done" && phase.status !== "sent") {
    if (phase.status === "own_address") return null;
    return (
      <Button
        size="sm"
        variant="flat"
        radius="full"
        isDisabled
        className={cn("shrink-0 font-medium", width)}
      >
        {SETTLED_LABEL[phase.status]}
      </Button>
    );
  }

  return (
    <div className={cn("flex shrink-0 items-center gap-1", width)}>
      <Button
        size="sm"
        variant="flat"
        color="success"
        radius="full"
        disableAnimation
        className="pointer-events-none flex-1 font-medium"
        startContent={<Tick02Icon width={15} height={15} />}
        aria-live="polite"
      >
        {REFERRAL_UI_COPY.sent}
      </Button>
      {phase.phase === "held" && (
        <Button
          size="sm"
          variant="light"
          radius="full"
          className="min-w-0 px-3 font-medium text-zinc-400"
          onPress={() => undo(email, surface)}
        >
          {REFERRAL_UI_COPY.undo}
        </Button>
      )}
    </div>
  );
}
