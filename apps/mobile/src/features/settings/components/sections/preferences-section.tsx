import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { Text } from "@/components/ui/text";
import type { OnboardingPreferences } from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

const PROFESSIONS = [
  "Software Engineer",
  "Product Manager",
  "Designer",
  "Data Scientist",
  "Marketing",
  "Student",
  "Other",
];

const RESPONSE_STYLES = [
  { value: "concise", label: "Concise" },
  { value: "detailed", label: "Detailed" },
  { value: "balanced", label: "Balanced" },
];

function SectionHeader({ children }: { children: string }) {
  const { fontSize, spacing } = useResponsive();
  return (
    <Text
      style={{
        fontSize: fontSize.xs,
        color: "#8e8e93",
        textTransform: "uppercase",
        letterSpacing: 1,
        marginBottom: spacing.xs,
      }}
    >
      {children}
    </Text>
  );
}

export function PreferencesSection() {
  const { spacing, fontSize } = useResponsive();

  const [prefs, setPrefs] = useState<OnboardingPreferences>({});
  const [customInstructions, setCustomInstructions] = useState("");
  const [timezone, setTimezone] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    settingsApi
      .getProfile()
      .then((profile) => {
        if (cancelled) return;
        const p = profile.onboarding?.preferences ?? {};
        setPrefs(p);
        setCustomInstructions(p.custom_instructions ?? "");
        setTimezone(
          profile.timezone ??
            (() => {
              try {
                return Intl.DateTimeFormat().resolvedOptions().timeZone;
              } catch {
                return "UTC";
              }
            })(),
        );
      })
      .catch(() => {
        if (!cancelled) {
          Alert.alert("Error", "Failed to load preferences.");
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    try {
      await Promise.all([
        settingsApi.updatePreferences({
          ...prefs,
          custom_instructions: customInstructions.trim() || null,
        }),
        settingsApi.updateTimezone(timezone),
      ]);
      Alert.alert("Saved", "Preferences updated.");
    } catch {
      Alert.alert("Error", "Failed to save preferences.");
    } finally {
      setIsSaving(false);
    }
  }, [prefs, customInstructions, timezone]);

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color="#16c1ff" />
      </View>
    );
  }

  return (
    <ScrollView
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{
        padding: spacing.md,
        gap: spacing.lg,
        paddingBottom: 40,
      }}
    >
      {/* Profession */}
      <View style={{ gap: spacing.xs }}>
        <SectionHeader>Profession</SectionHeader>
        <View
          style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}
        >
          {PROFESSIONS.map((p) => {
            const isActive = prefs.profession === p;
            return (
              <Pressable
                key={p}
                onPress={() => setPrefs((prev) => ({ ...prev, profession: p }))}
                style={{
                  borderRadius: 999,
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.xs,
                  backgroundColor: isActive
                    ? "rgba(22,193,255,0.2)"
                    : "rgba(255,255,255,0.07)",
                  borderWidth: 1,
                  borderColor: isActive
                    ? "rgba(22,193,255,0.4)"
                    : "transparent",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isActive ? "#9fe6ff" : "#c5cad2",
                  }}
                >
                  {p}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Response Style */}
      <View style={{ gap: spacing.xs }}>
        <SectionHeader>Response Style</SectionHeader>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {RESPONSE_STYLES.map(({ value, label }) => {
            const isActive = prefs.response_style === value;
            return (
              <Pressable
                key={value}
                onPress={() =>
                  setPrefs((prev) => ({ ...prev, response_style: value }))
                }
                style={{
                  flex: 1,
                  borderRadius: 12,
                  paddingVertical: spacing.md,
                  alignItems: "center",
                  backgroundColor: isActive
                    ? "rgba(22,193,255,0.2)"
                    : "#1c1c1e",
                  borderWidth: 1,
                  borderColor: isActive
                    ? "rgba(22,193,255,0.4)"
                    : "transparent",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: isActive ? "#9fe6ff" : "#c5cad2",
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Custom Instructions */}
      <View style={{ gap: spacing.xs }}>
        <SectionHeader>Custom Instructions</SectionHeader>
        <TextInput
          value={customInstructions}
          onChangeText={setCustomInstructions}
          placeholder="Tell GAIA how you'd like it to respond…"
          placeholderTextColor="#6b6b6b"
          multiline
          numberOfLines={4}
          style={{
            backgroundColor: "#1c1c1e",
            borderRadius: 12,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            fontSize: fontSize.sm,
            color: "#ffffff",
            minHeight: 100,
            textAlignVertical: "top",
          }}
        />
      </View>

      {/* Timezone */}
      <View style={{ gap: spacing.xs }}>
        <SectionHeader>Timezone</SectionHeader>
        <View
          style={{
            backgroundColor: "#1c1c1e",
            borderRadius: 12,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
          }}
        >
          <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
            {timezone}
          </Text>
        </View>
        <Text style={{ fontSize: fontSize.xs - 1, color: "#5a5a5e" }}>
          Auto-detected from your device.
        </Text>
      </View>

      {/* Save */}
      <Pressable
        onPress={() => {
          void handleSave();
        }}
        disabled={isSaving}
        style={{
          backgroundColor: "#16c1ff",
          borderRadius: 12,
          paddingVertical: spacing.md,
          alignItems: "center",
          opacity: isSaving ? 0.6 : 1,
          marginTop: spacing.sm,
        }}
      >
        {isSaving ? (
          <ActivityIndicator color="#000" />
        ) : (
          <Text
            style={{
              color: "#000",
              fontWeight: "600",
              fontSize: fontSize.base,
            }}
          >
            Save Preferences
          </Text>
        )}
      </Pressable>
    </ScrollView>
  );
}
