import { View, Keyboard, TouchableWithoutFeedback } from "react-native";
import { StyledSafeAreaView } from "@/lib/uniwind";
import { ChatInput } from "@/components/ui/chat-input";
import { MessageBubble, ChatMessage } from "@/components/ui/message-bubble";

export default function Test() {
  return (
    <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
      <StyledSafeAreaView className="flex-1">
        {/* Main content area with message examples */}
        <View className="flex-1 gap-4 p-4">
          {/* Single messages */}
          <MessageBubble message="Hello! How are you?" variant="received" />
          <MessageBubble message="I'm doing great, thanks!" variant="sent" />

          {/* Grouped messages using ChatMessage */}
          <ChatMessage
            messages={[
              "Hey there!",
              "Just checking in",
              "How's the project going?",
            ]}
            variant="received"
            timestamp="10:30 AM"
          />

          <ChatMessage
            messages={["All good!", "Almost done with the feature"]}
            variant="sent"
            timestamp="10:32 AM"
          />
        </View>

        {/* Chat Input at bottom */}
        <ChatInput
          placeholder="Ask Anything"
          onSend={(message) => console.log("Send:", message)}
        />
      </StyledSafeAreaView>
    </TouchableWithoutFeedback>
  );
}
