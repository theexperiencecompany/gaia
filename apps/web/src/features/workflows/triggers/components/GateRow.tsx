"use client";

import { Button, Popover } from "@heroui/react";
import { FilterHorizontalIcon } from "@icons";
import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { PanelRowContent } from "@/components/shared/PanelRow";
import { PANEL_ROW_BUTTON_PROPS } from "@/components/shared/panelRowButtonProps";
import { GATE_COPY, gateSkipCount } from "../../constants/gates";
import { gateSentence } from "../../utils/gateEdit";
import { GateDetail, type GateRuleProps } from "./GateDetail";

interface GateRowProps extends GateRuleProps {
  /** The gate as last saved; its author and skips describe the rule only while it is unchanged. */
  saved: AuthoredGateView | SystemGateView | null;
  /** Whether the job's trigger is new mail, which the row and switch name as email. */
  watchesMail: boolean;
}

/** A job's rule as one quiet row; what it skipped, its switch and its edit open in a popover. */
export function GateRow({ saved, watchesMail, ...rule }: GateRowProps) {
  if (!rule.condition.trim()) return null;

  const shown = saved?.display_condition === rule.condition ? saved : null;
  const skips = shown?.recent_skips ?? [];
  const skippedCount = shown?.skipped_count ?? 0;
  const copy = GATE_COPY[watchesMail ? "mail" : "event"];

  return (
    <Popover>
      <Button {...PANEL_ROW_BUTTON_PROPS}>
        <PanelRowContent
          icon={FilterHorizontalIcon}
          label={rule.enabled ? gateSentence(rule.condition) : copy.off}
          isMuted={!rule.enabled}
          end={rule.enabled && skippedCount > 0 && gateSkipCount(skippedCount)}
        />
      </Button>
      <Popover.Content placement="bottom" offset={6}>
        <Popover.Dialog className="w-80 shadow-xl">
          <GateDetail
            {...rule}
            skips={skips}
            editedByUser={shown?.kind === "authored" && shown.author === "user"}
            copy={copy}
          />
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}
