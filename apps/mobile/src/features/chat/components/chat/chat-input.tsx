import { PressableFeedback } from "heroui-native";
import { useEffect, useRef, useState } from "react";
import { Animated, TextInput, View } from "react-native";
import { HugeiconsIcon, PlusSignIcon, SentIcon } from "@/components/icons";

export function ChatInput({
  placeholder = "What can I do for you today?",
  onSubmit,
  disabled,
}: {
  placeholder?: string;
  onSubmit?: (value: string) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");
  const scaleAnim = useRef(new Animated.Value(0.9)).current;

  const canSubmit = value.trim().length > 0;

  useEffect(() => {
    Animated.spring(scaleAnim, {
      toValue: canSubmit ? 1 : 0.9,
      useNativeDriver: true,
    }).start();
  }, [canSubmit, scaleAnim]);

  const handleSend = () => {
    if (!canSubmit) return;
    onSubmit?.(value.trim());
    setValue("");
  };

  return (
    <View className="flex-row items-end rounded-3xl bg-surface-2 px-3 py-2 border border-border/10 shadow-lg">
      <PressableFeedback onPress={() => console.log("Attach pressed")}>
        <View className="h-10 w-10 items-center justify-center rounded-full">
          <HugeiconsIcon icon={PlusSignIcon} size={20} color="#8e8e93" />
        </View>
      </PressableFeedback>

      <TextInput
        value={value}
        onChangeText={setValue}
        placeholder={placeholder}
        placeholderTextColor="#666666"
        multiline
        editable={!disabled}
        className="flex-1 text-base leading-6 text-foreground px-2 py-2 max-h-32"
        style={{ textAlignVertical: "bottom" }}
      />

      <Animated.View
        style={{
          transform: [{ scale: scaleAnim }],
          opacity: canSubmit ? 1 : 0.4,
        }}
        className="pb-0.5"
      >
        <PressableFeedback onPress={handleSend} isDisabled={!canSubmit}>
          <View
            className={`h-9 w-9 rounded-full items-center justify-center ${
              canSubmit ? "bg-accent" : "bg-surface-3"
            }`}
          >
            <HugeiconsIcon
              icon={SentIcon}
              size={18}
              color={canSubmit ? "#000000" : "#666666"}
            />
          </View>
        </PressableFeedback>
      </Animated.View>
    </View>
  );
}
