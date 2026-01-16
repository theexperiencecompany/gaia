import type React from "react";

import CopyButton from "@/features/chat/components/code-block/CopyButton";
import {
  Cancel01Icon,
  CheckmarkCircle02Icon,
  SourceCodeCircleIcon,
} from "@/icons";

interface CodeExecutionOutputProps {
  output?: {
    stdout: string;
    stderr: string;
    results: string[];
    error: string | null;
  } | null;
  status?: "executing" | "completed" | "error";
  language: string;
  onCopy: () => void;
  copied: boolean;
}

const CodeExecutionOutput: React.FC<CodeExecutionOutputProps> = ({
  output,
  status,
  language,
  onCopy,
  copied,
}) => {
  const getStatusIcon = () => {
    if (status === "executing") {
      return (
        <div className="h-3 w-3 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
      );
    }
    if (status === "error" || output?.error) {
      return <Cancel01Icon className="h-3 w-3 text-red-400" />;
    }
    if (status === "completed" && output && !output.error) {
      return <CheckmarkCircle02Icon className="h-3 w-3 text-green-400" />;
    }
    return <SourceCodeCircleIcon className="h-3 w-3 text-foreground-400" />;
  };

  const getStatusText = () => {
    if (status === "executing") return "Running";
    if (status === "error" || output?.error) return "Failed";
    if (status === "completed" && output && !output.error) return "Success";
    return "Output";
  };

  const shouldShowCopyButton =
    output && (output.stdout || output.stderr || output.results?.length);

  return (
    <div className="w-full overflow-hidden rounded-2xl bg-surface-200">
      {/* Header */}
      <div className="p flex items-center justify-between bg-surface-100 px-4 py-2">
        <div className="flex items-center gap-2">
          {getStatusIcon()}
          <span className="text-sm font-medium text-foreground-200">
            {getStatusText()}
          </span>
        </div>
        {shouldShowCopyButton && (
          <CopyButton copied={copied} onPress={onCopy} />
        )}
      </div>

      {/* Content */}
      <div className="bg-surface-100 p-3 pt-0">
        {status === "executing" && !output ? (
          <div className="flex items-center gap-3 py-4 text-foreground-400">
            <div className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
            <span className="text-sm">Executing {language} code...</span>
          </div>
        ) : output ? (
          <div className="space-y-3">
            {/* Standard Output */}
            {output.stdout && (
              <div className="bg-black p-3 font-mono text-sm text-green-400">
                <pre className="whitespace-pre-wrap">{output.stdout}</pre>
              </div>
            )}

            {/* Results Output */}
            {output.results && output.results.length > 0 && (
              <div>
                <div className="bg-black p-3 font-mono text-sm text-blue-400">
                  {output.results.map((result, index) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: stable array
                    <pre key={result + index} className="whitespace-pre-wrap">
                      {result}
                    </pre>
                  ))}
                </div>
              </div>
            )}

            {/* Standard Error */}
            {output.stderr && (
              <div>
                <div className="bg-black p-3 font-mono text-sm text-red-400">
                  <pre className="whitespace-pre-wrap">{output.stderr}</pre>
                </div>
              </div>
            )}

            {/* Execution Error */}
            {output.error && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-foreground-500">
                  EXECUTION ERROR
                </div>
                <div className="bg-black p-3 font-mono text-sm text-red-400">
                  <pre className="whitespace-pre-wrap">{output.error}</pre>
                </div>
              </div>
            )}

            {/* Status */}
            <div className="flex items-center justify-between pb-3 text-xs text-foreground-500">
              <span>Status: {status || "unknown"}</span>
              {!output.error && !output.stderr ? (
                <span className="text-green-400">Success</span>
              ) : (
                <span className="text-red-400">Failed</span>
              )}
            </div>

            {/* No output message */}
            {!output.stdout &&
              !output.stderr &&
              !output.results?.length &&
              !output.error && (
                <div className="py-4 text-center text-sm text-foreground-500">
                  No output produced
                </div>
              )}
          </div>
        ) : (
          <div className="py-4 text-center text-sm text-foreground-500">
            Ready to execute
          </div>
        )}
      </div>
    </div>
  );
};

export default CodeExecutionOutput;
