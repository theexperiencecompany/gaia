import { Button } from "heroui-native";
import { useRef, useState } from "react";
import { Keyboard, TextInput, View } from "react-native";
import { ArrowUp02Icon, HugeiconsIcon, PlusSignIcon } from "@/components/icons";
import { ConnectDrawerTrigger } from "@/features/integrations";
import { useResponsive } from "@/lib/responsive";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend?: (message: string) => void;
  placeholder?: string;
  value?: string;
  onChangeText?: (text: string) => void;
}

export function ChatInput({
  onSend,
  placeholder = "Ask anything",
  value,
  onChangeText,
}: ChatInputProps) {
  const [internalMessage, setInternalMessage] = useState("");
  const inputRef = useRef<TextInput>(null);
  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();

  const message = value ?? internalMessage;
  const setMessage = onChangeText ?? setInternalMessage;

  const handleSend = () => {
    if (message.trim()) {
      onSend?.(message);
      setMessage("");
    }
  };

  const dismissKeyboard = () => {
    inputRef.current?.blur();
    Keyboard.dismiss();
  };

  return (
    <View style={{ width: "100%" }}>
      <View
        style={{
          backgroundColor: "#1c1c1e",
          borderRadius: moderateScale(24, 0.5),
        }}
      >
        <TextInput
          ref={inputRef}
          style={{
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.lg,
            fontSize: fontSize.base,
            color: "#ffffff",
            minHeight: moderateScale(56, 0.5),
          }}
          placeholder={placeholder}
          placeholderTextColor="#6b6b6b"
          value={message}
          onChangeText={setMessage}
          multiline
          maxLength={4000}
        />

        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: spacing.md,
            paddingBottom: spacing.md,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <Button
              variant="secondary"
              isIconOnly
              size="sm"
              className="rounded-full"
              onPress={dismissKeyboard}
            >
              <HugeiconsIcon
                icon={PlusSignIcon}
                size={iconSize.md - 2}
                color="#8e8e93"
              />
            </Button>

            <ConnectDrawerTrigger onOpen={dismissKeyboard} />
          </View>

          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <Button
              variant="ghost"
              isIconOnly
              size="sm"
              className={cn("rounded-full", {
                "bg-accent": message.trim(),
                "bg-default": !message.trim(),
              })}
              onPress={handleSend}
              isDisabled={!message.trim()}
            >
              <HugeiconsIcon
                icon={ArrowUp02Icon}
                size={iconSize.sm}
                strokeWidth={2.5}
                color={message.trim() ? "#000000" : "#8e8e93"}
              />
            </Button>
          </View>
        </View>
      </View>
    </View>
  );
}
