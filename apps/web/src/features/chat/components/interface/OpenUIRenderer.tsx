import { type ActionEvent, Renderer } from "@openuidev/react-lang";
import React from "react";
import { dispatchOpenUIAction } from "@/features/chat/actions/openUIActionDispatcher";
import { useAppendToInput } from "@/stores/composerStore";

interface OpenUIRendererProps {
  code: string;
  isStreaming: boolean;
}

function OpenUIRendererInner({ code, isStreaming }: OpenUIRendererProps) {
  const appendToInput = useAppendToInput();

  const handleAction = React.useCallback(
    (event: ActionEvent) => {
      dispatchOpenUIAction(event, appendToInput).catch((err) => {
        console.error("[OpenUIRenderer] Action dispatch failed:", err);
      });
    },
    [appendToInput],
  );

  return (
    <Renderer
      response={code}

      isStreaming={isStreaming}
      onAction={handleAction}
    />
  );
}

class OpenUIErrorBoundary extends React.Component<
  { children: React.ReactNode; fallbackText: string },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode; fallbackText: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: { fallbackText: string }) {
    if (
      this.state.hasError &&
      prevProps.fallbackText !== this.props.fallbackText
    ) {
      this.setState({ hasError: false });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUIRenderer] Render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <pre className="whitespace-pre-wrap text-sm text-zinc-400">
          {this.props.fallbackText}
        </pre>
      );
    }
    return this.props.children;
  }
}

export default function OpenUIRenderer({
  code,
  isStreaming,
}: OpenUIRendererProps) {
  return (
    <OpenUIErrorBoundary fallbackText={code}>
      <OpenUIRendererInner code={code} isStreaming={isStreaming} />
    </OpenUIErrorBoundary>
  );
}
