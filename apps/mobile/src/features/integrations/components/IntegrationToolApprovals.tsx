import { toolAsks } from "@gaia/shared/chat";
import { useMemo } from "react";
import { Alert, Pressable, Switch, View } from "react-native";
import { AppIcon, ShieldUserIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useHilPreferences } from "@/features/settings/hooks/use-hil-preferences";
import { useResponsive } from "@/lib/responsive";

export interface ToolEntry {
  name: string;
  label: string;
  destructive: boolean;
}

interface IntegrationToolApprovalsProps {
  entries: ToolEntry[];
}

/**
 * Connected-integration tool list as a per-tool approval checklist. A switch on
 * puts the tool in the gated set — the set that `always_ask` prompts on and
 * `auto` runs the intent judge over. When approvals are off the same rows render
 * read-only with a turn-on prompt, so the view never changes shape.
 */
export function IntegrationToolApprovals({
  entries,
}: IntegrationToolApprovalsProps) {
  const { fontSize, spacing } = useResponsive();
  const { prefs, setMode, setToolApproval } = useHilPreferences();
  const disabled = prefs.mode === "always_allow";

  const handleEnable = async () => {
    const ok = await setMode("always_ask");
    if (!ok) Alert.alert("Error", "Failed to turn on approvals.");
  };

  const ordered = useMemo(
    () =>
      [...entries].sort(
        (a, b) => Number(b.destructive) - Number(a.destructive),
      ),
    [entries],
  );

  return (
    <View style={{ gap: spacing.sm }}>
      <Text
        className="text-zinc-400"
        style={{ fontSize: fontSize.xs, fontWeight: "500", marginBottom: 2 }}
      >
        Tool approvals ({entries.length})
      </Text>

      {disabled ? (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            backgroundColor: "rgba(255,255,255,0.06)",
            borderRadius: 12,
            paddingHorizontal: 12,
            paddingVertical: 8,
          }}
        >
          <Text
            className="text-zinc-400"
            style={{ fontSize: fontSize.xs, flex: 1 }}
          >
            Approvals are off — GAIA won't ask before running these.
          </Text>
          <Pressable onPress={handleEnable} hitSlop={8}>
            <Text style={{ fontSize: fontSize.xs, color: "#16c1ff" }}>
              Turn on
            </Text>
          </Pressable>
        </View>
      ) : (
        <Text
          className="text-zinc-500"
          style={{ fontSize: fontSize.xs - 1, marginTop: -2 }}
        >
          Choose which tools need approval before running.
        </Text>
      )}

      <View>
        {ordered.map((tool) => {
          const ask = toolAsks(prefs, tool.name, tool.destructive);
          return (
            <View
              key={tool.name}
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                paddingVertical: 8,
              }}
            >
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  flex: 1,
                  minWidth: 0,
                }}
              >
                <AppIcon
                  icon={ShieldUserIcon}
                  size={15}
                  color={ask ? "#f59e0b" : "#52525b"}
                />
                <Text
                  className="text-zinc-200"
                  numberOfLines={1}
                  style={{ fontSize: fontSize.sm, flex: 1 }}
                >
                  {tool.label}
                </Text>
              </View>
              <Switch
                value={ask}
                onValueChange={(v) =>
                  setToolApproval(tool.name, v, tool.destructive)
                }
                disabled={disabled}
                trackColor={{ false: "#3a3a3c", true: "rgba(22,193,255,0.6)" }}
                thumbColor={ask ? "#16c1ff" : "#71717a"}
              />
            </View>
          );
        })}
      </View>
    </View>
  );
}
