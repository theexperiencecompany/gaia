import { Image } from "expo-image";
import { Dialog } from "heroui-native";
import { useCallback, useRef } from "react";
import {
  Dimensions,
  Platform,
  Pressable,
  ScrollView,
  Share,
  View,
} from "react-native";
import {
  Gesture,
  GestureDetector,
  GestureHandlerRootView,
} from "react-native-gesture-handler";
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Share01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get("window");

interface ImageViewerModalProps {
  isVisible: boolean;
  imageUrl: string | undefined;
  prompt?: string;
  improvedPrompt?: string;
  onClose: () => void;
}

export function ImageViewerModal({
  isVisible,
  imageUrl,
  prompt,
  improvedPrompt,
  onClose,
}: ImageViewerModalProps) {
  const insets = useSafeAreaInsets();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);
  const savedTranslateX = useSharedValue(0);
  const savedTranslateY = useSharedValue(0);
  const isZoomed = useRef(false);

  const resetTransform = useCallback(() => {
    scale.value = withTiming(1, { duration: 200 });
    translateX.value = withTiming(0, { duration: 200 });
    translateY.value = withTiming(0, { duration: 200 });
    savedScale.value = 1;
    savedTranslateX.value = 0;
    savedTranslateY.value = 0;
    isZoomed.current = false;
  }, [
    scale,
    translateX,
    translateY,
    savedScale,
    savedTranslateX,
    savedTranslateY,
  ]);

  const pinchGesture = Gesture.Pinch()
    .onUpdate((e) => {
      scale.value = savedScale.value * e.scale;
    })
    .onEnd(() => {
      if (scale.value < 1) {
        scale.value = withTiming(1, { duration: 200 });
        savedScale.value = 1;
        translateX.value = withTiming(0, { duration: 200 });
        translateY.value = withTiming(0, { duration: 200 });
        savedTranslateX.value = 0;
        savedTranslateY.value = 0;
        runOnJS(() => {
          isZoomed.current = false;
        })();
      } else {
        savedScale.value = scale.value;
        runOnJS(() => {
          isZoomed.current = scale.value > 1;
        })();
      }
    });

  const panGesture = Gesture.Pan()
    .onUpdate((e) => {
      if (savedScale.value > 1) {
        translateX.value = savedTranslateX.value + e.translationX;
        translateY.value = savedTranslateY.value + e.translationY;
      } else {
        // Pan to dismiss when not zoomed
        translateY.value = e.translationY;
      }
    })
    .onEnd((e) => {
      if (savedScale.value <= 1) {
        if (Math.abs(e.translationY) > 100) {
          runOnJS(onClose)();
        } else {
          translateY.value = withTiming(0, { duration: 200 });
        }
      } else {
        savedTranslateX.value = translateX.value;
        savedTranslateY.value = translateY.value;
      }
    });

  const doubleTapGesture = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd(() => {
      if (savedScale.value > 1) {
        scale.value = withTiming(1, { duration: 200 });
        translateX.value = withTiming(0, { duration: 200 });
        translateY.value = withTiming(0, { duration: 200 });
        savedScale.value = 1;
        savedTranslateX.value = 0;
        savedTranslateY.value = 0;
      } else {
        scale.value = withTiming(2.5, { duration: 200 });
        savedScale.value = 2.5;
      }
    });

  const composedGesture = Gesture.Simultaneous(
    pinchGesture,
    panGesture,
    doubleTapGesture,
  );

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
    ],
  }));

  const handleShare = useCallback(async () => {
    if (!imageUrl) return;
    try {
      if (Platform.OS === "ios") {
        await Share.share({ url: imageUrl, message: imageUrl });
      } else {
        await Share.share({ message: imageUrl });
      }
    } catch {
      // User cancelled or share failed silently
    }
  }, [imageUrl]);

  const handleClose = useCallback(() => {
    resetTransform();
    onClose();
  }, [onClose, resetTransform]);

  const imageDisplaySize = SCREEN_WIDTH - spacing.md * 2;

  return (
    <Dialog
      isOpen={isVisible}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay />
        <Dialog.Content
          isSwipeable={false}
          style={{
            flex: 1,
            backgroundColor: "rgba(0, 0, 0, 0.95)",
            borderRadius: 0,
            width: SCREEN_WIDTH,
            height: SCREEN_HEIGHT,
            maxHeight: SCREEN_HEIGHT,
          }}
        >
          <GestureHandlerRootView style={{ flex: 1 }}>
            <View style={{ flex: 1 }}>
              {/* Header */}
              <View
                style={{
                  flexDirection: "row",
                  justifyContent: "space-between",
                  alignItems: "center",
                  paddingTop: insets.top + spacing.sm,
                  paddingHorizontal: spacing.md,
                  paddingBottom: spacing.sm,
                  zIndex: 10,
                }}
              >
                <Dialog.Close
                  onPress={handleClose}
                  hitSlop={16}
                  style={{
                    padding: spacing.sm,
                    borderRadius: moderateScale(20, 0.5),
                    backgroundColor: "rgba(255,255,255,0.1)",
                  }}
                  iconProps={{ size: moderateScale(20, 0.5), color: "#ffffff" }}
                />

                <Pressable
                  onPress={handleShare}
                  hitSlop={16}
                  style={{
                    padding: spacing.sm,
                    borderRadius: moderateScale(20, 0.5),
                    backgroundColor: "rgba(255,255,255,0.1)",
                  }}
                >
                  <Share01Icon size={moderateScale(20, 0.5)} color="#ffffff" />
                </Pressable>
              </View>

              {/* Image area */}
              <View
                style={{
                  flex: 1,
                  justifyContent: "center",
                  alignItems: "center",
                }}
              >
                <GestureDetector gesture={composedGesture}>
                  <Animated.View style={animatedStyle}>
                    {imageUrl ? (
                      <Image
                        source={{ uri: imageUrl }}
                        style={{
                          width: imageDisplaySize,
                          height: imageDisplaySize,
                          borderRadius: moderateScale(16, 0.5),
                        }}
                        contentFit="contain"
                        transition={200}
                      />
                    ) : null}
                  </Animated.View>
                </GestureDetector>
              </View>

              {/* Prompt info */}
              {prompt || improvedPrompt ? (
                <ScrollView
                  style={{
                    maxHeight: SCREEN_HEIGHT * 0.2,
                    paddingHorizontal: spacing.md,
                    paddingBottom: insets.bottom + spacing.md,
                  }}
                  contentContainerStyle={{ paddingBottom: spacing.md }}
                  showsVerticalScrollIndicator={false}
                >
                  {prompt ? (
                    <View style={{ marginBottom: spacing.sm }}>
                      <Text
                        style={{
                          fontSize: fontSize.xs,
                          color: "#a1a1aa",
                          fontWeight: "600",
                          marginBottom: 2,
                        }}
                      >
                        Prompt
                      </Text>
                      <Text
                        style={{
                          fontSize: fontSize.sm,
                          color: "#d4d4d8",
                          lineHeight: 20,
                        }}
                      >
                        {prompt}
                      </Text>
                    </View>
                  ) : null}
                  {improvedPrompt ? (
                    <View>
                      <Text
                        style={{
                          fontSize: fontSize.xs,
                          color: "#a1a1aa",
                          fontWeight: "600",
                          marginBottom: 2,
                        }}
                      >
                        Enhanced Prompt
                      </Text>
                      <Text
                        style={{
                          fontSize: fontSize.sm,
                          color: "#d4d4d8",
                          lineHeight: 20,
                        }}
                      >
                        {improvedPrompt}
                      </Text>
                    </View>
                  ) : null}
                </ScrollView>
              ) : (
                <View style={{ height: insets.bottom + spacing.md }} />
              )}
            </View>
          </GestureHandlerRootView>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog>
  );
}
