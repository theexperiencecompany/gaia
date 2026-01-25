import { apiService } from "@/lib/api";

export interface LinkedAccount {
  platform: string;
  name: string;
  description: string;
  icon: string;
  available: boolean;
  linked: boolean;
  linkedAt: string | null;
}

export interface LinkedAccountsStatusResponse {
  accounts: LinkedAccount[];
}

export interface LinkedAccountsConfigResponse {
  platforms: Array<{
    id: string;
    name: string;
    description: string;
    icon: string;
    available: boolean;
  }>;
}

export const linkedAccountsApi = {
  /**
   * Get the status of all linked accounts for the current user
   */
  getStatus: async (): Promise<LinkedAccountsStatusResponse> => {
    try {
      const response = (await apiService.get("linked-accounts/status", {
        silent: true,
      })) as LinkedAccountsStatusResponse;
      return response;
    } catch (error) {
      console.error("Failed to get linked accounts status:", error);
      return { accounts: [] };
    }
  },

  /**
   * Get the configuration for all linkable platforms
   */
  getConfig: async (): Promise<LinkedAccountsConfigResponse> => {
    try {
      const response = (await apiService.get(
        "linked-accounts/config",
      )) as LinkedAccountsConfigResponse;
      return response;
    } catch (error) {
      console.error("Failed to get linked accounts config:", error);
      throw error;
    }
  },

  /**
   * Initiate OAuth flow to link a platform account
   */
  linkPlatform: (platform: string): void => {
    if (typeof window === "undefined") return;

    const currentPath = window.location.pathname + window.location.search;
    const backendUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
    const fullUrl = `${backendUrl}linked-accounts/link/${platform}?redirect_path=${encodeURIComponent(currentPath)}`;

    window.location.href = fullUrl;
  },

  /**
   * Unlink a platform account
   */
  unlinkPlatform: async (platform: string): Promise<void> => {
    try {
      await apiService.delete(
        `linked-accounts/${platform}`,
        {},
        { successMessage: "Account unlinked successfully" },
      );
    } catch (error) {
      console.error(`Failed to unlink ${platform}:`, error);
      throw error;
    }
  },
};
