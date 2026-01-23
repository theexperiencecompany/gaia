import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

export interface ValidationRule<T> {
  field: keyof T;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  pattern?: RegExp;
  custom?: (value: T[keyof T], data: T) => string | null;
  message?: string;
}

export interface UseModalFormOptions<T, R = void> {
  initialData: T | (() => T);
  onSubmit: (data: T) => Promise<R | undefined>;
  validate?: ValidationRule<T>[] | ((data: T) => string | null);
  onSuccess?: (result?: R) => void;
  onError?: (error: unknown) => void;
  resetOnSuccess?: boolean;
  closeOnSuccess?: boolean;
  successMessage?: string;
  errorMessage?: string;
}

export interface UseModalFormReturn<T> {
  formData: T;
  setFormData: React.Dispatch<React.SetStateAction<T>>;
  loading: boolean;
  errors: Partial<Record<keyof T, string>>;
  isValid: boolean;
  handleSubmit: () => Promise<void>;
  resetForm: () => void;
  validateField: (field: keyof T) => string | null;
  validateForm: () => { isValid: boolean; firstError?: string };
  clearError: (field: keyof T) => void;
  clearAllErrors: () => void;
  updateField: (field: keyof T, value: T[keyof T]) => void;
}

export function useModalForm<T extends Record<string, unknown>, R = void>({
  initialData,
  onSubmit,
  validate,
  onSuccess,
  onError,
  resetOnSuccess = true,
  closeOnSuccess: _closeOnSuccess = true,
  successMessage,
  errorMessage,
}: UseModalFormOptions<T, R>): UseModalFormReturn<T> {
  const [formData, setFormData] = useState<T>(() =>
    typeof initialData === "function" ? initialData() : initialData,
  );
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof T, string>>>({});

  // Reset form data when initialData changes
  useEffect(() => {
    const newData =
      typeof initialData === "function" ? initialData() : initialData;
    setFormData(newData);
    setErrors({});
  }, [initialData]);

  const validateField = useCallback(
    (field: keyof T): string | null => {
      if (!validate) return null;

      if (Array.isArray(validate)) {
        const rule = validate.find((r) => r.field === field);
        if (!rule) return null;

        const value = formData[field];

        if (
          rule.required &&
          (!value || (typeof value === "string" && !value.trim()))
        )
          return rule.message || `${String(field)} is required`;

        if (
          rule.minLength &&
          typeof value === "string" &&
          value.length < rule.minLength
        )
          return (
            rule.message ||
            `${String(field)} must be at least ${rule.minLength} characters`
          );

        if (
          rule.maxLength &&
          typeof value === "string" &&
          value.length > rule.maxLength
        )
          return (
            rule.message ||
            `${String(field)} must be no more than ${rule.maxLength} characters`
          );

        if (
          rule.pattern &&
          typeof value === "string" &&
          !rule.pattern.test(value)
        )
          return rule.message || `${String(field)} format is invalid`;

        if (rule.custom) return rule.custom(value, formData);
      }

      return null;
    },
    [formData, validate],
  );

  const validateForm = useCallback((): {
    isValid: boolean;
    firstError?: string;
  } => {
    if (!validate) return { isValid: true };

    const newErrors: Partial<Record<keyof T, string>> = {};
    let firstError: string | undefined;

    if (Array.isArray(validate)) {
      for (const rule of validate) {
        const error = validateField(rule.field);
        if (error) {
          newErrors[rule.field] = error;
          if (!firstError) {
            firstError = error;
          }
        }
      }
    } else {
      // Custom validation function
      const customError = validate(formData);
      if (customError) {
        firstError = customError;
        return { isValid: false, firstError };
      }
    }

    setErrors(newErrors);
    return {
      isValid: Object.keys(newErrors).length === 0,
      firstError,
    };
  }, [formData, validate, validateField]);

  const isValid = Object.keys(errors).length === 0;

  const clearError = useCallback((field: keyof T) => {
    setErrors((prev) => {
      const newErrors = { ...prev };
      delete newErrors[field];
      return newErrors;
    });
  }, []);

  const clearAllErrors = useCallback(() => {
    setErrors({});
  }, []);

  const updateField = useCallback(
    (field: keyof T, value: T[keyof T]) => {
      setFormData((prev) => ({ ...prev, [field]: value }));
      // Clear error for this field when user starts typing
      clearError(field);
    },
    [clearError],
  );

  const resetForm = useCallback(() => {
    const newData =
      typeof initialData === "function"
        ? (initialData as () => T)()
        : initialData;
    setFormData(newData);
    setErrors({});
    setLoading(false);
  }, [initialData]);

  const handleSubmit = useCallback(async () => {
    const validation = validateForm();
    if (!validation.isValid) {
      // Show validation error only on form submission
      if (validation.firstError) {
        toast.error(validation.firstError);
      }
      return;
    }

    setLoading(true);
    try {
      const result = await onSubmit(formData);

      if (successMessage) {
        toast.success(successMessage);
      }

      if (resetOnSuccess) {
        resetForm();
      }

      onSuccess?.(result as R);
    } catch (error) {
      console.error("Form submission error:", error);

      if (errorMessage) {
        toast.error(errorMessage);
      } else {
        toast.error("An error occurred. Please try again.");
      }

      onError?.(error);
    } finally {
      setLoading(false);
    }
  }, [
    formData,
    onSubmit,
    onSuccess,
    onError,
    resetOnSuccess,
    successMessage,
    errorMessage,
    validateForm,
    resetForm,
  ]);

  return {
    formData,
    setFormData,
    loading,
    errors,
    isValid,
    handleSubmit,
    resetForm,
    validateField,
    validateForm,
    clearError,
    clearAllErrors,
    updateField,
  };
}
