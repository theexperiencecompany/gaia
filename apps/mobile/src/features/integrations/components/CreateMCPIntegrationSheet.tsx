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
  PuzzleIcon,
  ShieldUserIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import {
  type CreateCustomIntegrationParams,
  createCustomIntegration,
  updateCustomIntegration,
} from "../api/integrations-api";
import type { Integration } from "../types";

export interface CreateMCPIntegrationSheetRef {
  open: (integration?: Integration | null) => void;
  close: () => void;
}

interface CreateMCPIntegrationSheetProps {
  onIntegrationCreated?: (integrationId: string) => void;
  onIntegrationUpdated?: (integrationId: string) => void;
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
>(({ onIntegrationCreated, onIntegrationUpdated }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const { fontSize, spacing, moderateScale } = useResponsive();

  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const isEditing = editingId !== null;

  const snapPoints = useMemo(
    () => (form.authType === "bearer" ? ["88%"] : ["78%"]),
    [form.authType],
  );

  useImperativeHandle(ref, () => ({
    open: (integration?: Integration | null) => {
      if (integration && integration.source === "custom") {
        setEditingId(integration.id);
        setForm({
          name: integration.name,
          description: integration.description ?? "",
          // Server URL is not exposed via the integration list; users edit
          // the visible fields and re-paste the URL if they need to rotate it.
          serverUrl: "",
          authType: integration.authType === "bearer" ? "bearer" : "none",
          bearerToken: "",
        });
      } else {
        setEditingId(null);
        setForm(INITIAL_FORM);
      }
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
    setEditingId(null);
    setIsSaving(false);
  }, []);

  const updateField = useCallback(
    <K extends keyof FormState>(field: K, value: FormState[K]) => {
      setForm((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const handleSave = useCallback(async () => {
    if (!form.name.trim()) {
      Alert.alert("Validation Error", "Name is required.");
      return;
    }
    if (!isEditing) {
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
    } else if (form.serverUrl.trim() && !validateUrl(form.serverUrl)) {
      Alert.alert(
        "Validation Error",
        "Please enter a valid URL starting with http:// or https://",
      );
      return;
    }

    setIsSaving(true);
    try {
      if (isEditing && editingId) {
        const updates: Partial<CreateCustomIntegrationParams> = {
          name: form.name.trim(),
          description: form.description.trim() || undefined,
          auth_type: form.authType,
        };
        if (form.serverUrl.trim()) {
          updates.server_url = form.serverUrl.trim();
        }
        if (form.authType === "bearer" && form.bearerToken.trim()) {
          updates.bearer_token = form.bearerToken.trim();
          updates.requires_auth = true;
        }

        await updateCustomIntegration(editingId, updates);
        onIntegrationUpdated?.(editingId);
        handleClose();
        return;
      }

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

      onIntegrationCreated?.(result.integrationId);
      handleClose();
    } catch (err) {
      Alert.alert(
        "Error",
        err instanceof Error
          ? err.message
          : isEditing
            ? "Failed to update integration."
            : "Failed to create integration.",
      );
    } finally {
      setIsSaving(false);
    }
  }, [
    form,
    isEditing,
    editingId,
    onIntegrationCreated,
    onIntegrationUpdated,
    handleClose,
  ]);

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
    paddingTop: spacing.sm + 2,
    paddingBottom: spacing.sm + 4,
    minHeight: 64,
    gap: 6,
    justifyContent: "center" as const,
  };

  const fieldLabelStyle = {
    fontSize: fontSize.sm,
    color: "#e4e4e7",
    fontWeight: "500" as const,
  };

  const isFormBusy = isSaving;

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
                {isEditing ? "Edit Integration" : "New MCP Integration"}
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                {isEditing
                  ? "Update the details for this custom integration."
                  : "Connect an MCP server to extend GAIA's capabilities"}
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
              <AppIcon icon={Cancel01Icon} size={16} color="#71717a" />
            </Pressable>
          </View>

          <BottomSheetScrollView
            contentContainerStyle={{
              padding: spacing.md,
              gap: spacing.md,
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
            <View
              style={{
                ...fieldWrapperStyle,
                minHeight: 96,
                justifyContent: "flex-start",
              }}
            >
              <Text style={fieldLabelStyle}>Description</Text>
              <BottomSheetTextInput
                style={{ ...inputStyle, minHeight: 60 }}
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
            <View style={{ gap: 8 }}>
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
                        height: 48,
                        justifyContent: "center",
                        borderRadius: moderateScale(12, 0.5),
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
                          color: isSelected ? "#00bbff" : "#71717a",
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

            {/* Save */}
            <Pressable
              onPress={() => void handleSave()}
              disabled={
                isFormBusy ||
                !form.name.trim() ||
                (!isEditing && !form.serverUrl.trim())
              }
              style={({ pressed }) => ({
                height: 48,
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
                marginTop: spacing.xs,
                borderRadius: moderateScale(12, 0.5),
                backgroundColor:
                  !form.name.trim() ||
                  (!isEditing && !form.serverUrl.trim()) ||
                  isFormBusy
                    ? "rgba(0,187,255,0.3)"
                    : pressed
                      ? "rgba(0,170,230,0.9)"
                      : "rgba(0,187,255,0.95)",
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
                  {isEditing ? "Save Changes" : "Save Integration"}
                </Text>
              )}
            </Pressable>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

CreateMCPIntegrationSheet.displayName = "CreateMCPIntegrationSheet";
