import { apiService } from "@/lib/api/service";
import type { ApproveDeviceResponse, DeviceListResponse } from "../types";

export const devicesApi = {
  list: () =>
    apiService.get<DeviceListResponse>("/device/list", { silent: true }),

  approve: (userCode: string) =>
    apiService.post<ApproveDeviceResponse>(
      "/device/pair/approve",
      { user_code: userCode },
      { errorMessage: "Could not approve this device" },
    ),

  revoke: (deviceId: string) =>
    apiService.delete(`/device/${deviceId}`, {
      successMessage: "Device revoked",
      errorMessage: "Could not revoke device",
    }),
};
