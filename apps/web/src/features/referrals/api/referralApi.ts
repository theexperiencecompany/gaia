import type { AxiosError } from "axios";

import { apiService } from "@/lib/api/service";

import type {
  InviteContact,
  InviteResult,
  ReferralOverview,
  ResolveCodeResult,
  UpdateCodeResult,
} from "../types";

interface InviteContactsResponse {
  contacts: InviteContact[];
}

// Helper function for consistent error handling
interface ApiErrorResponse {
  detail?: string;
  message?: string;
}

const handleApiError = (error: unknown, context: string): never => {
  let errorMessage = "An unexpected error occurred";
  let status: number | undefined;

  if (error && typeof error === "object" && "isAxiosError" in error) {
    const axiosError = error as AxiosError<ApiErrorResponse>;
    errorMessage =
      axiosError.response?.data?.detail ||
      axiosError.response?.data?.message ||
      axiosError.message ||
      errorMessage;
    status = axiosError.response?.status;
  } else if (error instanceof Error) {
    errorMessage = error.message;
  }

  console.error(`${context} failed:`, {
    error: errorMessage,
    status,
  });

  throw new Error(errorMessage);
};

class ReferralApi {
  // Get the current user's referral overview
  async getOverview(): Promise<ReferralOverview> {
    try {
      return await apiService.get<ReferralOverview>("/referrals/me");
    } catch (error) {
      return handleApiError(error, "Get referral overview");
    }
  }

  // Resolve a referral code (public — used by the landing page)
  async resolveCode(code: string): Promise<ResolveCodeResult> {
    try {
      return await apiService.get<ResolveCodeResult>(
        `/referrals/resolve/${code}`,
      );
    } catch (error) {
      return handleApiError(error, "Resolve referral code");
    }
  }

  // Invite friends by email
  async invite(emails: string[]): Promise<InviteResult> {
    try {
      return await apiService.post<InviteResult>("/referrals/invite", {
        emails,
      });
    } catch (error) {
      return handleApiError(error, "Invite friends");
    }
  }

  // Suggest Google contacts to invite (returns [] when Gmail isn't connected)
  async getInviteContacts(): Promise<InviteContact[]> {
    try {
      const { contacts } = await apiService.get<InviteContactsResponse>(
        "/referrals/contacts",
      );
      return contacts;
    } catch (error) {
      return handleApiError(error, "Get invite contacts");
    }
  }

  // Update the user's referral code
  async updateCode(code: string): Promise<UpdateCodeResult> {
    try {
      return await apiService.patch<UpdateCodeResult>("/referrals/code", {
        code,
      });
    } catch (error) {
      return handleApiError(error, "Update referral code");
    }
  }
}

export const referralApi = new ReferralApi();
