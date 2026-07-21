export interface DeviceServer {
  server_key: string;
  display_name: string;
  integration_id: string;
  status: string;
  tools_synced_at: string | null;
}

export interface Device {
  id: string;
  name: string;
  platform: string | null;
  daemon_version: string | null;
  status: string;
  online: boolean;
  last_seen_at: string | null;
  created_at: string;
  servers: DeviceServer[];
}

export interface DeviceListResponse {
  devices: Device[];
}

export interface ApproveDeviceResponse {
  device_id: string;
  name: string;
}
