import { CONNECT_LINK_ERROR_MESSAGES } from "../constants/connect";

/** The dead-link state: nothing to continue to. */
export function ConnectLinkExpired() {
  return (
    <>
      <h1 className="mb-2 text-xl font-semibold text-white">
        Connect your integration
      </h1>
      <p className="text-sm text-zinc-400">
        {CONNECT_LINK_ERROR_MESSAGES.invalid_or_expired_link}
      </p>
    </>
  );
}
