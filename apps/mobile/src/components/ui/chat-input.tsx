import { Button, PressableFeedback } from "heroui-native";
import { useRef, useState } from "react";
import { Keyboard, TextInput, View } from "react-native";
import { AppIcon, ArrowUp02Icon, PlusSignIcon } from "@/components/icons";
import { ConnectDrawerTrigger } from "@/features/integrations";
import { useResponsive } from "@/lib/responsive";
import { cn } from "@/lib/utils";
import { Text } from "./text";

const DEFAULT_COMMANDS = [
  "new",
  "integrations",
  "notifications",
  "settings",
  "workflows",
];

interface ChatInputProps {
  onSend?: (message: string) => void;
  placeholder?: string;
  value?: string;
  onChangeText?: (text: string) => void;
  onCommand?: (command: string) => boolean | undefined;
}

export function ChatInput({
  onSend,
  placeholder = "Ask anything",
  value,
  onChangeText,
  onCommand,
}: ChatInputProps) {
  const [internalMessage, setInternalMessage] = useState("");
  const inputRef = useRef<TextInput>(null);
  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();

  const message = value ?? internalMessage;
  const setMessage = onChangeText ?? setInternalMessage;
  const trimmed = message.trim();
  const isCommandMode = trimmed.startsWith("/");
  const commandQuery = isCommandMode ? trimmed.slice(1).toLowerCase() : "";
  const matchingCommands = DEFAULT_COMMANDS.filter((command) =>
    command.startsWith(commandQuery),
  );

  const runCommand = (command: string) => {
    const handled = onCommand?.(command) ?? false;
    if (handled) {
      setMessage("");
      dismissKeyboard();
    }
  };

  const handleSend = () => {
    if (message.trim()) {
      if (isCommandMode) {
        const command = trimmed.split(/\s+/)[0]?.slice(1).toLowerCase();
        if (command) {
          runCommand(command);
          return;
        }
      }
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
              <AppIcon
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
              <AppIcon
                icon={ArrowUp02Icon}
                size={iconSize.sm}
                strokeWidth={2.5}
                color={message.trim() ? "#000000" : "#8e8e93"}
              />
            </Button>
          </View>
        </View>

        {isCommandMode && matchingCommands.length > 0 && (
          <View
            style={{
              marginHorizontal: spacing.md,
              marginBottom: spacing.sm,
              borderRadius: moderateScale(12, 0.5),
              backgroundColor: "#111214",
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.08)",
              overflow: "hidden",
            }}
          >
            {matchingCommands.map((command, index) => (
              <PressableFeedback
                key={command}
                onPress={() => runCommand(command)}
                style={{
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm,
                  borderBottomWidth:
                    index === matchingCommands.length - 1 ? 0 : 1,
                  borderBottomColor: "rgba(255,255,255,0.05)",
                }}
              >
                <Text style={{ color: "#ffffff", fontSize: fontSize.sm }}>
                  /{command}
                </Text>
              </PressableFeedback>
            ))}
          </View>
        )}
      </View>
    </View>
  );
}
