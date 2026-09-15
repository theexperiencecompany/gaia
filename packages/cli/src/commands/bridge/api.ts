// The device-bridge REST client lives in bridge-core; response types come from
// the generated API schema.

export type {
  DeviceTokenResponse,
  PollPairingResponse,
  StartPairingResponse,
} from "@gaia/shared/api/generated";
export {
  ApiError,
  exchangeToken,
  pollPairing,
  registerServer,
  startPairing,
} from "@gaia/shared/bridge-core/api";
