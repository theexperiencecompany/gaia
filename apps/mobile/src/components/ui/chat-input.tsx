import { Button } from "heroui-native";
import { useRef, useState } from "react";
import { Keyboard, TextInput, View } from "react-native";
import { ArrowUp02Icon, HugeiconsIcon, PlusSignIcon } from "@/components/icons";
import { ConnectDrawerTrigger } from "@/features/integrations";
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
    <View className="w-full">
      <View className="bg-surface rounded-4xl">
        <TextInput
          ref={inputRef}
          className="px-4 py-6 text-base text-foreground min-h-14"
          placeholder={placeholder}
          placeholderTextColor="#6b6b6b"
          value={message}
          onChangeText={setMessage}
          multiline
          maxLength={4000}
        />

        <View className="flex-row items-center justify-between px-3 pb-3">
          <View className="flex-row items-center gap-2">
            <Button
              variant="secondary"
              isIconOnly
              size="sm"
              className="rounded-full"
              onPress={dismissKeyboard}
            >
              <HugeiconsIcon icon={PlusSignIcon} size={18} color="#8e8e93" />
            </Button>

            <ConnectDrawerTrigger onOpen={dismissKeyboard} />
          </View>

          <View className="flex-row items-center gap-2">
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
                size={16}
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
