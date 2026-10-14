import { api } from "@/lib/api/typed";

export const devicesApi = {
  // Polled every 15s for presence, so never a user action.
  list: () =>
    api.get("/api/v1/device/list", { silent: true, background: true }),

  approve: (userCode: string) =>
    api.post("/api/v1/device/pair/approve", {
      body: { user_code: userCode },
      errorMessage: "Could not approve this device",
    }),

  revoke: (deviceId: string) =>
    api.delete("/api/v1/device/{device_id}", {
      path: { device_id: deviceId },
      successMessage: "Device revoked",
      errorMessage: "Could not revoke device",
    }),
};
