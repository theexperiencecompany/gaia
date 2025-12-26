import { View, TextInput } from "react-native";
import { Text } from "@/components/ui/text";
import {
  HugeiconsIcon,
  PlusSignIcon,
  Wrench01Icon,
  ArrowUp02Icon,
  UserIcon,
} from "@/components/icons";
import { useState } from "react";
import { Button, TextField } from "heroui-native";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend?: (message: string) => void;
  onToolsPress?: () => void;
  placeholder?: string;
}

export function ChatInput({
  onSend,
  onToolsPress,
  placeholder = "Ask anything",
}: ChatInputProps) {
  const [message, setMessage] = useState("");

  const handleSend = () => {
    if (message.trim()) {
      onSend?.(message);
      setMessage("");
    }
  };

  return (
    <View className="w-full">
      <View className="bg-surface rounded-4xl">
        <TextInput
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
            >
              <HugeiconsIcon icon={PlusSignIcon} size={18} color="#8e8e93" />
            </Button>

            <Button
              variant="tertiary"
              isIconOnly
              size="sm"
              className="rounded-full"
              onPress={onToolsPress}
            >
              <HugeiconsIcon icon={Wrench01Icon} size={18} color="#8e8e93" />
            </Button>
            <Button
              variant="tertiary"
              isIconOnly
              size="sm"
              className="rounded-full"
            >
              <HugeiconsIcon icon={UserIcon} size={18} color="#8e8e93" />
            </Button>
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
