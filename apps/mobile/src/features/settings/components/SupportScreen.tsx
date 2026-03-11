import * as WebBrowser from "expo-web-browser";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  CustomerSupportIcon,
  DocumentAttachmentIcon,
  GlobeIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { apiService } from "@/lib/api";
import { useResponsive } from "@/lib/responsive";

type SupportCategory = "bug_report" | "feature_request" | "general";

interface SupportRequest {
  type: SupportCategory;
  title: string;
  description: string;
}

interface SupportResponse {
  success: boolean;
  message: string;
  ticket_id?: string;
}

const CATEGORIES: { value: SupportCategory; label: string }[] = [
  { value: "bug_report", label: "Bug Report" },
  { value: "feature_request", label: "Feature Request" },
  { value: "general", label: "General" },
];

const C = {
  bg: "#131416",
  sectionBg: "#171920",
  divider: "rgba(255,255,255,0.06)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.15)",
  primaryBorder: "rgba(0,187,255,0.35)",
  success: "#22c55e",
  successBg: "rgba(34,197,94,0.12)",
};

interface SupportScreenProps {
  onBack: () => void;
}

export function SupportScreen({ onBack }: SupportScreenProps) {
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState<SupportCategory>("general");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [ticketId, setTicketId] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    if (!subject.trim()) {
      Alert.alert("Missing Subject", "Please enter a subject for your ticket.");
      return;
    }
    if (!description.trim()) {
      Alert.alert(
        "Missing Description",
        "Please describe your issue or request.",
      );
      return;
    }

    setIsSubmitting(true);
    try {
      const body: SupportRequest = {
        type: category,
        title: subject.trim(),
        description: description.trim(),
      };
      const result = await apiService.post<SupportResponse>(
        "/support/requests",
        body,
      );
      if (result.success) {
        setTicketId(result.ticket_id ?? null);
        setSubmitted(true);
      } else {
        Alert.alert("Error", result.message || "Failed to submit ticket.");
      }
    } catch {
      Alert.alert(
        "Error",
        "Failed to submit support ticket. Please try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }, [subject, category, description]);

  const handleViewDocs = useCallback(async () => {
    await WebBrowser.openBrowserAsync("https://heygaia.io/docs");
  }, []);

  if (submitted) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: C.bg,
          paddingTop: insets.top,
          paddingBottom: insets.bottom,
        }}
      >
        <View
          style={{
            paddingTop: spacing.xl * 2,
            paddingHorizontal: spacing.md,
            paddingBottom: spacing.md,
            borderBottomWidth: 1,
            borderBottomColor: C.divider,
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.md,
          }}
        >
          <Pressable
            onPress={onBack}
            accessibilityRole="button"
            accessibilityLabel="Go back"
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(255,255,255,0.05)",
            }}
          >
            <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>
          <Text style={{ fontSize: fontSize.base, fontWeight: "600" }}>
            Contact Support
          </Text>
        </View>

        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: spacing.xl,
            gap: spacing.lg,
          }}
        >
          <View
            style={{
              width: 64,
              height: 64,
              borderRadius: 32,
              backgroundColor: C.successBg,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon icon={CustomerSupportIcon} size={28} color={C.success} />
          </View>
          <Text
            style={{
              fontSize: fontSize.xl,
              fontWeight: "700",
              color: C.text,
              textAlign: "center",
            }}
          >
            Ticket Submitted!
          </Text>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: C.textMuted,
              textAlign: "center",
              lineHeight: 22,
            }}
          >
            {ticketId
              ? `Your support ticket has been received. Ticket ID: ${ticketId}`
              : "Your support ticket has been received. We'll get back to you soon."}
          </Text>
          <Pressable
            onPress={onBack}
            accessibilityRole="button"
            accessibilityLabel="Return to settings"
            style={{
              backgroundColor: C.primary,
              borderRadius: 12,
              paddingHorizontal: spacing.xl,
              paddingVertical: spacing.md,
            }}
          >
            <Text
              style={{
                color: "#000",
                fontWeight: "600",
                fontSize: fontSize.sm,
              }}
            >
              Back to Settings
            </Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: C.bg,
        paddingTop: insets.top,
        paddingBottom: insets.bottom,
      }}
    >
      {/* Header */}
      <View
        style={{
          paddingTop: spacing.xl * 2,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: C.divider,
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.md,
        }}
      >
        <Pressable
          onPress={onBack}
          accessibilityRole="button"
          accessibilityLabel="Go back"
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
        </Pressable>
        <Text style={{ fontSize: fontSize.base, fontWeight: "600" }}>
          Contact Support
        </Text>
      </View>

      <ScrollView
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.lg,
        }}
        keyboardShouldPersistTaps="handled"
      >
        {/* View Documentation */}
        <Pressable
          onPress={() => {
            void handleViewDocs();
          }}
          accessibilityRole="button"
          accessibilityLabel="View documentation"
          accessibilityHint="Opens the Gaia documentation in your browser"
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            backgroundColor: C.sectionBg,
            borderRadius: 12,
            padding: spacing.md,
          }}
        >
          <AppIcon icon={GlobeIcon} size={18} color={C.primary} />
          <View style={{ flex: 1 }}>
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: C.primary,
              }}
            >
              View Documentation
            </Text>
            <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
              Find answers in our help center
            </Text>
          </View>
          <AppIcon
            icon={DocumentAttachmentIcon}
            size={16}
            color={C.textMuted}
          />
        </Pressable>

        {/* Subject */}
        <View style={{ gap: spacing.xs }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              fontWeight: "600",
              color: C.textMuted,
              textTransform: "uppercase",
              letterSpacing: 0.8,
              paddingHorizontal: 4,
            }}
          >
            Subject
          </Text>
          <TextInput
            value={subject}
            onChangeText={setSubject}
            placeholder="Brief description of your issue"
            placeholderTextColor="#555"
            accessibilityLabel="Subject"
            accessibilityHint="Enter a brief subject for your support request"
            style={{
              backgroundColor: C.sectionBg,
              borderRadius: 12,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.md,
              fontSize: fontSize.sm,
              color: C.text,
            }}
          />
        </View>

        {/* Category */}
        <View style={{ gap: spacing.xs }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              fontWeight: "600",
              color: C.textMuted,
              textTransform: "uppercase",
              letterSpacing: 0.8,
              paddingHorizontal: 4,
            }}
          >
            Category
          </Text>
          <View
            style={{
              flexDirection: "row",
              gap: spacing.sm,
            }}
          >
            {CATEGORIES.map(({ value, label }) => {
              const isActive = category === value;
              return (
                <Pressable
                  key={value}
                  onPress={() => setCategory(value)}
                  accessibilityRole="button"
                  accessibilityLabel={label}
                  accessibilityState={{ selected: isActive }}
                  style={{
                    flex: 1,
                    borderRadius: 10,
                    paddingVertical: spacing.sm + 2,
                    alignItems: "center",
                    backgroundColor: isActive ? C.primaryBg : C.sectionBg,
                    borderWidth: 1,
                    borderColor: isActive ? C.primaryBorder : "transparent",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      color: isActive ? C.primary : C.textMuted,
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

        {/* Description */}
        <View style={{ gap: spacing.xs }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              fontWeight: "600",
              color: C.textMuted,
              textTransform: "uppercase",
              letterSpacing: 0.8,
              paddingHorizontal: 4,
            }}
          >
            Description
          </Text>
          <TextInput
            value={description}
            onChangeText={setDescription}
            placeholder="Please describe your issue in detail..."
            placeholderTextColor="#555"
            multiline
            numberOfLines={6}
            textAlignVertical="top"
            accessibilityLabel="Description"
            accessibilityHint="Describe your issue or request in detail"
            style={{
              backgroundColor: C.sectionBg,
              borderRadius: 12,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.md,
              fontSize: fontSize.sm,
              color: C.text,
              minHeight: 140,
            }}
          />
        </View>

        {/* Submit */}
        <Pressable
          onPress={() => {
            void handleSubmit();
          }}
          disabled={isSubmitting}
          accessibilityRole="button"
          accessibilityLabel="Submit support ticket"
          accessibilityState={{ disabled: isSubmitting }}
          style={{
            backgroundColor: C.primary,
            borderRadius: 12,
            paddingVertical: spacing.md,
            alignItems: "center",
            opacity: isSubmitting ? 0.6 : 1,
          }}
        >
          {isSubmitting ? (
            <ActivityIndicator color="#000" />
          ) : (
            <Text
              style={{
                color: "#000",
                fontWeight: "600",
                fontSize: fontSize.base,
              }}
            >
              Submit Ticket
            </Text>
          )}
        </Pressable>
      </ScrollView>
    </View>
  );
}
