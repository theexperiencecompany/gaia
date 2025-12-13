"use client";

import { useCallback, useState } from "react";

export interface PaymentFlowStates {
  isInitiating: boolean;
  isProcessing: boolean;
  isVerifying: boolean;
  isComplete: boolean;
  error: string | null;
}

export const usePaymentFlow = () => {
  const [states, setStates] = useState<PaymentFlowStates>({
    isInitiating: false,
    isProcessing: false,
    isVerifying: false,
    isComplete: false,
    error: null,
  });

  const setInitiating = useCallback((value: boolean) => {
    setStates((prev) => ({ ...prev, isInitiating: value, error: null }));
  }, []);

  const setProcessing = useCallback((value: boolean) => {
    setStates((prev) => ({ ...prev, isProcessing: value, error: null }));
  }, []);

  const setVerifying = useCallback((value: boolean) => {
    setStates((prev) => ({ ...prev, isVerifying: value, error: null }));
  }, []);

  const setComplete = useCallback((value: boolean) => {
    setStates((prev) => ({ ...prev, isComplete: value, error: null }));
  }, []);

  const setError = useCallback((error: string | null) => {
    setStates((prev) => ({
      ...prev,
      error,
      isInitiating: false,
      isProcessing: false,
      isVerifying: false,
      isComplete: false,
    }));
  }, []);

  const reset = useCallback(() => {
    setStates({
      isInitiating: false,
      isProcessing: false,
      isVerifying: false,
      isComplete: false,
      error: null,
    });
  }, []);

  return {
    states,
    setInitiating,
    setProcessing,
    setVerifying,
    setComplete,
    setError,
    reset,
  };
};
