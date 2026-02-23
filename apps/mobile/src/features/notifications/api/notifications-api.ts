import { apiService } from "@/lib/api";

interface RegisterDeviceTokenPayload {
  token: string;
  platform: "ios" | "android";
  device_id?: string;
}

interface RegisterDeviceTokenResponse {
  success: boolean;
  message: string;
}

export const notificationsApi = {
  registerDeviceToken: async (
    payload: RegisterDeviceTokenPayload,
  ): Promise<RegisterDeviceTokenResponse> => {
    return apiService.post<RegisterDeviceTokenResponse>(
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
