import * as WebBrowser from "expo-web-browser";
import { Button } from "heroui-native";
import { Alert, View } from "react-native";
import { AppIcon, UploadCircle01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { PRICING_URL } from "@/lib/constants";
import { usePaywallStore } from "@/stores/paywall-store";

/**
 * The paid-only wall, shown above the composer once the backend refuses a turn
 * with 402. Distinct from `FailedResponse`: nothing here is retryable, so the
 * affordance is checkout, not retry.
 */
export function PaywallNotice() {
  const offer = usePaywallStore((s) => s.offer);

  if (!offer) return null;

  // The backend mints a personal checkout link into the 402 body, but sends
  // none when Dodo is unreachable — the block still stands, so fall back to
  // the pricing page rather than leaving a dead button.
  const target = offer.checkout_url ?? PRICING_URL;

  const openCheckout = async () => {
    try {
      await WebBrowser.openBrowserAsync(target);
    } catch {
      Alert.alert("Error", "Could not open the checkout page.");
    }
  };

  return (
    <View className="mb-2 gap-3 rounded-2xl bg-zinc-800 p-4">
      <View className="flex-row items-start gap-3">
        <View className="h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-500/15">
          <AppIcon icon={UploadCircle01Icon} size={18} color="#f5a524" />
        </View>
        <View className="shrink flex-1 gap-1">
          <Text className="font-semibold text-base text-zinc-100">
            GAIA is Pro-only
          </Text>
          <Text className="text-sm text-zinc-400">
            {offer.message ?? "Subscribe to GAIA Pro to keep chatting."}
          </Text>
          {offer.discount_code ? (
            <Text className="text-sm text-zinc-400">
              Use code{" "}
              <Text className="font-semibold text-zinc-200">
                {offer.discount_code}
              </Text>{" "}
              at checkout.
            </Text>
          ) : null}
        </View>
      </View>

      <Button
        size="sm"
        variant="primary"
        className="w-full rounded-xl"
        onPress={() => void openCheckout()}
      >
        <Button.Label>Subscribe to GAIA Pro</Button.Label>
      </Button>
    </View>
  );
}
