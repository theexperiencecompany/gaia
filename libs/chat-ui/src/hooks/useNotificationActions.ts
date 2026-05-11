import { useRouter } from "next/navigation";
import { useState } from "react";
import { useConfirmation } from "@/hooks/useConfirmation";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  type ActionResult,
  type ActionResultData,
  ActionStyle,
  ActionType,
  type ApiCallConfig,
  type ModalConfig,
  type NotificationAction,
  type RedirectConfig,
} from "@/types/features/notificationTypes";

interface UseNotificationActionsOptions {
  onSuccess?: (result: ActionResult) => void;
  onError?: (error: Error) => void;
  onModalOpen?: (config: ModalConfig) => void;
}

export function useNotificationActions(
  options: UseNotificationActionsOptions = {},
) {
  const [loading, setLoading] = useState<string | null>(null);
  const router = useRouter();
  const { confirm, confirmationProps } = useConfirmation();

  const executeAction = async (
    notificationId: string,
    action: NotificationAction,
  ): Promise<void> => {
    if (action.disabled) {
      toast.error("This action is currently disabled");
      return;
    }

    if (action.executed) {
      toast.error("This action has already been executed");
      return;
    }

    // Show confirmation dialog for workflow and api_call actions
    if (
      (action.type === ActionType.WORKFLOW ||
        action.type === ActionType.API_CALL) &&
      (action.requires_confirmation || action.confirmation_message)
    ) {
      const confirmed = await confirm({
        title: "Confirm Action",
        message:
          action.confirmation_message ||
          "Are you sure you want to perform this action?",
        confirmText: "Continue",
        cancelText: "Cancel",
        variant:
          action.style === ActionStyle.DANGER ? "destructive" : "default",
      });
      if (!confirmed) return;
    }

    // Set loading state only for API_CALL and WORKFLOW actions
    if (
      action.type === ActionType.API_CALL ||
      action.type === ActionType.WORKFLOW
    ) {
      setLoading(action.id);
    }

    try {
      switch (action.type) {
        case ActionType.API_CALL:
          await handleApiCall(notificationId, action);
          break;
        case ActionType.REDIRECT:
          await handleRedirect(notificationId, action);
          break;
        case ActionType.MODAL:
          await handleModal(notificationId, action);
          break;
        case ActionType.WORKFLOW:
          await handleWorkflow(notificationId, action);
          break;
        default:
          throw new Error(`Unsupported action type: ${action.type}`);
      }
    } catch (error) {
      console.error("Action execution failed:", error);
      const errorMessage =
        error instanceof Error ? error.message : "Action failed";
      toast.error(errorMessage);
      options.onError?.(
        error instanceof Error ? error : new Error(errorMessage),
      );
    } finally {
      // Only clear loading for API_CALL and WORKFLOW actions
      if (
        action.type === ActionType.API_CALL ||
        action.type === ActionType.WORKFLOW
      ) {
        setLoading(null);
      }
    }
  };

  const handleApiCall = async (
    notificationId: string,
    action: NotificationAction,
  ): Promise<void> => {
    const config = action.config.api_call as ApiCallConfig;
    if (!config) {
      throw new Error("API call configuration is missing");
    }

    try {
      const result = await NotificationsAPI.executeAction(
        notificationId,
        action.id,
      );

      if (result.success) {
        toast.success(result.message);
        // Convert NotificationResponse to ActionResult format for callback
        const actionResult: ActionResult = {
          success: result.success,
          message: result.message,
          data: result.data as ActionResultData, // Type assertion since we know it's ActionResultData for API calls
        };
        options.onSuccess?.(actionResult);
      } else {
        const errorMessage =
          result.message || config.error_message || "Action failed";
        toast.error(errorMessage);
      }
    } catch (error) {
      const errorMessage = config.error_message || "Failed to execute action";
      toast.error(errorMessage);
      throw error;
    }
  };

  const handleRedirect = async (
    _notificationId: string,
    action: NotificationAction,
  ): Promise<void> => {
    const config = action.config.redirect as RedirectConfig;
    if (!config?.url) {
      throw new Error("Redirect URL is missing");
    }

    try {
      // Execute the action on the backend first (for tracking)
      // await NotificationsAPI.executeAction(notificationId, action.id);

      // Handle the redirect
      if (config.open_in_new_tab) {
        window.open(config.url, "_blank", "noopener,noreferrer");
      } else {
        // Check if it's an external URL
        if (
          config.url.startsWith("http://") ||
          config.url.startsWith("https://")
        ) {
          window.location.href = config.url;
        } else {
          // Internal route
          router.push(config.url);
        }
      }
    } catch (error) {
      console.error("Redirect failed:", error);
      throw new Error("Failed to execute redirect action");
    }
  };

  const handleModal = async (
    notificationId: string,
    action: NotificationAction,
  ): Promise<void> => {
    const config = action.config.modal as ModalConfig;
    if (!config) {
      throw new Error("Modal configuration is missing");
    }

    // Enhance the modal config with notification and action context
    const enhancedConfig: ModalConfig = {
      ...config,
      props: {
        ...config.props,
        notificationId,
        actionId: action.id,
      },
    };

    // For modal actions, open the modal immediately without loading state
    options.onModalOpen?.(enhancedConfig);
  };

  const handleWorkflow = async (
    notificationId: string,
    action: NotificationAction,
  ): Promise<void> => {
    try {
      const result = await NotificationsAPI.executeAction(
        notificationId,
        action.id,
      );

      if (result.success) {
        toast.success(result.message || "Workflow started successfully");
        // Convert NotificationResponse to ActionResult format for callback
        const actionResult: ActionResult = {
          success: result.success,
          message: result.message,
          data: result.data as ActionResultData, // Type assertion since we know it's ActionResultData for workflow calls
        };
        options.onSuccess?.(actionResult);
      } else {
        toast.error(result.message || "Failed to start workflow");
      }
    } catch (error) {
      console.error("Workflow execution failed:", error);
      throw new Error("Failed to execute workflow action");
    }
  };

  const getActionButtonProps = (action: NotificationAction) => {
    const isExecuted = action.executed || false;
    const isLoading = loading === action.id;

    const baseProps = {
      disabled: action.disabled || isLoading || isExecuted,
      loading: isLoading,
      executed: isExecuted,
    };

    switch (action.style) {
      case "primary":
        return {
          ...baseProps,
          variant: "default" as const,
          className: "bg-blue-600 hover:bg-blue-700 text-white",
        };
      case "secondary":
        return {
          ...baseProps,
          variant: "secondary" as const,
          className: "bg-zinc-700 hover:bg-zinc-600 text-white",
        };
      case "danger":
        return {
          ...baseProps,
          variant: "destructive" as const,
          className: "bg-red-600 hover:bg-red-700 text-white",
        };
      default:
        return {
          ...baseProps,
          variant: "outline" as const,
        };
    }
  };

  return {
    executeAction,
    loading,
    getActionButtonProps,
    confirmationProps,
  };
}
