"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { FilterHorizontalIcon } from "@icons";
import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import {
  PANEL_ROW_BUTTON_PROPS,
  PanelRowContent,
} from "@/components/shared/PanelRow";
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
  const copy = GATE_COPY[watchesMail ? "mail" : "event"];

  return (
    <Popover placement="bottom" offset={6} triggerScaleOnOpen={false}>
      <PopoverTrigger>
        <Button {...PANEL_ROW_BUTTON_PROPS}>
          <PanelRowContent
            icon={FilterHorizontalIcon}
            label={rule.enabled ? gateSentence(rule.condition) : copy.off}
            isMuted={!rule.enabled}
            end={
              rule.enabled && skips.length > 0 && gateSkipCount(skips.length)
            }
          />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 rounded-2xl bg-zinc-900 p-0 shadow-xl">
        <GateDetail
          {...rule}
          skips={skips}
          editedByUser={shown?.kind === "authored" && shown.author === "user"}
          copy={copy}
        />
      </PopoverContent>
    </Popover>
  );
}
