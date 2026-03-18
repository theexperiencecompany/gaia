import { PressableFeedback, TextField } from "heroui-native";
import type { ReactNode } from "react";
import { View } from "react-native";
import { AppIcon, Cancel01Icon, Search01Icon } from "@/components/icons";
import { cn } from "@/lib/utils";

type TextFieldRootProps = React.ComponentProps<typeof TextField>;
type TextFieldInputProps = React.ComponentProps<typeof TextField.Input>;

export interface AppSearchInputProps
  extends Omit<TextFieldInputProps, "children" | "className"> {
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
      <PressableFeedback
        onPress={handleClear}
        feedbackPosition="behind"
        className="rounded-full"
      >
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
      {label ? <TextField.Label>{label}</TextField.Label> : null}

      <TextField.Input
        {...inputProps}
        value={value}
        placeholder={placeholder}
        onChangeText={onChangeText}
        className={cn("min-h-12 rounded-2xl", inputClassName)}
      >
        {resolvedStartContent ? (
          <TextField.InputStartContent>
            {resolvedStartContent}
          </TextField.InputStartContent>
        ) : null}

        {resolvedEndContent ? (
          <TextField.InputEndContent>
            {resolvedEndContent}
          </TextField.InputEndContent>
        ) : null}
      </TextField.Input>

      {errorMessage ? (
        <TextField.ErrorMessage>{errorMessage}</TextField.ErrorMessage>
      ) : description ? (
        <TextField.Description>{description}</TextField.Description>
      ) : null}
    </TextField>
  );
}
