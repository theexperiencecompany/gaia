import { ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import {
  EmailAccordion,
  EmailComposeCard,
  SAMPLE_EMAIL_COMPOSE,
  SAMPLE_EMAILS,
} from "@/features/chat";
import { StyledSafeAreaView } from "@/lib/uniwind";

export default function Test() {
  return (
    <StyledSafeAreaView className="flex-1 bg-background">
      <ScrollView className="flex-1">
        <View className="py-4">
          <Text className="text-lg font-semibold px-4 mb-4">
            Email Accordion Test
          </Text>
          <EmailAccordion emails={SAMPLE_EMAILS} />
        </View>

        <View className="py-4">
          <Text className="text-lg font-semibold px-4 mb-4">
            Email Compose Card
          </Text>
          <EmailComposeCard data={SAMPLE_EMAIL_COMPOSE} />
        </View>
      </ScrollView>
    </StyledSafeAreaView>
  );
}
