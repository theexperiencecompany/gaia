/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { ReactNode } from "react";

export interface ToastOptions {
  id?: string;
  description?: ReactNode | string;
  duration?: number;
  icon?: ReactNode;
  action?: {
    label: string;
    onClick: () => void;
  };
}

const noopId = (_message: string, _opts?: ToastOptions): string => "";

export const toast = {
  success: noopId,
  error: noopId,
  warning: noopId,
  info: noopId,
  loading: (_message: string, _opts?: ToastOptions): string => "",
  dismiss: (_id: string): void => {},
  clear: (_position?: unknown): void => {},
};
