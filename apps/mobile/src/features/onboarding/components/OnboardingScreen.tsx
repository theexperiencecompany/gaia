import * as Linking from "expo-linking";
import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Dimensions,
  FlatList,
  Pressable,
  View,
  type ViewToken,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { API_ORIGIN } from "@/lib/constants";
import { updateOnboardingPhase } from "../api/onboarding-api";
import type { OnboardingStep } from "../types";

// ─── Constants ───────────────────────────────────────────────────────────────

const { width: SCREEN_WIDTH } = Dimensions.get("window");

const C = {
  bg: "#060a14",
  cardBg: "#0d1117",
  border: "rgba(255,255,255,0.08)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.12)",
  primaryBorder: "rgba(0,187,255,0.3)",
  success: "#30d158",
  successBg: "rgba(48,209,88,0.12)",
  dotInactive: "rgba(255,255,255,0.2)",
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface IntegrationCard {
  id: string;
  name: string;
  logo: string;
  slug: string;
}

// ─── Data ────────────────────────────────────────────────────────────────────

const FEATURED_INTEGRATIONS: IntegrationCard[] = [
  {
    id: "googlecalendar",
    name: "Google Calendar",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/512px-Google_Calendar_icon_%282020%29.svg.png",
    slug: "googlecalendar",
  },
  {
    id: "slack",
    name: "Slack",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d5/Slack_icon_2019.svg/512px-Slack_icon_2019.svg.png",
    slug: "slack",
  },
  {
    id: "github",
    name: "GitHub",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/GitHub_Invertocat_Logo.svg/512px-GitHub_Invertocat_Logo.svg.png",
    slug: "github",
  },
  {
    id: "notion",
    name: "Notion",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/512px-Notion-logo.svg.png",
    slug: "notion",
  },
  {
    id: "gmail",
    name: "Gmail",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/512px-Gmail_icon_%282020%29.svg.png",
    slug: "gmail",
  },
  {
    id: "linear",
    name: "Linear",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Linear_logo.svg/512px-Linear_logo.svg.png",
    slug: "linear",
  },
];

const EXAMPLE_WORKFLOWS = [
  {
    id: "1",
    title: "Daily Briefing",
    description: "Get a morning summary of your calendar, emails, and tasks",
  },
  {
    id: "2",
    title: "Smart Notifications",
    description: "Triage and prioritize notifications based on your context",
  },
  {
    id: "3",
    title: "Meeting Prep",
    description:
      "Auto-generate meeting notes and action items from your calendar",
  },
];

// ─── Step Components ──────────────────────────────────────────────────────────

function WelcomeStep() {
  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 32,
      }}
    >
      <View
        style={{
          width: 96,
          height: 96,
          borderRadius: 24,
          backgroundColor: C.primaryBg,
          borderWidth: 1,
          borderColor: C.primaryBorder,
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 32,
        }}
      >
        <Text style={{ fontSize: 48 }}>G</Text>
      </View>
      <Text
        style={{
          fontSize: 32,
          fontWeight: "700",
          color: C.text,
          textAlign: "center",
          marginBottom: 16,
          letterSpacing: -0.5,
        }}
      >
        Welcome to GAIA
      </Text>
      <Text
        style={{
          fontSize: 17,
          color: C.textMuted,
          textAlign: "center",
          lineHeight: 26,
        }}
      >
        Your AI-powered personal assistant that connects your tools, automates
        your workflows, and keeps you in flow.
      </Text>
    </View>
  );
}

interface ConnectIntegrationStepProps {
  onIntegrationConnected: () => void;
}

function ConnectIntegrationStep({
  onIntegrationConnected,
}: ConnectIntegrationStepProps) {
  const [connecting, setConnecting] = useState<string | null>(null);
  const [connected, setConnected] = useState<Set<string>>(new Set());

  const handleConnect = useCallback(
    async (integration: IntegrationCard) => {
      setConnecting(integration.id);
      try {
        const redirectUri = Linking.createURL("integrations/callback");
        const authUrl = `${API_ORIGIN}/api/v1/integrations/login/${integration.slug}?redirect_path=${encodeURIComponent(redirectUri)}`;
        const result = await WebBrowser.openAuthSessionAsync(
          authUrl,
          redirectUri,
        );
        if (result.type === "success") {
          setConnected((prev) => new Set([...prev, integration.id]));
          onIntegrationConnected();
        }
      } catch {
        // Silently ignore connection errors in onboarding
      } finally {
        setConnecting(null);
      }
    },
    [onIntegrationConnected],
  );

  return (
    <View style={{ flex: 1, paddingHorizontal: 24 }}>
      <Text
        style={{
          fontSize: 28,
          fontWeight: "700",
          color: C.text,
          textAlign: "center",
          marginBottom: 8,
          letterSpacing: -0.3,
        }}
      >
        Connect your first app
      </Text>
      <Text
        style={{
          fontSize: 15,
          color: C.textMuted,
          textAlign: "center",
          marginBottom: 28,
          lineHeight: 22,
        }}
      >
        Link the tools you use every day so GAIA can work across your entire
        workflow.
      </Text>
      <View
        style={{
          flexDirection: "row",
          flexWrap: "wrap",
          gap: 12,
          justifyContent: "center",
        }}
      >
        {FEATURED_INTEGRATIONS.map((integration) => {
          const isConnected = connected.has(integration.id);
          const isConnecting = connecting === integration.id;
          return (
            <Pressable
              key={integration.id}
              onPress={() => handleConnect(integration)}
              disabled={isConnecting || isConnected}
              style={{
                width: (SCREEN_WIDTH - 72) / 3,
                backgroundColor: isConnected ? C.successBg : C.cardBg,
                borderWidth: 1,
                borderColor: isConnected ? C.success : C.primaryBorder,
                borderRadius: 16,
                padding: 16,
                alignItems: "center",
                gap: 8,
                opacity: isConnecting ? 0.7 : 1,
              }}
            >
              {isConnecting ? (
                <ActivityIndicator size="small" color={C.primary} />
              ) : (
                // eslint-disable-next-line @typescript-eslint/no-require-imports
                <View
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    backgroundColor: "rgba(255,255,255,0.05)",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Animated.Image
                    source={{ uri: integration.logo }}
                    style={{ width: 28, height: 28, borderRadius: 6 }}
                    resizeMode="contain"
                  />
                </View>
              )}
              <Text
                style={{
                  fontSize: 11,
                  color: isConnected ? C.success : C.text,
                  fontWeight: "500",
                  textAlign: "center",
                }}
                numberOfLines={1}
              >
                {isConnected ? "Connected" : integration.name}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

interface CreateWorkflowStepProps {
  onNavigateToWorkflows: () => void;
}

function CreateWorkflowStep({
  onNavigateToWorkflows,
}: CreateWorkflowStepProps) {
  return (
    <View style={{ flex: 1, paddingHorizontal: 24 }}>
      <Text
        style={{
          fontSize: 28,
          fontWeight: "700",
          color: C.text,
          textAlign: "center",
          marginBottom: 8,
          letterSpacing: -0.3,
        }}
      >
        Automate your work
      </Text>
      <Text
        style={{
          fontSize: 15,
          color: C.textMuted,
          textAlign: "center",
          marginBottom: 28,
          lineHeight: 22,
        }}
      >
        Workflows let GAIA take action on your behalf — from drafting emails to
        summarizing meetings.
      </Text>
      <View style={{ gap: 12 }}>
        {EXAMPLE_WORKFLOWS.map((workflow) => (
          <View
            key={workflow.id}
            style={{
              backgroundColor: C.cardBg,
              borderWidth: 1,
              borderColor: C.border,
              borderRadius: 16,
              padding: 16,
              flexDirection: "row",
              alignItems: "center",
              gap: 12,
            }}
          >
            <View
              style={{
                width: 40,
                height: 40,
                borderRadius: 12,
                backgroundColor: C.primaryBg,
                borderWidth: 1,
                borderColor: C.primaryBorder,
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Text style={{ fontSize: 18 }}>
                {workflow.id === "1" ? "☀️" : workflow.id === "2" ? "🔔" : "📝"}
              </Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text
                style={{
                  fontSize: 14,
                  fontWeight: "600",
                  color: C.text,
                  marginBottom: 2,
                }}
              >
                {workflow.title}
              </Text>
              <Text
                style={{ fontSize: 12, color: C.textMuted, lineHeight: 18 }}
              >
                {workflow.description}
              </Text>
            </View>
          </View>
        ))}
      </View>
      <Pressable
        onPress={onNavigateToWorkflows}
        style={{
          marginTop: 24,
          backgroundColor: C.primaryBg,
          borderWidth: 1,
          borderColor: C.primaryBorder,
          borderRadius: 14,
          paddingVertical: 14,
          alignItems: "center",
        }}
      >
        <Text style={{ fontSize: 15, fontWeight: "600", color: C.primary }}>
          Create Workflow
        </Text>
      </Pressable>
    </View>
  );
}

interface EnableNotificationsStepProps {
  onPermissionGranted: () => void;
}

function EnableNotificationsStep({
  onPermissionGranted,
}: EnableNotificationsStepProps) {
  const [isRequesting, setIsRequesting] = useState(false);
  const [permissionStatus, setPermissionStatus] = useState<
    "idle" | "granted" | "denied"
  >("idle");

  const handleAllow = useCallback(async () => {
    setIsRequesting(true);
    try {
      const { status } = await Notifications.requestPermissionsAsync();
      if (status === "granted") {
        setPermissionStatus("granted");
        onPermissionGranted();
      } else {
        setPermissionStatus("denied");
      }
    } catch {
      setPermissionStatus("denied");
    } finally {
      setIsRequesting(false);
    }
  }, [onPermissionGranted]);

  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 32,
      }}
    >
      <View
        style={{
          width: 96,
          height: 96,
          borderRadius: 24,
          backgroundColor: C.primaryBg,
          borderWidth: 1,
          borderColor: C.primaryBorder,
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 32,
        }}
      >
        <Text style={{ fontSize: 48 }}>🔔</Text>
      </View>
      <Text
        style={{
          fontSize: 28,
          fontWeight: "700",
          color: C.text,
          textAlign: "center",
          marginBottom: 16,
          letterSpacing: -0.3,
        }}
      >
        Never miss an update
      </Text>
      <Text
        style={{
          fontSize: 15,
          color: C.textMuted,
          textAlign: "center",
          lineHeight: 22,
          marginBottom: 40,
        }}
      >
        Get real-time alerts when GAIA completes tasks, surfaces insights, or
        needs your attention.
      </Text>
      {permissionStatus === "granted" ? (
        <View
          style={{
            backgroundColor: C.successBg,
            borderWidth: 1,
            borderColor: C.success,
            borderRadius: 14,
            paddingVertical: 14,
            paddingHorizontal: 32,
            alignItems: "center",
          }}
        >
          <Text style={{ fontSize: 15, fontWeight: "600", color: C.success }}>
            Notifications enabled
          </Text>
        </View>
      ) : (
        <Pressable
          onPress={handleAllow}
          disabled={isRequesting}
          style={{
            backgroundColor: C.primary,
            borderRadius: 14,
            paddingVertical: 14,
            paddingHorizontal: 48,
            alignItems: "center",
            opacity: isRequesting ? 0.7 : 1,
          }}
        >
          {isRequesting ? (
            <ActivityIndicator size="small" color="#000" />
          ) : (
            <Text style={{ fontSize: 15, fontWeight: "700", color: "#000" }}>
              Allow Notifications
            </Text>
          )}
        </Pressable>
      )}
      {permissionStatus === "denied" && (
        <Text
          style={{
            marginTop: 12,
            fontSize: 13,
            color: C.textMuted,
            textAlign: "center",
          }}
        >
          You can enable notifications later in Settings.
        </Text>
      )}
    </View>
  );
}

function CompleteStep() {
  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 32,
      }}
    >
      <View
        style={{
          width: 96,
          height: 96,
          borderRadius: 24,
          backgroundColor: C.successBg,
          borderWidth: 1,
          borderColor: C.success,
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 32,
        }}
      >
        <Text style={{ fontSize: 52 }}>🎉</Text>
      </View>
      <Text
        style={{
          fontSize: 32,
          fontWeight: "700",
          color: C.text,
          textAlign: "center",
          marginBottom: 16,
          letterSpacing: -0.5,
        }}
      >
        You're all set!
      </Text>
      <Text
        style={{
          fontSize: 17,
          color: C.textMuted,
          textAlign: "center",
          lineHeight: 26,
        }}
      >
        GAIA is ready to work for you. Ask anything, automate anything, and stay
        in flow.
      </Text>
    </View>
  );
}

// ─── Progress Dots ────────────────────────────────────────────────────────────

interface ProgressDotsProps {
  total: number;
  current: number;
}

function ProgressDots({ total, current }: ProgressDotsProps) {
  return (
    <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
      {Array.from({ length: total }).map((_, index) => (
        <View
          // biome-ignore lint/suspicious/noArrayIndexKey: static list
          key={index}
          style={{
            width: index === current ? 20 : 6,
            height: 6,
            borderRadius: 3,
            backgroundColor: index === current ? C.primary : C.dotInactive,
          }}
        />
      ))}
    </View>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

const STEPS: OnboardingStep[] = [
  "welcome",
  "connect_integration",
  "create_workflow",
  "enable_notifications",
  "complete",
];

const STEP_LABELS: Record<OnboardingStep, string> = {
  welcome: "Get Started",
  connect_integration: "Next",
  create_workflow: "Next",
  enable_notifications: "Next",
  complete: "Let's go!",
};

const SKIPPABLE_STEPS: Set<OnboardingStep> = new Set([
  "connect_integration",
  "create_workflow",
  "enable_notifications",
]);

export function OnboardingScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const flatListRef = useRef<FlatList<OnboardingStep>>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);

  const currentStep = STEPS[currentIndex];

  const scrollToIndex = useCallback((index: number) => {
    flatListRef.current?.scrollToIndex({ index, animated: true });
    setCurrentIndex(index);
  }, []);

  const handleNext = useCallback(async () => {
    const step = STEPS[currentIndex];
    setIsLoading(true);

    try {
      await updateOnboardingPhase(step, true).catch(() => {
        // Non-blocking: continue even if API fails
      });
    } finally {
      setIsLoading(false);
    }

    if (currentIndex < STEPS.length - 1) {
      scrollToIndex(currentIndex + 1);
    } else {
      // Mark complete and navigate
      try {
        await updateOnboardingPhase("complete", true).catch(() => {});
      } finally {
        router.replace("/(app)/(tabs)");
      }
    }
  }, [currentIndex, router, scrollToIndex]);

  const handleSkip = useCallback(async () => {
    const step = STEPS[currentIndex];
    await updateOnboardingPhase(step, false).catch(() => {});
    if (currentIndex < STEPS.length - 1) {
      scrollToIndex(currentIndex + 1);
    } else {
      router.replace("/(app)/(tabs)");
    }
  }, [currentIndex, router, scrollToIndex]);

  const handleNavigateToWorkflows = useCallback(() => {
    // Mark workflow step complete then navigate
    updateOnboardingPhase("create_workflow", true).catch(() => {});
    updateOnboardingPhase("complete", true).catch(() => {});
    router.replace("/(app)/(tabs)/workflows");
  }, [router]);

  const onViewableItemsChanged = useCallback(
    ({ viewableItems }: { viewableItems: ViewToken[] }) => {
      if (viewableItems.length > 0 && viewableItems[0].index !== null) {
        setCurrentIndex(viewableItems[0].index);
      }
    },
    [],
  );

  const viewabilityConfig = useRef({ viewAreaCoveragePercentThreshold: 50 });

  const renderItem = useCallback(
    ({ item }: { item: OnboardingStep }) => {
      return (
        <View style={{ width: SCREEN_WIDTH, flex: 1 }}>
          {item === "welcome" && <WelcomeStep />}
          {item === "connect_integration" && (
            <ConnectIntegrationStep
              onIntegrationConnected={() => {
                // Optionally auto-advance after first connection
              }}
            />
          )}
          {item === "create_workflow" && (
            <CreateWorkflowStep
              onNavigateToWorkflows={handleNavigateToWorkflows}
            />
          )}
          {item === "enable_notifications" && (
            <EnableNotificationsStep onPermissionGranted={() => {}} />
          )}
          {item === "complete" && <CompleteStep />}
        </View>
      );
    },
    [handleNavigateToWorkflows],
  );

  const isLastStep = currentIndex === STEPS.length - 1;
  const isSkippable = SKIPPABLE_STEPS.has(currentStep);

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: C.bg,
        paddingTop: insets.top,
        paddingBottom: insets.bottom,
      }}
    >
      <FlatList
        ref={flatListRef}
        data={STEPS}
        keyExtractor={(item) => item}
        renderItem={renderItem}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        scrollEnabled={false}
        onViewableItemsChanged={onViewableItemsChanged}
        viewabilityConfig={viewabilityConfig.current}
        style={{ flex: 1 }}
        contentContainerStyle={{ flexGrow: 1 }}
        getItemLayout={(_, index) => ({
          length: SCREEN_WIDTH,
          offset: SCREEN_WIDTH * index,
          index,
        })}
      />

      <View
        style={{
          paddingHorizontal: 24,
          paddingBottom: 16,
          paddingTop: 12,
          gap: 16,
          borderTopWidth: 1,
          borderTopColor: C.border,
        }}
      >
        <View style={{ alignItems: "center" }}>
          <ProgressDots total={STEPS.length} current={currentIndex} />
        </View>
        <Pressable
          onPress={handleNext}
          disabled={isLoading}
          style={{
            backgroundColor: C.primary,
            borderRadius: 14,
            paddingVertical: 15,
            alignItems: "center",
            opacity: isLoading ? 0.7 : 1,
          }}
        >
          {isLoading ? (
            <ActivityIndicator size="small" color="#000" />
          ) : (
            <Text style={{ fontSize: 16, fontWeight: "700", color: "#000" }}>
              {isLastStep ? "Let's go!" : STEP_LABELS[currentStep]}
            </Text>
          )}
        </Pressable>
        {isSkippable && !isLastStep && (
          <Pressable onPress={handleSkip} style={{ alignItems: "center" }}>
            <Text
              style={{ fontSize: 14, color: C.textMuted, fontWeight: "500" }}
            >
              Skip for now
            </Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}
