import type { ApprovalStatus, ToolDataEntry } from "@gaia/shared/chat";
import * as Clipboard from "expo-clipboard";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type LayoutChangeEvent,
  Pressable,
  ScrollView,
  useWindowDimensions,
  View,
} from "react-native";
import Animated, {
  Easing,
  FadeIn,
  type SharedValue,
  useAnimatedStyle,
  useDerivedValue,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import {
  Alert01Icon,
  AppIcon,
  ArrowDown01Icon,
  Brain02Icon,
  Copy01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { colors, typography } from "@/lib/design-tokens";
import { selectionHaptic } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { TOOL_RENDERERS } from "../../tool-data/renderers";
import {
  type ActivityStatus,
  type ActivityToolCall,
  type ApprovalLookup,
  buildApprovalLookup,
  buildTimeline,
  callStatus,
  countTimelineTools,
  type EnrichedSubagentGroup,
  formatDetailText,
  humanToolTitle,
  matchRichRenderer,
  previewForCall,
} from "./activity-format";
import { PulsingDot } from "./pulsing";

// Gap scale — decisions §5 allows ONLY these values.
const GAP = { xs: 2, sm: 4, md: 8, lg: 12, xl: 16, xxl: 24 } as const;

const ROW_HEIGHT = 32;
const DOT_CONTAINER_SIZE = 20;
const CROSSFADE_MS = 150;
const EXPAND_MS = 200;
const FADE_MS = 150;
const EXPAND_EASING = Easing.bezier(0.32, 0.72, 0, 1);
const DETAIL_MAX_HEIGHT_RATIO = 0.4;
const CARD_RADIUS = 12;
const CARD_PADDING = 10;
const MAX_SUMMARY_ICONS = 3;
const SUBAGENT_INDENT = 16;
const MAX_INDENT_DEPTH = 2;
const CHIP_HEIGHT = 18;
const TASK_MAX_LINES = 4;
const MONO_FONT = typography.fontFamily.mono[0];
const PANEL_BG = `${colors.zinc900}80`;

/** Single shared elapsed-seconds timer — freezes once `running` goes false. */
function useElapsedSeconds(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [running]);
  return seconds;
}

function formatSeconds(seconds: number): string {
  return `${seconds}s`;
}

/**
 * Measured-height collapse shared by every expandable surface in the block
 * (root timeline, subagent bodies, thinking details). Heights animate the
 * always-mounted inner container — no list items are ever added or removed
 * (FlashList-safe). `progress` also drives chevron rotation.
 */
function useMeasuredCollapse(open: boolean): {
  progress: SharedValue<number>;
  collapseStyle: ReturnType<typeof useAnimatedStyle>;
  measureHandler: (event: LayoutChangeEvent) => void;
} {
  const contentHeight = useSharedValue(0);
  const progress = useSharedValue(open ? 1 : 0);
  const fade = useSharedValue(open ? 1 : 0);

  useEffect(() => {
    progress.value = withTiming(open ? 1 : 0, {
      duration: EXPAND_MS,
      easing: EXPAND_EASING,
    });
    fade.value = withTiming(open ? 1 : 0, { duration: FADE_MS });
  }, [open, progress, fade]);

  const collapseStyle = useAnimatedStyle(() => ({
    height: contentHeight.value * progress.value,
    opacity: fade.value,
    overflow: "hidden",
  }));

  const measureHandler = useCallback(
    (event: LayoutChangeEvent) => {
      contentHeight.value = event.nativeEvent.layout.height;
    },
    [contentHeight],
  );

  return { progress, collapseStyle, measureHandler };
}

/** Chevron rotating off a collapse's own progress. */
function CollapseChevron({ progress }: { progress: SharedValue<number> }) {
  const rotation = useDerivedValue(() => `${progress.value * 180}deg`);
  const style = useAnimatedStyle(() => ({
    transform: [{ rotate: rotation.value }],
  }));
  return (
    <Animated.View style={style}>
      <AppIcon icon={ArrowDown01Icon} size={12} color={colors.zinc500} />
    </Animated.View>
  );
}

function CategoryIcon({
  category,
  iconUrl,
  size,
}: {
  category: string;
  iconUrl?: string;
  size: number;
}) {
  const icon = getToolCategoryIcon(
    category,
    { size, showBackground: false },
    iconUrl,
  );
  return icon ?? null;
}

/** pulsing dot → check crossfade (~150ms); red dot on error. */
function StatusDot({ status }: { status: ActivityStatus }) {
  const doneOpacity = useSharedValue(status === "done" ? 1 : 0);

  useEffect(() => {
    doneOpacity.value = withTiming(status === "done" ? 1 : 0, {
      duration: CROSSFADE_MS,
    });
  }, [status, doneOpacity]);

  const checkStyle = useAnimatedStyle(() => ({ opacity: doneOpacity.value }));
  const dotStyle = useAnimatedStyle(() => ({ opacity: 1 - doneOpacity.value }));

  return (
    <View
      style={{
        width: DOT_CONTAINER_SIZE,
        height: DOT_CONTAINER_SIZE,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Animated.View style={[dotStyle, { position: "absolute" }]}>
        {status === "error" ? (
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: colors.error,
            }}
          />
        ) : (
          <PulsingDot size={8} color={colors.zinc400} />
        )}
      </Animated.View>
      <Animated.View style={[checkStyle, { position: "absolute" }]}>
        <AppIcon icon={Tick02Icon} size={14} color={colors.zinc400} />
      </Animated.View>
    </View>
  );
}

/** A tool call blocked on a HIL approval shows why it is stuck inline. */
function WaitingForApprovalPill() {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: GAP.xs,
        flexShrink: 0,
      }}
    >
      <AppIcon icon={Alert01Icon} size={13} color={colors.warning} />
      <Text style={{ fontSize: 11, fontWeight: "500", color: colors.warning }}>
        Waiting for approval
      </Text>
    </View>
  );
}

const APPROVAL_CHIP: Partial<
  Record<ApprovalStatus, { label: string; color: string }>
> = {
  approved: { label: "Approved", color: colors.success },
  auto_approved: { label: "Auto-approved", color: colors.success },
  denied: { label: "Denied", color: colors.error },
  timeout: { label: "Expired", color: colors.zinc500 },
  abandoned: { label: "Expired", color: colors.zinc500 },
};

/** A settled HIL decision rides its tool's own row as a small chip. */
function ApprovalOutcomeChip({ status }: { status: ApprovalStatus }) {
  const chip = APPROVAL_CHIP[status];
  if (!chip) return null;
  return (
    <View
      style={{
        height: CHIP_HEIGHT,
        borderRadius: CHIP_HEIGHT / 2,
        paddingHorizontal: GAP.md,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: `${chip.color}1f`,
        flexShrink: 0,
      }}
    >
      <Text style={{ fontSize: 10, fontWeight: "500", color: chip.color }}>
        {chip.label}
      </Text>
    </View>
  );
}

function CopyJsonButton({ json }: { json: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    Clipboard.setStringAsync(json)
      .then(() => setCopied(true))
      .catch(() => setCopied(false));
  }, [json]);

  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(id);
  }, [copied]);

  return (
    <Pressable
      onPress={copy}
      hitSlop={GAP.md}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: GAP.sm,
        opacity: pressed ? 0.6 : 1,
        alignSelf: "flex-start",
        paddingVertical: GAP.sm,
      })}
    >
      <AppIcon
        icon={copied ? Tick02Icon : Copy01Icon}
        size={13}
        color={copied ? colors.success : colors.zinc500}
      />
      <Text style={{ fontSize: 11, color: colors.zinc500 }}>
        {copied ? "Copied" : "Copy"}
      </Text>
    </Pressable>
  );
}

/** Raw monospace JSON behind a secondary toggle WITH copy button. */
function RawJsonToggle({
  inputs,
  output,
}: {
  inputs?: Record<string, unknown>;
  output?: string;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const json = JSON.stringify({ inputs, output }, null, 2);

  return (
    <View>
      <Pressable
        onPress={() => setShowRaw((v) => !v)}
        hitSlop={GAP.md}
        style={({ pressed }) => ({
          opacity: pressed ? 0.6 : 1,
          alignSelf: "flex-start",
        })}
      >
        <Text style={{ fontSize: 11, color: colors.zinc500 }}>
          {showRaw ? "Hide raw JSON" : "Raw JSON"}
        </Text>
      </Pressable>
      {showRaw ? (
        <View
          style={{
            marginTop: GAP.sm,
            backgroundColor: PANEL_BG,
            borderRadius: CARD_RADIUS,
            padding: CARD_PADDING,
          }}
        >
          <Text
            style={{
              fontFamily: MONO_FONT,
              fontSize: 11,
              lineHeight: 18,
              color: colors.zinc400,
            }}
          >
            {json}
          </Text>
          <CopyJsonButton json={json} />
        </View>
      ) : null}
    </View>
  );
}

function LabeledSection({
  label,
  content,
}: {
  label: string;
  content: string;
}) {
  return (
    <View>
      <Text
        style={{
          fontSize: typography.fontSize.xs,
          color: colors.zinc500,
          fontWeight: "500",
          marginBottom: GAP.sm,
        }}
      >
        {label}
      </Text>
      <View
        style={{
          backgroundColor: PANEL_BG,
          borderRadius: CARD_RADIUS,
          padding: CARD_PADDING,
        }}
      >
        <Text
          style={{
            fontFamily: MONO_FONT,
            fontSize: 11,
            lineHeight: 18,
            color: colors.zinc400,
          }}
        >
          {content}
        </Text>
      </View>
    </View>
  );
}

/**
 * Second level: tap a row → detail, bounded to ~40% of the window height in
 * an internal ScrollView. Rich TOOL_RENDERERS typed card (interactive) when
 * the output carries one, otherwise formatted Input/Output panels — with raw
 * JSON behind a secondary copyable toggle either way.
 */
function RowDetail({ call }: { call: ActivityToolCall }) {
  const { height: windowHeight } = useWindowDimensions();
  const rich = matchRichRenderer(call.output);
  const hasInputs = !!call.inputs && Object.keys(call.inputs).length > 0;

  return (
    <ScrollView
      nestedScrollEnabled
      style={{ maxHeight: windowHeight * DETAIL_MAX_HEIGHT_RATIO }}
      contentContainerStyle={{
        gap: GAP.md,
        paddingBottom: GAP.xs,
        marginBottom: GAP.lg,
      }}
    >
      {rich ? TOOL_RENDERERS[rich.key]?.(rich.data, rich.key) : null}
      {!rich && hasInputs ? (
        <LabeledSection label="Input" content={formatDetailText(call.inputs)} />
      ) : null}
      {call.output && !rich ? (
        <LabeledSection
          label="Output"
          content={formatDetailText(call.output)}
        />
      ) : null}
      <RawJsonToggle inputs={call.inputs} output={call.output} />
    </ScrollView>
  );
}

/** Task/Result card inside a subagent body — compact labelled panel. */
function DetailCard({ label, content }: { label: string; content: string }) {
  return (
    <View
      style={{
        backgroundColor: PANEL_BG,
        borderRadius: CARD_RADIUS,
        padding: CARD_PADDING,
      }}
    >
      <Text
        style={{
          fontSize: 11,
          fontWeight: "500",
          color: colors.zinc500,
          marginBottom: GAP.xs,
        }}
      >
        {label}
      </Text>
      <Text
        numberOfLines={TASK_MAX_LINES}
        style={{ fontSize: 11, lineHeight: 16, color: colors.zinc400 }}
      >
        {content}
      </Text>
    </View>
  );
}

function ConnectorLine() {
  return (
    <View
      style={{
        width: 1,
        flex: 1,
        minHeight: GAP.xl,
        backgroundColor: colors.zinc800,
      }}
    />
  );
}

/** One chronological activity row: 20px status column, one-line title + preview. */
function ActivityRow({
  call,
  isLast,
  approvals,
}: {
  call: ActivityToolCall;
  isLast: boolean;
  approvals: ApprovalLookup;
}) {
  const [detailOpen, setDetailOpen] = useState(false);
  const status = callStatus(call);

  const awaitingApproval =
    call.tool_call_id != null &&
    approvals.pendingToolCallIds.has(call.tool_call_id);
  const settledStatus =
    call.tool_call_id != null
      ? approvals.statusByToolCallId.get(call.tool_call_id)
      : undefined;

  const title = humanToolTitle(call.tool_name);
  const preview = previewForCall(call);
  const hasDetail =
    Boolean(call.output) ||
    (!!call.inputs && Object.keys(call.inputs).length > 0);

  return (
    <View>
      <Pressable
        onPress={() => {
          if (!hasDetail) return;
          selectionHaptic();
          setDetailOpen((v) => !v);
        }}
        disabled={!hasDetail}
        style={({ pressed }) => ({
          opacity: pressed ? 0.7 : 1,
        })}
      >
        <View
          style={{ minHeight: ROW_HEIGHT, flexDirection: "row", gap: GAP.md }}
        >
          <View
            style={{
              width: DOT_CONTAINER_SIZE,
              alignItems: "center",
              alignSelf: "stretch",
            }}
          >
            <View style={{ height: ROW_HEIGHT, justifyContent: "center" }}>
              <CategoryIcon
                category={call.tool_category || "general"}
                iconUrl={call.icon_url}
                size={16}
              />
            </View>
            {!isLast ? <ConnectorLine /> : null}
          </View>
          <View style={{ flex: 1, minWidth: 0, justifyContent: "center" }}>
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: GAP.sm,
                minHeight: ROW_HEIGHT,
                flexWrap: "wrap",
              }}
            >
              <StatusDot status={status} />
              <Text
                numberOfLines={1}
                style={{
                  flexShrink: 1,
                  fontSize: 12,
                  fontWeight: "500",
                  color: colors.zinc400,
                }}
              >
                {title}
              </Text>
              {awaitingApproval ? <WaitingForApprovalPill /> : null}
              {settledStatus ? (
                <ApprovalOutcomeChip status={settledStatus} />
              ) : null}
            </View>
            {preview ? (
              <Text
                numberOfLines={1}
                style={{
                  fontSize: 11,
                  color: colors.zinc500,
                  marginTop: GAP.xs,
                }}
              >
                {preview}
              </Text>
            ) : null}
          </View>
        </View>
      </Pressable>
      {detailOpen && hasDetail ? (
        <Animated.View entering={FadeIn.duration(FADE_MS)}>
          <RowDetail call={call} />
        </Animated.View>
      ) : null}
    </View>
  );
}

/** A model thinking step: italic label + collapsible detail card. */
function ThinkingRow({
  content,
  isLast,
}: {
  content: string;
  isLast: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { progress, collapseStyle, measureHandler } = useMeasuredCollapse(open);

  return (
    <View>
      <Pressable
        onPress={() => {
          selectionHaptic();
          setOpen((v) => !v);
        }}
        hitSlop={GAP.md}
        style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
      >
        <View
          style={{ minHeight: ROW_HEIGHT, flexDirection: "row", gap: GAP.md }}
        >
          <View
            style={{
              width: DOT_CONTAINER_SIZE,
              alignItems: "center",
              alignSelf: "stretch",
            }}
          >
            <View style={{ height: ROW_HEIGHT, justifyContent: "center" }}>
              <AppIcon icon={Brain02Icon} size={16} color={colors.zinc500} />
            </View>
            {!isLast ? <ConnectorLine /> : null}
          </View>
          <View
            style={{
              flex: 1,
              minWidth: 0,
              flexDirection: "row",
              alignItems: "center",
              gap: GAP.xs,
              height: ROW_HEIGHT,
            }}
          >
            <Text
              style={{
                fontSize: 12,
                fontWeight: "500",
                fontStyle: "italic",
                color: colors.zinc500,
              }}
            >
              Thinking
            </Text>
            <CollapseChevron progress={progress} />
          </View>
        </View>
      </Pressable>
      <Animated.View style={collapseStyle}>
        <View onLayout={measureHandler}>
          <View
            style={{
              marginTop: GAP.xs,
              marginBottom: GAP.lg,
              backgroundColor: PANEL_BG,
              borderRadius: CARD_RADIUS,
              padding: CARD_PADDING,
            }}
          >
            <Text
              style={{
                fontFamily: MONO_FONT,
                fontSize: 11,
                lineHeight: 18,
                color: colors.zinc400,
              }}
            >
              {content}
            </Text>
          </View>
        </View>
      </Animated.View>
    </View>
  );
}

function countGroupTools(group: EnrichedSubagentGroup): number {
  let total = group.tool_calls.filter((tc) => tc.reasoning == null).length;
  for (const nested of group.nested_subagents) {
    total += countGroupTools(nested as EnrichedSubagentGroup);
  }
  return total;
}

/**
 * Nested subagent block. While running (completed_at is null and the turn's
 * stream is live) it auto-expands; completed groups start collapsed. A user
 * tap stores an override that wins over the automation from then on.
 * Indentation caps at MAX_INDENT_DEPTH levels — deeper groups flatten to the
 * same indent with their ancestor chain prefixed onto the name.
 */
function SubagentBlock({
  group,
  turnRunning,
  approvals,
  depth,
  namePrefix = "",
}: {
  group: EnrichedSubagentGroup;
  /** Whether the owning turn's stream is still open. */
  turnRunning: boolean;
  approvals: ApprovalLookup;
  depth: number;
  namePrefix?: string;
}) {
  const running = group.completed_at === null && turnRunning;
  // null = follow the running automation; a tap sets an explicit value.
  const [override, setOverride] = useState<boolean | null>(null);
  const expanded = override ?? running;
  const { progress, collapseStyle, measureHandler } =
    useMeasuredCollapse(expanded);

  const toggle = useCallback(() => {
    selectionHaptic();
    setOverride((prev) => !(prev ?? running));
  }, [running]);

  const toolCount = countGroupTools(group);
  const childRows = group.tool_calls;
  const nested = group.nested_subagents;
  const indent = Math.min(depth + 1, MAX_INDENT_DEPTH) * SUBAGENT_INDENT;
  const flattenNested = depth + 1 >= MAX_INDENT_DEPTH;

  const fullName = `${namePrefix}${group.subagent_name}`;

  return (
    <View>
      <Pressable
        onPress={toggle}
        hitSlop={GAP.md}
        style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
      >
        {running ? (
          <View
            style={{
              minHeight: ROW_HEIGHT,
              flexDirection: "row",
              alignItems: "center",
              gap: GAP.sm,
            }}
          >
            <Text
              numberOfLines={1}
              style={{
                flexShrink: 1,
                fontSize: 12,
                fontWeight: "500",
                color: colors.zinc400,
              }}
            >
              {fullName}
            </Text>
            <PulsingDot size={5} color={colors.zinc400} />
            <View style={{ marginLeft: "auto" }}>
              <CollapseChevron progress={progress} />
            </View>
          </View>
        ) : (
          <View style={{ minHeight: ROW_HEIGHT, justifyContent: "center" }}>
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: GAP.sm,
              }}
            >
              <Text
                numberOfLines={1}
                style={{
                  flexShrink: 1,
                  fontSize: 12,
                  fontWeight: "500",
                  color: colors.zinc200,
                }}
              >
                {fullName}
              </Text>
              {group.duration_ms != null ? (
                <Text
                  style={{
                    fontSize: 11,
                    color: colors.zinc500,
                    fontVariant: ["tabular-nums"],
                    flexShrink: 0,
                  }}
                >
                  {(group.duration_ms / 1000).toFixed(1)}s
                </Text>
              ) : null}
              <View style={{ marginLeft: "auto" }}>
                <CollapseChevron progress={progress} />
              </View>
            </View>
            <Text
              style={{
                fontSize: 11,
                lineHeight: 14,
                color: colors.zinc600,
                marginTop: GAP.xs,
              }}
            >
              Subagent · {toolCount} tool{toolCount === 1 ? "" : "s"}
            </Text>
          </View>
        )}
      </Pressable>

      <Animated.View style={[collapseStyle, { paddingLeft: indent }]}>
        <View onLayout={measureHandler} style={{ paddingTop: GAP.xs }}>
          {group.handoff_input ? (
            <View style={{ marginBottom: GAP.md }}>
              <DetailCard label="Task" content={group.handoff_input} />
            </View>
          ) : null}

          {childRows.map((call, index) => {
            const key =
              call.tool_call_id != null
                ? `${group.subagent_id}-${call.tool_call_id}`
                : `${group.subagent_id}-reasoning-${
                    childRows.slice(0, index).filter((c) => c.reasoning != null)
                      .length
                  }`;
            const isLast =
              index === childRows.length - 1 && nested.length === 0;
            return call.reasoning != null ? (
              <ThinkingRow key={key} content={call.reasoning} isLast={isLast} />
            ) : (
              <ActivityRow
                key={key}
                call={call}
                approvals={approvals}
                isLast={isLast}
              />
            );
          })}

          {nested.map((nestedGroup) => (
            <SubagentBlock
              key={`nested-${nestedGroup.subagent_id}`}
              group={nestedGroup as EnrichedSubagentGroup}
              turnRunning={turnRunning}
              approvals={approvals}
              depth={depth + 1}
              namePrefix={flattenNested ? `${fullName} › ` : namePrefix}
            />
          ))}

          {group.handoff_output ? (
            <View style={{ marginTop: GAP.md }}>
              <DetailCard label="Result" content={group.handoff_output} />
            </View>
          ) : null}
        </View>
      </Animated.View>
    </View>
  );
}

export interface ActivityBlockProps {
  /** Raw streamed tool data for the turn (tool_calls_data, subagent_group, approval_request, …). */
  toolData: ToolDataEntry[];
  /** Turn still streaming. */
  isRunning: boolean;
  /** Text/markdown already accumulating below the block. */
  hasStreamedText?: boolean;
  /** Turn errored — failure blocks auto-collapse until the next user turn. */
  failed?: boolean;
  /** Live progress label while no timeline items exist yet ("Checking email…"). */
  thinkingLabel?: string | null;
}

interface SummaryIconItem {
  category: string;
  iconUrl?: string;
}

/**
 * Persistent per-turn activity surface — an OBJECT, not a MODE. Rendered as
 * the first sibling of every AI turn; streamed text accumulates below it
 * simultaneously instead of the old mutually-exclusive surface swap.
 *
 * RUNNING shows a single live line (pulse + current step + elapsed ticker);
 * COMPLETED collapses to one tappable "Used N tools · Xs" row. The unified
 * chain only ever appears via explicit tap — expansion animates height
 * 0↔measured without adding/removing list items (FlashList-safe).
 */
export function ActivityBlock({
  toolData,
  isRunning,
  failed = false,
  thinkingLabel,
}: ActivityBlockProps) {
  const { spacing } = useResponsive();
  const [expanded, setExpanded] = useState(false);

  const working = isRunning && !failed;
  const seconds = useElapsedSeconds(working);

  const timeline = useMemo(() => buildTimeline(toolData), [toolData]);
  const approvals = useMemo(() => buildApprovalLookup(toolData), [toolData]);
  const totalCount = useMemo(() => countTimelineTools(timeline), [timeline]);

  const { progress, collapseStyle, measureHandler } =
    useMeasuredCollapse(expanded);

  const toggleExpanded = useCallback(() => {
    selectionHaptic();
    setExpanded((v) => !v);
    trackEvent(ANALYTICS_EVENTS.CHAT_ACTIVITY_TIMELINE_TOGGLED, {
      expanded: !expanded,
      totalCount,
      elapsedSeconds: seconds,
    });
  }, [expanded, totalCount, seconds]);

  const liveTitle = useMemo(() => {
    const last = timeline.at(-1);
    if (!last) return `${thinkingLabel ?? "Thinking"}…`;
    if (last.kind === "tool") return `${humanToolTitle(last.call.tool_name)}…`;
    if (last.kind === "subagent") return `${last.group.subagent_name}…`;
    return "Thinking…";
  }, [timeline, thinkingLabel]);

  const summaryIcons = useMemo(() => {
    const seen = new Set<string>();
    const unique: SummaryIconItem[] = [];
    for (const item of timeline) {
      if (item.kind === "thinking") continue;
      const category =
        item.kind === "subagent"
          ? (item.group.tool_category ?? "subagent")
          : item.call.tool_category || "general";
      if (seen.has(category)) continue;
      seen.add(category);
      unique.push({
        category,
        iconUrl:
          item.kind === "subagent"
            ? (item.group.icon_url ?? undefined)
            : item.call.icon_url,
      });
      if (unique.length >= MAX_SUMMARY_ICONS) break;
    }
    return unique;
  }, [timeline]);

  if (timeline.length === 0 && !working) return null;

  const renderTimelineItem = (
    item: (typeof timeline)[number],
    index: number,
  ) => {
    const isLast = index === timeline.length - 1;
    if (item.kind === "tool") {
      return (
        <ActivityRow
          key={`tool-${item.call.tool_call_id ?? index}`}
          call={item.call}
          approvals={approvals}
          isLast={isLast}
        />
      );
    }
    if (item.kind === "thinking") {
      return (
        <ThinkingRow
          key={`think-${index}`}
          content={item.content}
          isLast={isLast}
        />
      );
    }
    return (
      <SubagentBlock
        key={`sa-${item.group.subagent_id}`}
        group={item.group}
        turnRunning={working}
        approvals={approvals}
        depth={0}
      />
    );
  };

  return (
    <View
      style={{
        paddingHorizontal: spacing.md,
        alignSelf: "stretch",
        width: "100%",
      }}
    >
      {working ? (
        <Pressable
          onPress={toggleExpanded}
          hitSlop={GAP.md}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            gap: GAP.sm,
            height: ROW_HEIGHT,
            opacity: pressed ? 0.6 : 1,
          })}
        >
          <PulsingDot size={6} color={colors.zinc400} />
          <Text
            numberOfLines={1}
            style={{
              flexShrink: 1,
              fontSize: typography.fontSize.xs,
              fontWeight: "500",
              color: colors.zinc400,
            }}
          >
            {liveTitle}
          </Text>
          <Text
            style={{
              fontSize: 11,
              color: colors.zinc500,
              marginLeft: "auto",
              fontVariant: ["tabular-nums"],
            }}
          >
            {formatSeconds(seconds)}
          </Text>
          <CollapseChevron progress={progress} />
        </Pressable>
      ) : (
        <Pressable
          onPress={toggleExpanded}
          hitSlop={GAP.md}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            gap: GAP.sm,
            minHeight: ROW_HEIGHT - 2,
            opacity: pressed ? 0.6 : 1,
          })}
        >
          {summaryIcons.map((item) => (
            <View key={item.category}>
              <CategoryIcon
                category={item.category}
                iconUrl={item.iconUrl}
                size={14}
              />
            </View>
          ))}
          <Text
            numberOfLines={1}
            style={{
              flexShrink: 1,
              fontSize: typography.fontSize.xs,
              fontWeight: "500",
              color: colors.zinc500,
            }}
          >
            Used {totalCount} tool{totalCount === 1 ? "" : "s"}
          </Text>
          {seconds > 0 ? (
            <Text
              style={{
                fontSize: 11,
                color: colors.zinc500,
                fontVariant: ["tabular-nums"],
              }}
            >
              · {formatSeconds(seconds)}
            </Text>
          ) : null}
          <View style={{ marginLeft: "auto" }}>
            <CollapseChevron progress={progress} />
          </View>
        </Pressable>
      )}

      {/* Always mounted so onLayout can measure before/while expanding —
          no list items are added or removed (FlashList-safe). */}
      <Animated.View style={collapseStyle}>
        <View onLayout={measureHandler} style={{ paddingTop: GAP.sm }}>
          {timeline.map(renderTimelineItem)}
        </View>
      </Animated.View>
    </View>
  );
}
