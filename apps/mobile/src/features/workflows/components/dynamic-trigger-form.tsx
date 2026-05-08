import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  Switch,
  TextInput,
  View,
} from "react-native";
import { AppIcon, ArrowDown01Icon, ArrowUp01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { workflowApi } from "../api/workflow-api";
import type { TriggerConfig, TriggerFieldSchema } from "../types/trigger-types";

export interface SelectOption {
  label: string;
  value: string;
}

export interface FieldWithMeta {
  name: string;
  schema: TriggerFieldSchema;
  derivedOptions?: SelectOption[];
}

interface DynamicTriggerFormProps {
  fields: FieldWithMeta[];
  config: TriggerConfig;
  onChange: (config: TriggerConfig) => void;
  /**
   * Required for dynamic options fetch (`/triggers/options`). When omitted,
   * fields with `options_endpoint` fall back to a free-text input.
   */
  integrationId?: string;
  triggerSlug?: string;
}

interface SelectPickerProps {
  options: SelectOption[];
  selected: string;
  onSelect: (value: string) => void;
  loading?: boolean;
  fontSize: { xs: number; sm: number };
  spacing: { xs: number; sm: number; md: number };
  moderateScale: (size: number, factor?: number) => number;
}

function SelectPicker({
  options,
  selected,
  onSelect,
  loading,
  fontSize,
  spacing,
  moderateScale,
}: SelectPickerProps) {
  const [open, setOpen] = useState(false);

  const selectedLabel =
    options.find((o) => o.value === selected)?.label ?? selected;

  return (
    <View>
      <Pressable
        onPress={() => setOpen((prev) => !prev)}
        style={{
          backgroundColor: "#2c2c2e",
          borderRadius: moderateScale(10, 0.5),
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.md,
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <Text
          style={{
            fontSize: fontSize.sm,
            color: selectedLabel ? "#fff" : "#52525b",
            flex: 1,
          }}
          numberOfLines={1}
        >
          {selectedLabel || "Select an option"}
        </Text>
        {loading ? (
          <ActivityIndicator size="small" color="#52525b" />
        ) : (
          <AppIcon
            icon={open ? ArrowUp01Icon : ArrowDown01Icon}
            size={14}
            color="#52525b"
          />
        )}
      </Pressable>

      {open && (
        <View
          style={{
            backgroundColor: "#2c2c2e",
            borderRadius: moderateScale(10, 0.5),
            marginTop: spacing.xs,
            overflow: "hidden",
            maxHeight: 240,
          }}
        >
          {options.length === 0 ? (
            <View style={{ padding: spacing.md }}>
              <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                No options available
              </Text>
            </View>
          ) : (
            options.map((option) => {
              const isSelected = option.value === selected;
              return (
                <Pressable
                  key={option.value}
                  onPress={() => {
                    onSelect(option.value);
                    setOpen(false);
                  }}
                  style={({ pressed }) => ({
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm + 4,
                    backgroundColor: isSelected
                      ? "rgba(0,187,255,0.12)"
                      : pressed
                        ? "rgba(255,255,255,0.05)"
                        : "transparent",
                    borderLeftWidth: isSelected ? 2 : 0,
                    borderLeftColor: "#00bbff",
                  })}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      color: isSelected ? "#00bbff" : "#d4d4d8",
                    }}
                  >
                    {option.label}
                  </Text>
                </Pressable>
              );
            })
          )}
        </View>
      )}
    </View>
  );
}

interface DynamicSelectFieldProps {
  fieldName: string;
  schema: TriggerFieldSchema;
  value: string;
  onChange: (value: string) => void;
  derivedOptions?: SelectOption[];
  integrationId?: string;
  triggerSlug?: string;
  fontSize: { xs: number; sm: number };
  spacing: { xs: number; sm: number; md: number };
  moderateScale: (size: number, factor?: number) => number;
}

function DynamicSelectField({
  fieldName,
  schema,
  value,
  onChange,
  derivedOptions,
  integrationId,
  triggerSlug,
  fontSize,
  spacing,
  moderateScale,
}: DynamicSelectFieldProps) {
  const [options, setOptions] = useState<SelectOption[]>(derivedOptions ?? []);
  const [loading, setLoading] = useState(false);

  const hasEndpoint = Boolean(schema.options_endpoint);

  useEffect(() => {
    if (!hasEndpoint || !integrationId || !triggerSlug) return;
    let cancelled = false;
    setLoading(true);
    workflowApi
      .getTriggerOptions(integrationId, triggerSlug, fieldName)
      .then((opts) => {
        if (cancelled) return;
        setOptions(opts);
      })
      .catch(() => {
        if (cancelled) return;
        // Silent: leave options empty so the user sees an empty dropdown
        // rather than a red toast.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hasEndpoint, integrationId, triggerSlug, fieldName]);

  return (
    <SelectPicker
      options={options}
      selected={value}
      onSelect={onChange}
      loading={loading}
      fontSize={fontSize}
      spacing={spacing}
      moderateScale={moderateScale}
    />
  );
}

export function DynamicTriggerForm({
  fields,
  config,
  onChange,
  integrationId,
  triggerSlug,
}: DynamicTriggerFormProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const updateField = (name: string, value: unknown) => {
    onChange({ ...config, [name]: value });
  };

  if (fields.length === 0) {
    return null;
  }

  return (
    <View style={{ gap: spacing.md }}>
      {fields.map(({ name, schema, derivedOptions }) => {
        const currentValue = config[name];
        const labelText = name
          .replace(/_/g, " ")
          .replace(/\b\w/g, (c) => c.toUpperCase());

        const hasOptions =
          (derivedOptions && derivedOptions.length > 0) ||
          Boolean(schema.options_endpoint);

        return (
          <View key={name} style={{ gap: spacing.xs }}>
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.xs,
              }}
            >
              <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
                {labelText}
              </Text>
              {schema.description ? (
                <Text style={{ fontSize: fontSize.xs - 1, color: "#52525b" }}>
                  {schema.description}
                </Text>
              ) : null}
            </View>

            {schema.type === "boolean" ? (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "space-between",
                  backgroundColor: "#2c2c2e",
                  borderRadius: moderateScale(10, 0.5),
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm,
                }}
              >
                <Text style={{ fontSize: fontSize.sm, color: "#d4d4d8" }}>
                  {currentValue ? "Enabled" : "Disabled"}
                </Text>
                <Switch
                  value={Boolean(currentValue ?? schema.default)}
                  onValueChange={(val) => updateField(name, val)}
                  trackColor={{ false: "#3f3f46", true: "#0077aa" }}
                  thumbColor={currentValue ? "#00bbff" : "#71717a"}
                />
              </View>
            ) : schema.type === "string" && hasOptions ? (
              <DynamicSelectField
                fieldName={name}
                schema={schema}
                value={String(currentValue ?? schema.default ?? "")}
                onChange={(val) => updateField(name, val)}
                derivedOptions={derivedOptions}
                integrationId={integrationId}
                triggerSlug={triggerSlug}
                fontSize={fontSize}
                spacing={spacing}
                moderateScale={moderateScale}
              />
            ) : schema.type === "integer" || schema.type === "number" ? (
              <TextInput
                style={{
                  backgroundColor: "#2c2c2e",
                  borderRadius: moderateScale(10, 0.5),
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.md,
                  fontSize: fontSize.sm,
                  color: "#fff",
                }}
                keyboardType="numeric"
                placeholder={String(schema.default ?? "")}
                placeholderTextColor="#52525b"
                value={currentValue != null ? String(currentValue) : ""}
                onChangeText={(text) => {
                  const parsed =
                    schema.type === "integer"
                      ? Number.parseInt(text, 10)
                      : Number.parseFloat(text);
                  updateField(name, Number.isNaN(parsed) ? undefined : parsed);
                }}
              />
            ) : (
              <TextInput
                style={{
                  backgroundColor: "#2c2c2e",
                  borderRadius: moderateScale(10, 0.5),
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.md,
                  fontSize: fontSize.sm,
                  color: "#fff",
                }}
                placeholder={schema.description ?? String(schema.default ?? "")}
                placeholderTextColor="#52525b"
                value={currentValue != null ? String(currentValue) : ""}
                onChangeText={(text) => updateField(name, text)}
              />
            )}
          </View>
        );
      })}
    </View>
  );
}
