import { dispatchOpenUIAction, normalizeOpenUICode } from "@gaia/shared/utils";
import {
  type ActionEvent,
  type ParseResult,
  Renderer,
} from "@openuidev/react-lang";
import * as WebBrowser from "expo-web-browser";
import React from "react";
import { View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { Alert01Icon, AppIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { genericLibrary } from "@/config/openui/generic-library";
import { useAppendToInput } from "@/features/chat/stores/composer-store";

interface OpenUIRendererProps {
  code: string;
  isStreaming: boolean;
}

function OpenUIShimmer() {
  const opacity = useSharedValue(0.55);

  React.useEffect(() => {
    opacity.value = withRepeat(
      withTiming(1, { duration: 900, easing: Easing.inOut(Easing.ease) }),
      -1,
      true,
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Animated.View
      style={animatedStyle}
      className="w-full max-w-lg rounded-2xl bg-zinc-800 p-4"
    >
      <View className="gap-2.5">
        <View className="h-3 w-full rounded-lg bg-zinc-700/70" />
        <View className="h-3 w-5/6 rounded-lg bg-zinc-700/70" />
        <View className="h-3 w-2/3 rounded-lg bg-zinc-700/70" />
      </View>
      <View className="mt-4 h-24 w-full rounded-xl bg-zinc-700/50" />
    </Animated.View>
  );
}

function OpenUIErrorCard({ code, error }: { code: string; error?: string }) {
  return (
    <View className="w-full max-w-lg rounded-2xl bg-zinc-800 p-4">
      <View className="mb-2 flex-row items-center gap-2">
        <AppIcon icon={Alert01Icon} size={16} color="#f87171" />
        <Text className="text-sm font-medium text-red-400">
          Component failed to render
        </Text>
      </View>
      {error ? (
        <Text className="mb-2 text-xs text-zinc-500">{error}</Text>
      ) : null}
      <View className="rounded-xl bg-zinc-900 p-3">
        <Text className="text-xs text-zinc-400 font-mono">{code}</Text>
      </View>
    </View>
  );
}

function OpenUIRendererInner({ code, isStreaming }: OpenUIRendererProps) {
  const appendToInput = useAppendToInput();
  const normalizedCode = React.useMemo(
    () => normalizeOpenUICode(code, genericLibrary),
    [code],
  );

  const [failedForCode, setFailedForCode] = React.useState<string | null>(null);
  const [failureReason, setFailureReason] = React.useState<string>("");
  const [hasRendered, setHasRendered] = React.useState(false);
  const parseFailed = !isStreaming && failedForCode === normalizedCode;

  const handleAction = React.useCallback(
    (event: ActionEvent) => {
      dispatchOpenUIAction(event, {
        appendToInput,
        openUrl: (url) => {
          WebBrowser.openBrowserAsync(url).catch((err) => {
            console.error("[OpenUIRenderer] openBrowserAsync failed:", err);
          });
        },
      }).catch((err) => {
        console.error("[OpenUIRenderer] Action dispatch failed:", err);
      });
    },
    [appendToInput],
  );

  const handleParseResult = React.useCallback(
    (result: ParseResult | null) => {
      if (!result) return;
      if (result.root !== null && !hasRendered) {
        setHasRendered(true);
      }
      const failed = result.root === null && !isStreaming;
      if (failed) {
        const errors = result.meta?.validationErrors;
        const reason = errors?.length
          ? errors
              .map((e: unknown) =>
                typeof e === "string" ? e : JSON.stringify(e),
              )
              .join("; ")
          : "Parse produced no root node";
        console.error(`[OpenUIRenderer] ${reason}`, {
          rawCode: code,
          normalizedCode,
          unresolved: result.meta?.unresolved,
          statementCount: result.meta?.statementCount,
        });
        setFailedForCode(normalizedCode);
        setFailureReason(reason);
      } else {
        setFailedForCode(null);
        setFailureReason("");
      }
    },
    [code, normalizedCode, isStreaming, hasRendered],
  );

  if (parseFailed) {
    return <OpenUIErrorCard code={code} error={failureReason} />;
  }

  const showShimmer = isStreaming && !hasRendered;

  return (
    <>
      {showShimmer ? <OpenUIShimmer /> : null}
      <View style={showShimmer ? { display: "none" } : undefined}>
        <Renderer
          response={normalizedCode}
          library={genericLibrary}
          isStreaming={isStreaming}
          onAction={handleAction}
          onParseResult={handleParseResult}
        />
      </View>
    </>
  );
}

class OpenUIErrorBoundary extends React.Component<
  { children: React.ReactNode; code: string },
  { hasError: boolean; errorMessage: string }
> {
  constructor(props: { children: React.ReactNode; code: string }) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, errorMessage: error.message };
  }

  componentDidUpdate(prevProps: { code: string }) {
    if (this.state.hasError && prevProps.code !== this.props.code) {
      this.setState({ hasError: false, errorMessage: "" });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUIRenderer] Render error:", error, info, {
      code: this.props.code,
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <OpenUIErrorCard
          code={this.props.code}
          error={this.state.errorMessage}
        />
      );
    }
    return this.props.children;
  }
}

export function OpenUIRenderer({ code, isStreaming }: OpenUIRendererProps) {
  return (
    <OpenUIErrorBoundary code={code}>
      <View className="my-1 w-full">
        <OpenUIRendererInner code={code} isStreaming={isStreaming} />
      </View>
    </OpenUIErrorBoundary>
  );
}
