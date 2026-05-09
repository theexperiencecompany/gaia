import { PressableFeedback, TextField } from "heroui-native";
import type { ReactNode } from "react";
import { View } from "react-native";
import { AppIcon, Cancel01Icon, Search01Icon } from "@/components/icons";
import { cn } from "@/lib/utils";

type TextFieldRootProps = React.ComponentProps<typeof TextField>;
type InputProps = React.ComponentProps<typeof TextField.Input>;

export interface AppSearchInputProps
  extends Omit<InputProps, "children" | "className"> {
  className?: string;
  inputClassName?: string;
  label?: ReactNode;
  description?: ReactNode;
  errorMessage?: ReactNode;
  startContent?: ReactNode;
  endContent?: ReactNode;
  showSearchIcon?: boolean;
  showClearButton?: boolean;
  onClear?: () => void;
  isDisabled?: TextFieldRootProps["isDisabled"];
  isInvalid?: TextFieldRootProps["isInvalid"];
}

export function AppSearchInput({
  className,
  inputClassName,
  label,
  description,
  errorMessage,
  startContent,
  endContent,
  showSearchIcon = true,
  showClearButton = true,
  onClear,
  isDisabled,
  isInvalid,
  onChangeText,
  placeholder = "Search",
  value,
  ...inputProps
}: AppSearchInputProps) {
  const hasValue = typeof value === "string" && value.length > 0;

  const resolvedStartContent =
    startContent === undefined && showSearchIcon ? (
      <AppIcon icon={Search01Icon} size={16} color="#6b6b6e" />
    ) : (
      startContent
    );

  const handleClear = () => {
    if (onClear) {
      onClear();
      return;
    }
    onChangeText?.("");
  };

  const resolvedEndContent =
    endContent ??
    (showClearButton && hasValue && !isDisabled ? (
      <PressableFeedback onPress={handleClear} className="rounded-full">
        <View className="h-6 w-6 items-center justify-center rounded-full">
          <AppIcon icon={Cancel01Icon} size={16} color="#6b6b6e" />
        </View>
      </PressableFeedback>
    ) : null);

  return (
    <TextField
      className={cn("gap-1", className)}
      isDisabled={isDisabled}
      isInvalid={isInvalid}
    >
      {label ? <View>{typeof label === "string" ? null : label}</View> : null}

      <View className="flex-row items-center">
        {resolvedStartContent ? (
          <View className="absolute left-3 z-10">{resolvedStartContent}</View>
        ) : null}
        <TextField.Input
          {...inputProps}
          value={value}
          placeholder={placeholder}
          onChangeText={onChangeText}
          placeholderTextColor="#71717a"
          style={{ backgroundColor: "rgba(39,39,42,0.30)" }}
          className={cn(
            "min-h-12 flex-1 rounded-2xl border-0 text-white",
            resolvedStartContent ? "pl-9" : "",
            resolvedEndContent ? "pr-9" : "",
            inputClassName,
          )}
        />
        {resolvedEndContent ? (
          <View className="absolute right-3 z-10">{resolvedEndContent}</View>
        ) : null}
      </View>

      {errorMessage ? (
        <View>{typeof errorMessage === "string" ? null : errorMessage}</View>
      ) : description ? (
        <View>{typeof description === "string" ? null : description}</View>
      ) : null}
    </TextField>
  );
}
