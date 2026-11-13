import type { NoticeAction, UpdateRow } from "@shared/api/generated";

export interface UpdateActionLink {
  label: string;
  href: string;
}

const UPGRADE_HREF = "/pricing";

function actionLink(action: NoticeAction): UpdateActionLink {
  switch (action.kind) {
    case "upgrade":
      return { label: "Upgrade", href: UPGRADE_HREF };
    case "reconnect_integration": {
      const params = new URLSearchParams({
        connect: action.integration_id ?? "",
      });
      if (action.account_id) params.set("account", action.account_id);
      return { label: "Reconnect", href: `/integrations?${params}` };
    }
  }
}

/** The button a notice offers, or none once what it asked of the user is done. */
export function updateAction(row: UpdateRow): UpdateActionLink | null {
  const action = row.display?.action;
  if (!action || row.resolved_at) return null;
  return actionLink(action);
}
