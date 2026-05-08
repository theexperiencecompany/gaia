import { BottomSheetTextInput } from "@gorhom/bottom-sheet";
import { Pressable, View } from "react-native";
import { AppIcon, MailSend01Icon } from "@/components/icons";

interface TodoCreateInputProps {
  value: string;
  canSubmit: boolean;
  onChangeText: (text: string) => void;
  onSubmit: () => void;
  onFocus?: () => void;
}

export function TodoCreateInput({
  value,
  canSubmit,
  onChangeText,
  onSubmit,
  onFocus,
}: TodoCreateInputProps) {
  return (
    <View
      className="flex-row items-center"
      style={{
        paddingHorizontal: 14,
        paddingVertical: 8,
        gap: 10,
      }}
    >
      <BottomSheetTextInput
        value={value}
        onChangeText={onChangeText}
        onFocus={onFocus}
        autoFocus
        multiline
        placeholder='Try "Email Sam tomorrow #work !p1"'
        placeholderTextColor="#52525b"
        style={{
          flex: 1,
          fontSize: 16,
          color: "#f4f4f5",
          paddingVertical: 8,
          minHeight: 36,
          maxHeight: 120,
          textAlignVertical: "top",
        }}
      />
      <Pressable
        onPress={onSubmit}
        disabled={!canSubmit}
        accessibilityLabel="Add todo"
        style={{
          width: 40,
          height: 40,
          borderRadius: 20,
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: canSubmit ? "#00bbff" : "rgba(63,63,70,0.5)",
          opacity: canSubmit ? 1 : 0.6,
        }}
      >
        <AppIcon
          icon={MailSend01Icon}
          size={18}
          color={canSubmit ? "#000" : "#a1a1aa"}
        />
      </Pressable>
    </View>
  );
}
