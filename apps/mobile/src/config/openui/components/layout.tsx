import { defineComponent, useTriggerAction } from "@openuidev/react-lang";
import React from "react";
import {
  LayoutAnimation,
  Platform,
  Pressable,
  UIManager,
  View,
} from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { z } from "zod";
import {
  AppIcon,
  ArrowDown01Icon,
  ArrowRight01Icon,
  Cancel01Icon,
  CheckmarkCircle01Icon,
  File01Icon,
  Folder02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  Card,
  InnerCard,
  ItemTitle,
  MutedText,
  SectionTitle,
  STATUS_DOT_COLOR,
  StatusPill,
  SubtleText,
} from "./primitives";

if (
  Platform.OS === "android" &&
  UIManager.setLayoutAnimationEnabledExperimental
) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

export const dataCardSchema = z.object({
  title: z.string(),
  fields: z.array(z.object({ label: z.string(), value: z.string() })),
});

export const resultListSchema = z.object({
  items: z.array(
    z.object({
      title: z.string(),
      subtitle: z.string().optional(),
      body: z.string().optional(),
      url: z.string().optional(),
      badge: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const comparisonTableSchema = z.object({
  leftLabel: z.string(),
  rightLabel: z.string(),
  rows: z.array(
    z.object({
      label: z.string(),
      left: z.string(),
      right: z.string(),
      highlight: z.boolean().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const statusCardSchema = z.object({
  title: z.string(),
  status: z.enum(["success", "error", "warning", "info", "pending"]),
  message: z.string().optional(),
  detail: z.string().optional(),
});

export const actionCardSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
  actions: z
    .array(
      z.object({
        label: z.string(),
        type: z.literal("continue_conversation"),
        value: z.string(),
      }),
    )
    .optional(),
});

export const tagGroupSchema = z.object({
  tags: z.array(
    z.object({
      label: z.string(),
      color: z
        .enum(["default", "primary", "success", "warning", "danger"])
        .optional(),
    }),
  ),
  title: z.string().optional(),
});

export const fileTreeSchema = z.object({
  items: z.array(
    z.object({
      path: z.string(),
      type: z.enum(["file", "dir"]),
      size: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const accordionSchema = z.object({
  items: z.array(z.object({ label: z.string(), content: z.string() })),
  title: z.string().optional(),
});

export const tabsBlockSchema = z.object({
  tabs: z.array(z.object({ label: z.string(), content: z.string() })),
});

export const progressListSchema = z.object({
  items: z.array(
    z.object({
      label: z.string(),
      value: z.number(),
      max: z.number().optional(),
      color: z
        .enum(["default", "primary", "success", "warning", "danger"])
        .optional(),
    }),
  ),
  title: z.string().optional(),
});

export const selectableListSchema = z.object({
  options: z.array(
    z.object({
      label: z.string(),
      description: z.string().optional(),
      value: z.string(),
      badge: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
  description: z.string().optional(),
});

export const avatarListSchema = z.object({
  items: z.array(
    z.object({
      name: z.string(),
      role: z.string().optional(),
      description: z.string().optional(),
      initials: z.string().optional(),
      color: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

export const kbdBlockSchema = z.object({
  shortcuts: z.array(
    z.object({ keys: z.array(z.string()), description: z.string() }),
  ),
  title: z.string().optional(),
});

const PROGRESS_BAR_COLOR: Record<string, string> = {
  default: "#71717a",
  primary: "#00bbff",
  success: "#34d399",
  warning: "#fbbf24",
  danger: "#f87171",
};

const AVATAR_PALETTE = [
  "#00bbff",
  "#f472b6",
  "#34d399",
  "#fbbf24",
  "#a78bfa",
  "#f87171",
  "#60a5fa",
];

function deriveInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
}

function colorForName(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0;
  }
  const idx = Math.abs(hash) % AVATAR_PALETTE.length;
  return AVATAR_PALETTE[idx];
}

type FileTreeNode = {
  name: string;
  type: "file" | "dir";
  size?: string;
  children: Record<string, FileTreeNode>;
};

function buildFileTree(
  items: Array<{ path: string; type: "file" | "dir"; size?: string }>,
): Record<string, FileTreeNode> {
  const root: Record<string, FileTreeNode> = {};
  for (const item of items) {
    const parts = item.path.replace(/\/$/, "").split("/").filter(Boolean);
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!current[part]) {
        current[part] = {
          name: part,
          type: isLast ? item.type : "dir",
          size: isLast ? item.size : undefined,
          children: {},
        };
      }
      current = current[part].children;
    }
  }
  return root;
}

function FileTreeNodeRow({
  node,
  depth,
}: {
  node: FileTreeNode;
  depth: number;
}) {
  const [open, setOpen] = React.useState(true);
  const isDir = node.type === "dir";
  const hasChildren = Object.keys(node.children).length > 0;
  const toggle = isDir && hasChildren ? () => setOpen((o) => !o) : undefined;

  return (
    <View>
      <Pressable
        onPress={toggle}
        disabled={!toggle}
        className="flex-row items-center justify-between rounded-lg px-2 py-1 active:bg-zinc-800/60"
        style={{ paddingLeft: 8 + depth * 16 }}
      >
        <View className="flex-row items-center gap-1.5 flex-1 min-w-0">
          {isDir && hasChildren ? (
            <AppIcon
              icon={open ? ArrowDown01Icon : ArrowRight01Icon}
              size={12}
              color="#71717a"
            />
          ) : (
            <View style={{ width: 12, height: 12 }} />
          )}
          <AppIcon
            icon={isDir ? Folder02Icon : File01Icon}
            size={16}
            color={isDir ? "#00bbff" : "#71717a"}
          />
          <Text
            numberOfLines={1}
            className={
              isDir
                ? "text-sm font-medium text-zinc-200 flex-1"
                : "text-sm text-zinc-400 flex-1"
            }
          >
            {node.name}
          </Text>
        </View>
        {!isDir && node.size ? (
          <Text className="text-xs text-zinc-500 ml-2">{node.size}</Text>
        ) : null}
      </Pressable>
      {isDir && open && hasChildren ? (
        <View>
          {Object.values(node.children).map((child) => (
            <FileTreeNodeRow key={child.name} node={child} depth={depth + 1} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

export function DataCardView(props: z.infer<typeof dataCardSchema>) {
  return (
    <Card>
      <SectionTitle>{props.title}</SectionTitle>
      <View className="gap-2">
        {props.fields.map((field, index) => (
          <View
            key={`${field.label}-${index}`}
            className="rounded-2xl bg-zinc-900 p-3 flex-row items-center justify-between gap-4"
          >
            <SubtleText>{field.label}</SubtleText>
            <ItemTitle>{field.value}</ItemTitle>
          </View>
        ))}
      </View>
    </Card>
  );
}

export function ResultListView(props: z.infer<typeof resultListSchema>) {
  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View className="gap-2">
        {props.items.map((item) => (
          <InnerCard key={item.title}>
            <View className="flex-row items-start justify-between gap-2">
              <View className="flex-1">
                <ItemTitle>{item.title}</ItemTitle>
              </View>
              {item.badge ? (
                <View className="rounded-full bg-zinc-700/50 px-2 py-0.5">
                  <Text className="text-xs text-zinc-400">{item.badge}</Text>
                </View>
              ) : null}
            </View>
            {item.subtitle ? (
              <View className="mt-1">
                <MutedText>{item.subtitle}</MutedText>
              </View>
            ) : null}
            {item.body ? (
              <View className="mt-1">
                <MutedText>{item.body}</MutedText>
              </View>
            ) : null}
            {item.url ? (
              <View className="flex-row items-center gap-1 mt-1.5">
                <Text
                  numberOfLines={1}
                  className="text-xs text-zinc-500 flex-1"
                >
                  {item.url}
                </Text>
                <AppIcon icon={ArrowRight01Icon} size={12} color="#52525b" />
              </View>
            ) : null}
          </InnerCard>
        ))}
      </View>
    </Card>
  );
}

function ComparisonCell({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  if (normalized === "yes") {
    return <AppIcon icon={CheckmarkCircle01Icon} size={16} color="#34d399" />;
  }
  if (normalized === "no") {
    return (
      <AppIcon icon={Cancel01Icon} size={16} color="rgba(248, 113, 113, 0.7)" />
    );
  }
  return <Text className="text-xs text-zinc-200">{value}</Text>;
}

export function ComparisonTableView(
  props: z.infer<typeof comparisonTableSchema>,
) {
  return (
    <View className="w-full">
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View className="rounded-2xl bg-zinc-900 overflow-hidden">
        <View className="flex-row border-b border-zinc-800 px-3 py-2.5">
          <View style={{ flex: 0.7 }} />
          <View style={{ flex: 1 }}>
            <Text className="text-xs font-semibold text-zinc-200">
              {props.leftLabel}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text className="text-xs font-semibold text-zinc-200">
              {props.rightLabel}
            </Text>
          </View>
        </View>
        {props.rows.map((row) => (
          <View
            key={row.label}
            className={`flex-row px-3 py-2 ${
              row.highlight ? "bg-[#00bbff]/5" : ""
            }`}
          >
            <View style={{ flex: 0.7 }}>
              <Text className="text-xs text-zinc-500">{row.label}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <ComparisonCell value={row.left} />
            </View>
            <View style={{ flex: 1 }}>
              <ComparisonCell value={row.right} />
            </View>
          </View>
        ))}
      </View>
    </View>
  );
}

function PulsingStatusDot({ color }: { color: string }) {
  const scale = useSharedValue(1);
  const opacity = useSharedValue(0.5);

  React.useEffect(() => {
    scale.value = withRepeat(
      withTiming(2.2, { duration: 1000, easing: Easing.out(Easing.ease) }),
      -1,
      false,
    );
    opacity.value = withRepeat(
      withTiming(0, { duration: 1000, easing: Easing.out(Easing.ease) }),
      -1,
      false,
    );
  }, [scale, opacity]);

  const pingStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    opacity: opacity.value,
  }));

  return (
    <View
      style={{
        width: 10,
        height: 10,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Animated.View
        pointerEvents="none"
        style={[
          pingStyle,
          {
            position: "absolute",
            width: 10,
            height: 10,
            borderRadius: 5,
            backgroundColor: color,
          },
        ]}
      />
      <View
        style={{
          width: 10,
          height: 10,
          borderRadius: 5,
          backgroundColor: color,
        }}
      />
    </View>
  );
}

export function StatusCardView(props: z.infer<typeof statusCardSchema>) {
  const dotColor = STATUS_DOT_COLOR[props.status] ?? "#71717a";
  const label = props.status.charAt(0).toUpperCase() + props.status.slice(1);
  // Web renders info pill with primary (cyan) colors, not blue-400.
  // Map info -> primary and error -> danger for the pill kind.
  const pillKind =
    props.status === "error"
      ? "danger"
      : props.status === "info"
        ? "primary"
        : props.status;
  const isPending = props.status === "pending";
  return (
    <Card>
      <View className="flex-row items-center gap-2 mb-2">
        {isPending ? (
          <PulsingStatusDot color={dotColor} />
        ) : (
          <View
            style={{
              width: 10,
              height: 10,
              borderRadius: 5,
              backgroundColor: dotColor,
            }}
          />
        )}
        <View className="flex-1">
          <ItemTitle>{props.title}</ItemTitle>
        </View>
        <StatusPill kind={pillKind}>{label}</StatusPill>
      </View>
      {props.message ? (
        <Text className="text-sm text-zinc-200 mt-1">{props.message}</Text>
      ) : null}
      {props.detail ? (
        <View className="mt-1">
          <SubtleText>{props.detail}</SubtleText>
        </View>
      ) : null}
    </Card>
  );
}

export function ActionCardView(props: z.infer<typeof actionCardSchema>) {
  const triggerAction = useTriggerAction();

  const handlePress = (value: string) => {
    triggerAction(value, undefined, {
      type: "continue_conversation",
      params: {},
    });
  };

  return (
    <Card>
      <Text className="text-sm font-semibold text-zinc-100 mb-1">
        {props.title}
      </Text>
      {props.description ? (
        <View className="mb-3">
          <MutedText>{props.description}</MutedText>
        </View>
      ) : null}
      {props.actions && props.actions.length > 0 ? (
        <View className="flex-row flex-wrap gap-2 mt-3">
          {props.actions.map((action) => (
            <Pressable
              key={action.value}
              onPress={() => handlePress(action.value)}
              className="rounded-full bg-zinc-800 px-3 py-1.5 active:bg-zinc-700"
            >
              {({ pressed }) => (
                <Text
                  className={
                    pressed
                      ? "text-xs font-medium text-zinc-100"
                      : "text-xs font-medium text-zinc-200"
                  }
                >
                  {action.label}
                </Text>
              )}
            </Pressable>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

export function TagGroupView(props: z.infer<typeof tagGroupSchema>) {
  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View className="flex-row flex-wrap gap-2">
        {props.tags.map((tag) => (
          <StatusPill key={tag.label} kind={tag.color ?? "default"}>
            {tag.label}
          </StatusPill>
        ))}
      </View>
    </Card>
  );
}

export function FileTreeView(props: z.infer<typeof fileTreeSchema>) {
  const tree = buildFileTree(props.items);
  return (
    <View className="rounded-2xl bg-zinc-900 p-3 w-full">
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View>
        {Object.values(tree).map((node) => (
          <FileTreeNodeRow key={node.name} node={node} depth={0} />
        ))}
      </View>
    </View>
  );
}

function AccordionRow({
  label,
  content,
  open,
  onToggle,
}: {
  label: string;
  content: string;
  open: boolean;
  onToggle: () => void;
}) {
  const rotation = useSharedValue(open ? 1 : 0);

  React.useEffect(() => {
    rotation.value = withTiming(open ? 1 : 0, { duration: 180 });
  }, [open, rotation]);

  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value * 90}deg` }],
  }));

  return (
    <View className="border-b border-zinc-800/60">
      <Pressable
        onPress={onToggle}
        className="flex-row items-center justify-between py-4"
      >
        <View className="flex-1 pr-2">
          <ItemTitle>{label}</ItemTitle>
        </View>
        <Animated.View style={chevronStyle}>
          <AppIcon icon={ArrowRight01Icon} size={14} color="#a1a1aa" />
        </Animated.View>
      </Pressable>
      {open ? (
        <View className="pb-2">
          <Text className="text-xs text-zinc-400">{content}</Text>
        </View>
      ) : null}
    </View>
  );
}

export function AccordionView(props: z.infer<typeof accordionSchema>) {
  const [openIndex, setOpenIndex] = React.useState<Set<number>>(new Set());

  const toggle = (idx: number) => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setOpenIndex((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <View className="rounded-2xl bg-zinc-800 px-3 w-full">
      {props.title ? (
        <Text className="text-sm font-semibold text-zinc-100 pt-3 pb-2">
          {props.title}
        </Text>
      ) : null}
      {props.items.map((item, idx) => (
        <AccordionRow
          key={item.label}
          label={item.label}
          content={item.content}
          open={openIndex.has(idx)}
          onToggle={() => toggle(idx)}
        />
      ))}
    </View>
  );
}

export function TabsBlockView(props: z.infer<typeof tabsBlockSchema>) {
  const [active, setActive] = React.useState(0);
  const activeTab = props.tabs[active];

  return (
    <View className="w-full">
      <View className="self-start rounded-full bg-zinc-800 p-1 mb-3">
        <View className="flex-row">
          {props.tabs.map((tab, idx) => {
            const isActive = idx === active;
            return (
              <Pressable
                key={tab.label}
                onPress={() => setActive(idx)}
                className={`rounded-full px-3 py-1.5 ${
                  isActive ? "bg-zinc-800" : "bg-transparent"
                }`}
              >
                <Text
                  className={
                    isActive
                      ? "text-xs font-medium text-zinc-100"
                      : "text-xs font-medium text-zinc-400"
                  }
                >
                  {tab.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>
      {activeTab ? (
        <View className="rounded-2xl bg-zinc-800/50 p-4">
          <Text className="text-sm text-zinc-200">{activeTab.content}</Text>
        </View>
      ) : null}
    </View>
  );
}

export function ProgressListView(props: z.infer<typeof progressListSchema>) {
  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View className="gap-2">
        {props.items.map((item) => {
          const max = item.max ?? 100;
          const pct = Math.min(100, Math.round((item.value / max) * 100));
          const barColor =
            PROGRESS_BAR_COLOR[item.color ?? "primary"] ??
            PROGRESS_BAR_COLOR.primary;
          return (
            <InnerCard key={item.label}>
              <View className="flex-row items-center justify-between mb-1.5">
                <ItemTitle>{item.label}</ItemTitle>
                <SubtleText>{`${pct}%`}</SubtleText>
              </View>
              <View
                className="w-full rounded-full bg-zinc-700/60 overflow-hidden"
                style={{ height: 6 }}
              >
                <View
                  style={{
                    width: `${pct}%`,
                    height: "100%",
                    backgroundColor: barColor,
                    borderRadius: 999,
                  }}
                />
              </View>
            </InnerCard>
          );
        })}
      </View>
    </Card>
  );
}

export function SelectableListView(
  props: z.infer<typeof selectableListSchema>,
) {
  const [selected, setSelected] = React.useState<string>("");
  const triggerAction = useTriggerAction();

  const handleSelect = (value: string) => {
    setSelected(value);
    triggerAction(value, undefined, {
      type: "continue_conversation",
      params: {},
    });
  };

  return (
    <Card>
      {props.title ? (
        <Text className="text-sm font-semibold text-zinc-100 mb-1">
          {props.title}
        </Text>
      ) : null}
      {props.description ? (
        <View className="mb-3">
          <MutedText>{props.description}</MutedText>
        </View>
      ) : null}
      <View className="gap-2">
        {props.options.map((option) => {
          const isSelected = selected === option.value;
          return (
            <Pressable
              key={option.value}
              onPress={() => handleSelect(option.value)}
              className={`rounded-2xl p-3 ${
                isSelected
                  ? "bg-[#00bbff]/20"
                  : "bg-zinc-900 active:bg-zinc-900/70"
              }`}
            >
              <View className="flex-row items-center gap-2">
                <View
                  style={{
                    width: 16,
                    height: 16,
                    borderRadius: 8,
                    borderWidth: 2,
                    borderColor: isSelected ? "#00bbff" : "#52525b",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {isSelected ? (
                    <View
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: "#00bbff",
                      }}
                    />
                  ) : null}
                </View>
                <View className="flex-1 flex-row items-center gap-2">
                  <ItemTitle>{option.label}</ItemTitle>
                  {option.badge ? (
                    <View className="rounded-full bg-zinc-700/50 px-2 py-0.5">
                      <Text className="text-xs text-zinc-400">
                        {option.badge}
                      </Text>
                    </View>
                  ) : null}
                </View>
              </View>
              {option.description ? (
                <View className="mt-1 ml-6">
                  <MutedText>{option.description}</MutedText>
                </View>
              ) : null}
            </Pressable>
          );
        })}
      </View>
    </Card>
  );
}

function Avatar({
  name,
  initials,
  color,
  stacked,
}: {
  name: string;
  initials?: string;
  color?: string;
  stacked?: boolean;
}) {
  const text = initials ?? deriveInitials(name);
  const bg = color ?? colorForName(name);
  return (
    <View
      style={{
        width: 32,
        height: 32,
        borderRadius: 16,
        backgroundColor: bg,
        alignItems: "center",
        justifyContent: "center",
        marginLeft: stacked ? -8 : 0,
        borderWidth: stacked ? 2 : 0,
        borderColor: "#27272a",
      }}
    >
      <Text className="text-xs font-semibold text-zinc-900">{text}</Text>
    </View>
  );
}

function AvatarOverflow({ count }: { count: number }) {
  return (
    <View
      style={{
        width: 32,
        height: 32,
        borderRadius: 16,
        backgroundColor: "#3f3f46",
        alignItems: "center",
        justifyContent: "center",
        marginLeft: -8,
        borderWidth: 2,
        borderColor: "#27272a",
      }}
    >
      <Text className="text-xs font-semibold text-zinc-200">{`+${count}`}</Text>
    </View>
  );
}

export function AvatarListView(props: z.infer<typeof avatarListSchema>) {
  const hasDetails = props.items.some((item) => item.role || item.description);
  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      {hasDetails ? (
        <View className="gap-2">
          {props.items.map((item) => (
            <View key={item.name} className="flex-row items-center gap-3">
              <Avatar
                name={item.name}
                initials={item.initials}
                color={item.color}
              />
              <View className="flex-1">
                <ItemTitle>{item.name}</ItemTitle>
                {item.role ? <MutedText>{item.role}</MutedText> : null}
                {item.description ? (
                  <SubtleText>{item.description}</SubtleText>
                ) : null}
              </View>
            </View>
          ))}
        </View>
      ) : (
        <View className="flex-row">
          {props.items.slice(0, 7).map((item, idx) => (
            <Avatar
              key={item.name}
              name={item.name}
              initials={item.initials}
              color={item.color}
              stacked={idx > 0}
            />
          ))}
          {props.items.length > 7 ? (
            <AvatarOverflow count={props.items.length - 7} />
          ) : null}
        </View>
      )}
    </Card>
  );
}

export function KbdBlockView(props: z.infer<typeof kbdBlockSchema>) {
  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View className="gap-2">
        {props.shortcuts.map((shortcut) => (
          <View
            key={shortcut.description}
            className="rounded-2xl bg-zinc-900 p-3 flex-row items-center justify-between gap-4"
          >
            <View className="flex-1">
              <MutedText>{shortcut.description}</MutedText>
            </View>
            <View className="flex-row items-center gap-1">
              {shortcut.keys.map((key) => (
                <View
                  key={key}
                  className="rounded-md bg-zinc-800 px-1.5 py-0.5"
                >
                  <Text className="text-xs font-mono text-zinc-200">{key}</Text>
                </View>
              ))}
            </View>
          </View>
        ))}
      </View>
    </Card>
  );
}

export const dataCardDef = defineComponent({
  name: "DataCard",
  description: "Single record fields as label-value pairs.",
  props: dataCardSchema,
  component: ({ props }) => React.createElement(DataCardView, props),
});

export const resultListDef = defineComponent({
  name: "ResultList",
  description: "List of results with title, subtitle, body, url, badge.",
  props: resultListSchema,
  component: ({ props }) => React.createElement(ResultListView, props),
});

export const comparisonTableDef = defineComponent({
  name: "ComparisonTable",
  description: "A vs B comparison table.",
  props: comparisonTableSchema,
  component: ({ props }) => React.createElement(ComparisonTableView, props),
});

export const statusCardDef = defineComponent({
  name: "StatusCard",
  description: "Operation result card with status indicator.",
  props: statusCardSchema,
  component: ({ props }) => React.createElement(StatusCardView, props),
});

export const actionCardDef = defineComponent({
  name: "ActionCard",
  description: "Next-step suggestions with action buttons.",
  props: actionCardSchema,
  component: ({ props }) => React.createElement(ActionCardView, props),
});

export const tagGroupDef = defineComponent({
  name: "TagGroup",
  description: "Flat set of labeled chips/tags.",
  props: tagGroupSchema,
  component: ({ props }) => React.createElement(TagGroupView, props),
});

export const fileTreeDef = defineComponent({
  name: "FileTree",
  description: "Directory or file listing.",
  props: fileTreeSchema,
  component: ({ props }) => React.createElement(FileTreeView, props),
});

export const accordionDef = defineComponent({
  name: "Accordion",
  description: "Collapsible sections with label and content.",
  props: accordionSchema,
  component: ({ props }) => React.createElement(AccordionView, props),
});

export const tabsBlockDef = defineComponent({
  name: "TabsBlock",
  description: "Tabbed content panels.",
  props: tabsBlockSchema,
  component: ({ props }) => React.createElement(TabsBlockView, props),
});

export const progressListDef = defineComponent({
  name: "ProgressList",
  description: "Labeled progress bars.",
  props: progressListSchema,
  component: ({ props }) => React.createElement(ProgressListView, props),
});

export const selectableListDef = defineComponent({
  name: "SelectableList",
  description: "Selectable options with radio group.",
  props: selectableListSchema,
  component: ({ props }) => React.createElement(SelectableListView, props),
});

export const avatarListDef = defineComponent({
  name: "AvatarList",
  description: "People list with avatars.",
  props: avatarListSchema,
  component: ({ props }) => React.createElement(AvatarListView, props),
});

export const kbdBlockDef = defineComponent({
  name: "KbdBlock",
  description: "Keyboard shortcut reference table.",
  props: kbdBlockSchema,
  component: ({ props }) => React.createElement(KbdBlockView, props),
});
