import { useEffect, useRef } from "react";
import { Animated, View } from "react-native";
import { useResponsive } from "@/lib/responsive";

function SkeletonBox({
  width,
  height,
  borderRadius = 8,
  style,
}: {
  width: number | string;
  height: number;
  borderRadius?: number;
  style?: object;
}) {
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, {
          toValue: 1,
          duration: 900,
          useNativeDriver: true,
        }),
        Animated.timing(shimmer, {
          toValue: 0,
          duration: 900,
          useNativeDriver: true,
        }),
      ]),
    ).start();
    return () => shimmer.stopAnimation();
  }, [shimmer]);

  const opacity = shimmer.interpolate({
    inputRange: [0, 1],
    outputRange: [0.3, 0.65],
  });

  return (
    <Animated.View
      style={[
        { width, height, borderRadius, backgroundColor: "#3f3f46", opacity },
        style,
      ]}
    />
  );
}

export function WorkflowCardSkeleton() {
  const { spacing, moderateScale } = useResponsive();
  return (
    <View
      style={{
        backgroundColor: "#1c1c1e",
        borderRadius: moderateScale(16, 0.5),
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      {/* Icon row */}
      <View style={{ flexDirection: "row", gap: spacing.xs }}>
        <SkeletonBox width={32} height={32} borderRadius={8} />
        <SkeletonBox width={32} height={32} borderRadius={8} />
        <SkeletonBox width={32} height={32} borderRadius={8} />
      </View>
      {/* Title */}
      <SkeletonBox width="70%" height={16} borderRadius={6} />
      {/* Description */}
      <SkeletonBox width="90%" height={12} borderRadius={4} />
      <SkeletonBox width="60%" height={12} borderRadius={4} />
      {/* Footer */}
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          marginTop: spacing.xs,
        }}
      >
        <SkeletonBox width={60} height={20} borderRadius={10} />
        <SkeletonBox width={80} height={20} borderRadius={10} />
      </View>
    </View>
  );
}

export function WorkflowStepSkeleton() {
  const { spacing } = useResponsive();
  return (
    <View
      style={{
        flexDirection: "row",
        gap: spacing.sm,
        alignItems: "flex-start",
      }}
    >
      <SkeletonBox width={32} height={32} borderRadius={16} />
      <View style={{ flex: 1, gap: 6 }}>
        <SkeletonBox width="60%" height={14} borderRadius={4} />
        <SkeletonBox width="80%" height={12} borderRadius={4} />
        <SkeletonBox width="40%" height={12} borderRadius={4} />
      </View>
    </View>
  );
}

export function WorkflowDetailSkeleton() {
  const { spacing, moderateScale } = useResponsive();
  return (
    <View style={{ gap: spacing.lg }}>
      {/* Hero card: icon + title + chips */}
      <View
        style={{
          backgroundColor: "rgba(39,39,42,0.30)",
          borderRadius: moderateScale(16, 0.5),
          padding: spacing.md,
          gap: spacing.md,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <SkeletonBox width={44} height={44} borderRadius={12} />
          <View style={{ flex: 1, gap: 6 }}>
            <SkeletonBox width="70%" height={16} borderRadius={6} />
            <SkeletonBox width="90%" height={12} borderRadius={4} />
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <SkeletonBox width={70} height={22} borderRadius={11} />
          <SkeletonBox width={56} height={22} borderRadius={11} />
        </View>
      </View>

      {/* Action row */}
      <View style={{ gap: spacing.sm }}>
        <SkeletonBox width="100%" height={44} borderRadius={14} />
        <SkeletonBox width="100%" height={36} borderRadius={14} />
      </View>

      {/* Tabs */}
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <SkeletonBox width={88} height={32} borderRadius={10} />
        <SkeletonBox width={88} height={32} borderRadius={10} />
      </View>

      {/* Steps list placeholder */}
      <View style={{ gap: spacing.md }}>
        <WorkflowStepSkeleton />
        <WorkflowStepSkeleton />
        <WorkflowStepSkeleton />
      </View>
    </View>
  );
}

export function WorkflowListSkeleton() {
  const { spacing } = useResponsive();
  return (
    <View style={{ gap: spacing.sm }}>
      <WorkflowCardSkeleton />
      <WorkflowCardSkeleton />
      <WorkflowCardSkeleton />
      <WorkflowCardSkeleton />
    </View>
  );
}
