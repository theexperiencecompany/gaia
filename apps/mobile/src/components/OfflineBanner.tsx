import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, Cancel01Icon, GlobeIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useNetwork } from "@/hooks/use-network";

export function OfflineBanner() {
  const { isOnline } = useNetwork();
  const insets = useSafeAreaInsets();
  const translateY = useRef(new Animated.Value(-80)).current;
  const [isDismissed, setIsDismissed] = useState(false);
  const [wasOffline, setWasOffline] = useState(false);

  useEffect(() => {
    if (!isOnline) {
      setWasOffline(true);
      setIsDismissed(false);
      Animated.spring(translateY, {
        toValue: 0,
        useNativeDriver: true,
        damping: 20,
        stiffness: 200,
      }).start();
    } else if (wasOffline) {
      const timer = setTimeout(() => {
        Animated.timing(translateY, {
          toValue: -80,
          duration: 300,
          useNativeDriver: true,
        }).start(() => {
          setWasOffline(false);
        });
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [isOnline, wasOffline, translateY]);

  const handleDismiss = useCallback(() => {
    setIsDismissed(true);
    Animated.timing(translateY, {
      toValue: -80,
      duration: 250,
      useNativeDriver: true,
    }).start();
  }, [translateY]);

  if (!wasOffline && isOnline) return null;
  if (isDismissed) return null;

  const isBackOnline = isOnline && wasOffline;
  const bgColor = isBackOnline ? "#16a34a" : "#dc2626";

  return (
    <Animated.View
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        transform: [{ translateY }],
        paddingTop: insets.top,
        backgroundColor: bgColor,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: 16,
          paddingVertical: 10,
          gap: 8,
        }}
      >
        <AppIcon icon={GlobeIcon} size={16} color="#ffffff" />
        <Text
          style={{
            flex: 1,
            fontSize: 13,
            fontWeight: "600",
            color: "#ffffff",
          }}
        >
          {isBackOnline ? "Back online" : "No internet connection"}
        </Text>
        {!isBackOnline && (
          <Pressable onPress={handleDismiss} hitSlop={8}>
            <AppIcon
              icon={Cancel01Icon}
              size={16}
              color="rgba(255,255,255,0.7)"
            />
          </Pressable>
        )}
      </View>
    </Animated.View>
  );
}
