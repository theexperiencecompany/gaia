import { Button, Card, Chip, Spinner, TextField } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import { Alert, ScrollView, View } from "react-native";
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
        <Spinner />
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
      <Card variant="secondary" className="rounded-3xl bg-surface">
        <Card.Body className="gap-5 px-5 py-5">
          <SectionHeader>Profession</SectionHeader>
          <View
            style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}
          >
            {PROFESSIONS.map((p) => {
              const isActive = prefs.profession === p;
              return (
                <Chip
                  key={p}
                  onPress={() =>
                    setPrefs((prev) => ({ ...prev, profession: p }))
                  }
                  variant={isActive ? "primary" : "secondary"}
                  color={isActive ? "accent" : "default"}
                  className={isActive ? "" : "bg-white/10"}
                >
                  {p}
                </Chip>
              );
            })}
          </View>

          <SectionHeader>Response Style</SectionHeader>
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            {RESPONSE_STYLES.map(({ value, label }) => {
              const isActive = prefs.response_style === value;
              return (
                <Chip
                  key={value}
                  onPress={() =>
                    setPrefs((prev) => ({ ...prev, response_style: value }))
                  }
                  variant={isActive ? "primary" : "secondary"}
                  color={isActive ? "accent" : "default"}
                  className="flex-1 justify-center py-3"
                >
                  {label}
                </Chip>
              );
            })}
          </View>

          <SectionHeader>Custom Instructions</SectionHeader>
          <TextField>
            <TextField.Input
              value={customInstructions}
              onChangeText={setCustomInstructions}
              placeholder="Tell GAIA how you'd like it to respond…"
              multiline
              numberOfLines={4}
              style={{ minHeight: 100 }}
            />
          </TextField>

          <SectionHeader>Timezone</SectionHeader>
          <Card variant="secondary" className="rounded-2xl bg-secondary">
            <Card.Body className="px-4 py-4">
              <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
                {timezone}
              </Text>
            </Card.Body>
          </Card>
          <Text style={{ fontSize: fontSize.xs - 1, color: "#5a5a5e" }}>
            Auto-detected from your device.
          </Text>
        </Card.Body>
      </Card>

      <Button
        onPress={() => {
          void handleSave();
        }}
        isDisabled={isSaving}
        className="bg-primary"
      >
        {isSaving ? <Spinner /> : <Button.Label>Save Preferences</Button.Label>}
      </Button>
    </ScrollView>
  );
}
