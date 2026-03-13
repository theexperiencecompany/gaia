import {
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { ActivityIndicator, Alert, Pressable, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  ConnectIcon,
  FlashIcon,
  PuzzleIcon,
  ShieldUserIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import {
  type CreateCustomIntegrationParams,
  createCustomIntegration,
  type TestConnectionResponse,
  testIntegrationConnection,
} from "../api/integrations-api";
import { TestConnectionResult } from "./TestConnectionResult";

export interface CreateMCPIntegrationSheetRef {
  open: () => void;
  close: () => void;
}

interface CreateMCPIntegrationSheetProps {
  onIntegrationCreated?: (integrationId: string) => void;
}

type AuthType = "none" | "bearer";

interface FormState {
  name: string;
  description: string;
  serverUrl: string;
  authType: AuthType;
  bearerToken: string;
}

const INITIAL_FORM: FormState = {
  name: "",
  description: "",
  serverUrl: "",
  authType: "none",
  bearerToken: "",
};

function validateUrl(url: string): boolean {
  return /^https?:\/\/.+/.test(url.trim());
}

export const CreateMCPIntegrationSheet = forwardRef<
  CreateMCPIntegrationSheetRef,
  CreateMCPIntegrationSheetProps
>(({ onIntegrationCreated }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const { fontSize, spacing, moderateScale } = useResponsive();

  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(
    null,
  );
  const [testError, setTestError] = useState<string | null>(null);
  const [savedIntegrationId, setSavedIntegrationId] = useState<string | null>(
    null,
  );

  const snapPoints = useMemo(
    () => (form.authType === "bearer" ? ["85%"] : ["75%"]),
    [form.authType],
  );

  useImperativeHandle(ref, () => ({
    open: () => {
      setIsOpen(true);
    },
    close: () => {
      setIsOpen(false);
    },
  }));

  const handleClose = useCallback(() => {
    setIsOpen(false);
  }, []);

  const handleDismiss = useCallback(() => {
    setForm(INITIAL_FORM);
    setTestResult(null);
    setTestError(null);
    setSavedIntegrationId(null);
    setIsSaving(false);
    setIsTesting(false);
  }, []);

  const updateField = useCallback(
    <K extends keyof FormState>(field: K, value: FormState[K]) => {
      setForm((prev) => ({ ...prev, [field]: value }));
      // Clear test result when form changes (except when toggling auth type in a way
      // that doesn't change the actual connection parameters)
      if (field !== "authType" || value !== "none") {
        setTestResult(null);
        setTestError(null);
        setSavedIntegrationId(null);
      }
    },
    [],
  );

  const handleSave = useCallback(async () => {
    if (!form.name.trim()) {
      Alert.alert("Validation Error", "Name is required.");
      return;
    }
    if (!form.serverUrl.trim()) {
      Alert.alert("Validation Error", "Server URL is required.");
      return;
    }
    if (!validateUrl(form.serverUrl)) {
      Alert.alert(
        "Validation Error",
        "Please enter a valid URL starting with http:// or https://",
      );
      return;
    }

    setIsSaving(true);
    try {
      const params: CreateCustomIntegrationParams = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        server_url: form.serverUrl.trim(),
        requires_auth: form.authType === "bearer" && !!form.bearerToken.trim(),
        auth_type: form.authType,
        is_public: false,
        bearer_token:
          form.authType === "bearer" && form.bearerToken.trim()
            ? form.bearerToken.trim()
            : undefined,
      };

      const result = await createCustomIntegration(params);
      setSavedIntegrationId(result.integrationId);

      // If the backend auto-connected, surface that result
      if (result.connection) {
        const conn = result.connection;
        const testResp: TestConnectionResponse = {
          status:
            conn.status === "connected"
              ? "connected"
              : conn.status === "requires_oauth"
                ? "requires_oauth"
                : "failed",
          tools_count: conn.toolsCount,
          error: conn.error,
        };
        setTestResult(testResp);
      }

      onIntegrationCreated?.(result.integrationId);
      handleClose();
    } catch (err) {
      Alert.alert(
        "Error",
        err instanceof Error ? err.message : "Failed to create integration.",
      );
    } finally {
      setIsSaving(false);
    }
  }, [form, onIntegrationCreated, handleClose]);

  const handleTestConnection = useCallback(async () => {
    if (!savedIntegrationId) {
      // Save first if not saved yet
      if (!form.name.trim()) {
        Alert.alert(
          "Save First",
          "Please fill in the name and save before testing.",
        );
        return;
      }
      if (!validateUrl(form.serverUrl)) {
        Alert.alert(
          "Validation Error",
          "Please enter a valid URL starting with http:// or https://",
        );
        return;
      }

      setIsSaving(true);
      try {
        const params: CreateCustomIntegrationParams = {
          name: form.name.trim(),
          description: form.description.trim() || undefined,
          server_url: form.serverUrl.trim(),
          requires_auth:
            form.authType === "bearer" && !!form.bearerToken.trim(),
          auth_type: form.authType,
          is_public: false,
          bearer_token:
            form.authType === "bearer" && form.bearerToken.trim()
              ? form.bearerToken.trim()
              : undefined,
        };
        const created = await createCustomIntegration(params);
        setSavedIntegrationId(created.integrationId);
        onIntegrationCreated?.(created.integrationId);

        setIsSaving(false);
        setIsTesting(true);
        setTestResult(null);
        setTestError(null);

        try {
          const response = await testIntegrationConnection(
            created.integrationId,
          );
          setTestResult(response);
        } catch (testErr) {
          setTestError(
            testErr instanceof Error
              ? testErr.message
              : "Connection test failed.",
          );
        } finally {
          setIsTesting(false);
        }
      } catch (err) {
        setIsSaving(false);
        Alert.alert(
          "Error",
          err instanceof Error ? err.message : "Failed to create integration.",
        );
      }
      return;
    }

    setIsTesting(true);
    setTestResult(null);
    setTestError(null);

    try {
      const response = await testIntegrationConnection(savedIntegrationId);
      setTestResult(response);
    } catch (err) {
      setTestError(
        err instanceof Error ? err.message : "Connection test failed.",
      );
    } finally {
      setIsTesting(false);
    }
  }, [savedIntegrationId, form, onIntegrationCreated]);

  const inputStyle = {
    flex: 1,
    color: "#f4f4f5",
    fontSize: fontSize.sm,
    padding: 0,
  };

  const fieldWrapperStyle = {
    backgroundColor: "rgba(255,255,255,0.06)",
    borderRadius: moderateScale(12, 0.5),
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    gap: 4,
  };

  const fieldLabelStyle = {
    fontSize: fontSize.xs,
    color: "#8e8e93",
    fontWeight: "500" as const,
  };

  const isFormBusy = isSaving || isTesting;

  return (
    <BottomSheet
      isOpen={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        if (!open) handleDismiss();
      }}
    >
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={snapPoints}
          enableDynamicSizing={false}
          enablePanDownToClose={!isFormBusy}
          backgroundStyle={{ backgroundColor: "#131416" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          {/* Header */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.md,
              borderBottomWidth: 1,
              borderBottomColor: "rgba(255,255,255,0.06)",
            }}
          >
            <View style={{ gap: 2 }}>
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#fff",
                }}
              >
                New MCP Integration
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
                Connect an MCP server to extend GAIA&apos;s capabilities
              </Text>
            </View>
            <Pressable
              onPress={handleClose}
              disabled={isFormBusy}
              style={{
                width: 32,
                height: 32,
                borderRadius: 999,
                backgroundColor: "rgba(255,255,255,0.06)",
                alignItems: "center",
                justifyContent: "center",
                opacity: isFormBusy ? 0.4 : 1,
              }}
            >
              <AppIcon icon={Cancel01Icon} size={16} color="#8e8e93" />
            </Pressable>
          </View>

          <BottomSheetScrollView
            contentContainerStyle={{
              padding: spacing.md,
              gap: spacing.sm + 4,
              paddingBottom: spacing.xl * 2,
            }}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {/* Name */}
            <View style={fieldWrapperStyle}>
              <Text style={fieldLabelStyle}>Name *</Text>
              <View
                style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
              >
                <AppIcon icon={PuzzleIcon} size={15} color="#6f737c" />
                <BottomSheetTextInput
                  style={inputStyle}
                  placeholder="My Integration"
                  placeholderTextColor="#6f737c"
                  value={form.name}
                  onChangeText={(v) => updateField("name", v)}
                  editable={!isFormBusy}
                  returnKeyType="next"
                />
              </View>
            </View>

            {/* Description */}
            <View style={fieldWrapperStyle}>
              <Text style={fieldLabelStyle}>Description</Text>
              <BottomSheetTextInput
                style={{ ...inputStyle, minHeight: 48 }}
                placeholder="What does this integration do?"
                placeholderTextColor="#6f737c"
                value={form.description}
                onChangeText={(v) => updateField("description", v)}
                multiline
                editable={!isFormBusy}
                textAlignVertical="top"
              />
            </View>

            {/* Server URL */}
            <View style={fieldWrapperStyle}>
              <Text style={fieldLabelStyle}>Server URL *</Text>
              <View
                style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
              >
                <AppIcon icon={ConnectIcon} size={15} color="#6f737c" />
                <BottomSheetTextInput
                  style={inputStyle}
                  placeholder="https://mcp.example.com/sse"
                  placeholderTextColor="#6f737c"
                  value={form.serverUrl}
                  onChangeText={(v) => updateField("serverUrl", v)}
                  editable={!isFormBusy}
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="url"
                  returnKeyType="next"
                />
              </View>
            </View>

            {/* Auth Type */}
            <View style={{ gap: spacing.xs }}>
              <Text style={{ ...fieldLabelStyle, paddingHorizontal: 2 }}>
                Authentication
              </Text>
              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                {(["none", "bearer"] as AuthType[]).map((type) => {
                  const isSelected = form.authType === type;
                  return (
                    <Pressable
                      key={type}
                      onPress={() => updateField("authType", type)}
                      disabled={isFormBusy}
                      style={{
                        flex: 1,
                        paddingVertical: spacing.sm + 2,
                        borderRadius: moderateScale(10, 0.5),
                        alignItems: "center",
                        backgroundColor: isSelected
                          ? "rgba(0,187,255,0.15)"
                          : "rgba(255,255,255,0.06)",
                        borderWidth: 1,
                        borderColor: isSelected
                          ? "rgba(0,187,255,0.4)"
                          : "transparent",
                      }}
                    >
                      <Text
                        style={{
                          fontSize: fontSize.sm,
                          fontWeight: isSelected ? "600" : "400",
                          color: isSelected ? "#00bbff" : "#8e8e93",
                        }}
                      >
                        {type === "none" ? "None" : "Bearer Token"}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            {/* Bearer Token (conditional) */}
            {form.authType === "bearer" && (
              <View style={fieldWrapperStyle}>
                <Text style={fieldLabelStyle}>Bearer Token</Text>
                <View
                  style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
                >
                  <AppIcon icon={ShieldUserIcon} size={15} color="#6f737c" />
                  <BottomSheetTextInput
                    style={inputStyle}
                    placeholder="sk-... or your API token"
                    placeholderTextColor="#6f737c"
                    value={form.bearerToken}
                    onChangeText={(v) => updateField("bearerToken", v)}
                    secureTextEntry
                    editable={!isFormBusy}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                </View>
              </View>
            )}

            {/* Test Result */}
            {(isTesting || testResult !== null || testError !== null) && (
              <TestConnectionResult
                isLoading={isTesting}
                result={testResult}
                error={testError}
              />
            )}

            {/* Action Buttons */}
            <View
              style={{ flexDirection: "row", gap: spacing.sm, marginTop: 4 }}
            >
              {/* Test Connection */}
              <Pressable
                onPress={() => void handleTestConnection()}
                disabled={isFormBusy || !form.serverUrl.trim()}
                style={({ pressed }) => ({
                  flex: 1,
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                  paddingVertical: spacing.sm + 4,
                  borderRadius: moderateScale(12, 0.5),
                  backgroundColor:
                    isTesting || !form.serverUrl.trim()
                      ? "rgba(255,255,255,0.04)"
                      : pressed
                        ? "rgba(255,255,255,0.08)"
                        : "rgba(255,255,255,0.06)",
                  opacity: isFormBusy && !isTesting ? 0.5 : 1,
                })}
              >
                {isTesting ? (
                  <ActivityIndicator size="small" color="#8e8e93" />
                ) : (
                  <AppIcon
                    icon={FlashIcon}
                    size={15}
                    color={form.serverUrl.trim() ? "#8e8e93" : "#4a4a4e"}
                  />
                )}
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: "500",
                    color: form.serverUrl.trim() ? "#8e8e93" : "#4a4a4e",
                  }}
                >
                  Test
                </Text>
              </Pressable>

              {/* Save */}
              <Pressable
                onPress={() => void handleSave()}
                disabled={
                  isFormBusy || !form.name.trim() || !form.serverUrl.trim()
                }
                style={({ pressed }) => ({
                  flex: 2,
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                  paddingVertical: spacing.sm + 4,
                  borderRadius: moderateScale(12, 0.5),
                  backgroundColor:
                    !form.name.trim() || !form.serverUrl.trim() || isFormBusy
                      ? "rgba(0,187,255,0.3)"
                      : pressed
                        ? "rgba(0,170,230,0.9)"
                        : "rgba(0,187,255,0.85)",
                })}
              >
                {isSaving ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "600",
                      color: "#fff",
                    }}
                  >
                    Save Integration
                  </Text>
                )}
              </Pressable>
            </View>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

CreateMCPIntegrationSheet.displayName = "CreateMCPIntegrationSheet";
