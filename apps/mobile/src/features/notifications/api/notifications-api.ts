import type {
  PushTokenRequest,
  PushTokenResponse,
} from "@gaia/shared/api/generated";
import { apiService } from "@/lib/api";

export const notificationsApi = {
  registerDeviceToken: async (
    payload: PushTokenRequest,
  ): Promise<PushTokenResponse> => {
    return apiService.post<PushTokenResponse>(
      "/notifications/register-device",
      payload,
    );
  },

  unregisterDeviceToken: async (token: string): Promise<void> => {
    return apiService.post("/notifications/unregister-device", {
      token,
    });
  },
};
