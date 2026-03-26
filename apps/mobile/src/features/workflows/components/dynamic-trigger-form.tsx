import { useState } from "react";
import { Pressable, Switch, TextInput, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
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
}

interface SelectPickerProps {
  options: SelectOption[];
  selected: string;
  onSelect: (value: string) => void;
  fontSize: { xs: number; sm: number };
  spacing: { xs: number; sm: number; md: number };
  moderateScale: (size: number, factor?: number) => number;
}

function SelectPicker({
  options,
  selected,
  onSelect,
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
          }}
        >
          {selectedLabel || "Select an option"}
        </Text>
        <Text style={{ fontSize: fontSize.xs, color: "#52525b" }}>
          {open ? "▲" : "▼"}
        </Text>
      </Pressable>

      {open && (
        <View
          style={{
            backgroundColor: "#2c2c2e",
            borderRadius: moderateScale(10, 0.5),
            marginTop: spacing.xs,
            overflow: "hidden",
          }}
        >
          {options.map((option) => {
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
                    ? "#00bbff20"
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
          })}
        </View>
      )}
    </View>
  );
}

export function DynamicTriggerForm({
  fields,
  config,
  onChange,
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
                  — {schema.description}
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
            ) : schema.type === "string" &&
              derivedOptions &&
              derivedOptions.length > 0 ? (
              <SelectPicker
                options={derivedOptions}
                selected={String(currentValue ?? schema.default ?? "")}
                onSelect={(val) => updateField(name, val)}
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
