import {
  Description,
  Dropdown,
  Input,
  Label,
  Menu,
  TextField,
} from "@heroui/react";
import { MoreHorizontalIcon } from "@icons";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  ApprovalScope,
} from "@shared/chat";
import {
  approvalAgeSeconds,
  formatApprovalAge,
  RECONFIRM_AGE_SECONDS,
} from "@shared/chat";
import { endAfterDecision, flattenArgsPreview } from "@shared/utils";
import { useMemo, useState } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { ShieldAlertIcon } from "@/components/shared/icons";
import { chatApi } from "@/features/chat/api/chatApi";
import { APPROVAL_COPY } from "@/features/chat/constants/approvalCopy";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { toast } from "@/lib/toast";

/** Labelled facts in the card's inner panel. */
function detailRows(
  rows: readonly ApprovalRequestData["description"]["details"][number][],
) {
  return (
    <div className="mt-3 space-y-2 rounded-2xl bg-zinc-900 p-3">
      {rows.map((detail) => (
        <div key={detail.label} className="text-xs">
          <div className="mb-0.5 text-[11px] text-zinc-500">{detail.label}</div>
          <div className="break-words text-zinc-200">{detail.value}</div>
        </div>
      ))}
    </div>
  );
}

interface ApprovalRequestSectionProps {
  data: ApprovalRequestData;
  /** A batch decision ("Approve all"/"Decline all") is in flight — lock this card
   * so a per-card click can't send a second, conflicting decision for the same id. */
  disabled?: boolean;
}

/** Every argument of the call, for anyone who wants more than the plain-language facts. */
function ArgsPreview({ args }: { args: Record<string, unknown> }) {
  const { rows, omitted } = useMemo(() => flattenArgsPreview(args), [args]);
  if (rows.length === 0) return null;
  let lastGroup: string | null = null;
  return (
    <div className="mt-2 space-y-2 rounded-2xl bg-zinc-900 p-3">
      {rows.map((row) => {
        const showGroup = row.group !== null && row.group !== lastGroup;
        lastGroup = row.group;
        return (
          <div key={`${row.group ?? "top"}:${row.key}:${row.value}`}>
            {showGroup && (
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-zinc-400">
                {row.group}
              </div>
            )}
            <div className="text-xs">
              <div className="mb-0.5 text-[11px] text-zinc-500">
                {row.key.replace(/^./, (char) => char.toUpperCase())}
              </div>
              <div className="text-zinc-200">{row.value}</div>
            </div>
          </div>
        );
      })}
      {omitted > 0 && (
        <div className="text-[11px] text-zinc-500">+{omitted} more</div>
      )}
    </div>
  );
}

type Phase = "idle" | "reconfirm" | "submitting";

export default function ApprovalRequestSection({
  data,
  disabled = false,
}: ApprovalRequestSectionProps) {
  const [submitting, setSubmitting] = useState<ApprovalDecision | null>(null);
  const [feedback, setFeedback] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [showAllArgs, setShowAllArgs] = useState(false);
  const [openedAt] = useState(() => Date.now());
  const locked = submitting !== null || disabled || phase === "submitting";

  const ageSeconds = approvalAgeSeconds(data.asked_at, openedAt);
  const needsReconfirm = (ageSeconds ?? 0) >= RECONFIRM_AGE_SECONDS;
  const { description } = data;
  const facts = description.details.filter((detail) => !detail.expandable);
  const longText = description.details.filter((detail) => detail.expandable);
  const integrationIcon = data.integration_name
    ? getToolCategoryIcon(data.integration_name, {
        width: 20,
        height: 20,
        showBackground: false,
      })
    : null;

  const submit = async (
    decision: ApprovalDecision,
    scope: ApprovalScope = "once",
  ) => {
    setSubmitting(decision);
    setPhase("submitting");
    // A note rides either decision, as on the review sheet: with Approve it is the
    // change, and the work asks again with it instead of running the call as it stands.
    try {
      const outcome = await chatApi.postApprovalDecision(data.approval_id, {
        decision,
        feedback: feedback.trim() || undefined,
        scope,
      });
      // The server's screen ends the card with the action's result; reaching the
      // catch means the submit genuinely failed.
      if (endAfterDecision(decision, outcome) === null) {
        setSubmitting(null);
        setPhase("idle");
        toast.error(APPROVAL_COPY.alreadyDecided);
        return;
      }
    } catch {
      toast.error(APPROVAL_COPY.submitFailed);
      setSubmitting(null);
      setPhase("idle");
    }
  };

  const onApproveTap = () => {
    if (needsReconfirm && phase === "idle") {
      setPhase("reconfirm");
      return;
    }
    // No commit grace: the tap IS the decision. The ledger CAS makes a
    // double tap harmless, so there is nothing a waiting room would protect.
    void submit("approve");
  };

  if (data.outcome != null) return null;

  if (phase === "reconfirm") {
    return (
      <div className="w-full max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
        <div className="text-sm leading-snug text-zinc-100">
          {`Asked ${formatApprovalAge(ageSeconds).replace("asked ", "")} ago — still want this?`}
        </div>
        <div className="mt-1 text-xs text-zinc-400">{description.headline}</div>
        <div className="mt-3 flex items-center gap-2">
          <GaiaButton
            size="sm"
            onPress={() => {
              setPhase("idle");
              onApproveTap();
            }}
            variant="primary"
          >
            {APPROVAL_COPY.reconfirmApprove}
          </GaiaButton>
          <GaiaButton
            variant="default-soft"
            size="sm"
            onPress={() => setPhase("idle")}
          >
            {APPROVAL_COPY.back}
          </GaiaButton>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
      <div className="flex items-start gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-zinc-900">
          {integrationIcon ?? (
            <ShieldAlertIcon
              width={17}
              height={17}
              className="text-amber-400"
            />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-amber-400">
            {APPROVAL_COPY.needsApproval}
            {data.integration_name && (
              <span className="font-normal text-zinc-500">
                {APPROVAL_COPY.inIntegration(data.integration_name)}
              </span>
            )}
          </div>
          <div className="text-sm leading-snug text-zinc-100">
            {description.headline}
          </div>
          {ageSeconds != null && (
            <div className="mt-0.5 text-[11px] text-zinc-500">
              {formatApprovalAge(ageSeconds)}
            </div>
          )}
        </div>
      </div>

      {data.auto_reason?.trim() && (
        <div className="mt-2 text-xs leading-snug text-zinc-400">
          {data.auto_reason.trim()}
        </div>
      )}

      {facts.length > 0 && detailRows(facts)}

      {description.details.length === 0 || showAllArgs ? (
        <>
          {longText.length > 0 && detailRows(longText)}
          <ArgsPreview args={data.args_preview} />
        </>
      ) : (
        <GaiaButton
          className="mt-1"
          size="sm"
          variant="ghost"
          inset="none"
          tone="faint"
          onPress={() => setShowAllArgs(true)}
        >
          {APPROVAL_COPY.showAllDetails}
        </GaiaButton>
      )}

      <div className="mt-3 flex items-center gap-2">
        <TextField
          className={inputVariants({ size: "sm", className: "flex-1" })}
          value={feedback}
          onChange={setFeedback}
          isDisabled={locked}
        >
          <Input placeholder={APPROVAL_COPY.feedbackPlaceholder} />
        </TextField>
        <GaiaButton
          size="sm"
          isDisabled={locked}
          onPress={onApproveTap}
          variant="primary"
        >
          {APPROVAL_COPY.approve}
        </GaiaButton>
        <GaiaButton
          variant="default-soft"
          size="sm"
          isDisabled={locked}
          onPress={() => submit("deny")}
        >
          {APPROVAL_COPY.deny}
        </GaiaButton>
        {!data.always_asks && (
          <Dropdown>
            <GaiaButton
              isIconOnly
              size="sm"
              variant="ghost"
              isDisabled={locked}
              aria-label={APPROVAL_COPY.moreOptions}
            >
              <MoreHorizontalIcon width={18} />
            </GaiaButton>
            <Dropdown.Popover placement="bottom end">
              <Menu aria-label={APPROVAL_COPY.optionsMenu}>
                <Menu.Item
                  id="always"
                  textValue={APPROVAL_COPY.alwaysAllow(description.action)}
                  onAction={() => submit("approve", "always_tool")}
                >
                  <Label>{APPROVAL_COPY.alwaysAllow(description.action)}</Label>
                  <Description>{APPROVAL_COPY.alwaysAllowHint}</Description>
                </Menu.Item>
              </Menu>
            </Dropdown.Popover>
          </Dropdown>
        )}
      </div>
    </div>
  );
}
