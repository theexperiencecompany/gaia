import type { ReferralStatus } from "../types";

type ChipColor = "success" | "primary" | "warning" | "default" | "danger";

interface StatusPresentation {
  label: string;
  chipColor: ChipColor;
  /** Tailwind text color for the leading status dot. */
  dotClass: string;
}

// Maps a referral lifecycle status to its display label, chip color, and dot
// tint. "upgraded"/"renewed" are the wins (primary), "reverted" is the loss.
const STATUS_PRESENTATION: Record<ReferralStatus, StatusPresentation> = {
  invited: {
    label: "Invited",
    chipColor: "default",
    dotClass: "bg-zinc-500",
  },
  signed_up: {
    label: "Joined",
    chipColor: "warning",
    dotClass: "bg-amber-400",
  },
  activated: {
    label: "Active",
    chipColor: "warning",
    dotClass: "bg-amber-400",
  },
  upgraded: {
    label: "Upgraded",
    chipColor: "primary",
    dotClass: "bg-primary",
  },
  renewed: {
    label: "Renewed",
    chipColor: "success",
    dotClass: "bg-emerald-400",
  },
  reverted: {
    label: "Lapsed",
    chipColor: "danger",
    dotClass: "bg-red-400",
  },
};

export function presentStatus(status: ReferralStatus): StatusPresentation {
  return STATUS_PRESENTATION[status];
}
