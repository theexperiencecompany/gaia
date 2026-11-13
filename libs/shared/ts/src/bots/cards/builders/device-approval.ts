import type { Card } from "../types";

/**
 * The `device_approval_required` payload (app/utils/device_onboarding.py): a
 * machine waiting on its pairing code, and the signed-in page that approves it.
 */
export interface DeviceApprovalRequiredData {
  approve_url: string;
  code: string;
  message: string;
}

const APPROVE_LABEL = "Approve";

/** The link to the approve page; the approval itself happens there, signed in. */
export function buildDeviceApprovalCards(
  data: DeviceApprovalRequiredData,
): Card[] {
  return [
    {
      title: `Approve device ${data.code}`,
      accent: "warning",
      status: { label: "New device", tone: "warning" },
      blocks: [{ kind: "text", markdown: data.message }],
      actions: [{ kind: "link", label: APPROVE_LABEL, url: data.approve_url }],
    },
  ];
}
