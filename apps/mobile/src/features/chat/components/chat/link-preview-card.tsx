import { Image } from "expo-image";
import {
  openBrowserAsync,
  WebBrowserPresentationStyle,
} from "expo-web-browser";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

export interface LinkPreviewCardProps {
  url: string;
  title?: string;
  description?: string;
  imageUrl?: string;
  favicon?: string;
  domain?: string;
}

export function LinkPreviewCard({
  url,
  title,
  description,
  imageUrl,
  favicon,
  domain,
}: LinkPreviewCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const handlePress = async () => {
    await openBrowserAsync(url, {
      presentationStyle: WebBrowserPresentationStyle.AUTOMATIC,
    });
  };

  const displayDomain =
    domain ??
    (() => {
      try {
        return new URL(url).hostname.replace(/^www\./, "");
      } catch {
        return url;
      }
    })();

  return (
    <Pressable
      onPress={handlePress}
      style={({ pressed }) => ({
        opacity: pressed ? 0.75 : 1,
        borderRadius: moderateScale(12, 0.5),
        overflow: "hidden",
        borderWidth: 1,
        borderColor: "rgba(255,255,255,0.08)",
        backgroundColor: "rgba(255,255,255,0.04)",
        marginTop: spacing.sm,
      })}
    >
      {imageUrl ? (
        <Image
          source={{ uri: imageUrl }}
          style={{
            width: "100%",
            height: moderateScale(140, 0.5),
          }}
          contentFit="cover"
        />
      ) : null}

      <View
        style={{
          padding: spacing.md,
          gap: spacing.xs,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.xs,
          }}
        >
          {favicon ? (
            <Image
              source={{ uri: favicon }}
              style={{
                width: moderateScale(14, 0.5),
                height: moderateScale(14, 0.5),
                borderRadius: 2,
              }}
              contentFit="contain"
            />
          ) : null}
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8e8e93",
              flexShrink: 1,
            }}
            numberOfLines={1}
          >
            {displayDomain}
          </Text>
        </View>

        {title ? (
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#ffffff",
              fontWeight: "600",
            }}
            numberOfLines={2}
          >
            {title}
          </Text>
        ) : null}

        {description ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8e8e93",
              lineHeight: fontSize.xs * 1.4,
            }}
            numberOfLines={2}
          >
            {description}
          </Text>
        ) : null}

        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#00bbff",
            marginTop: spacing.xs,
          }}
        >
          Open
        </Text>
      </View>
    </Pressable>
  );
}
