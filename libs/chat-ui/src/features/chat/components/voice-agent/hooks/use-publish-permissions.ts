import { useLocalParticipantPermissions } from "@livekit/components-react";
import { Track } from "livekit-client";

const trackSourceToProtocol = (source: Track.Source) => {
  // NOTE: this mapping avoids importing the protocol package as that leads to a significant bundle size increase
  switch (source) {
    case Track.Source.Microphone:
      return 2;
    default:
      return 0;
  }
};

export interface PublishPermissions {
  microphone: boolean;
  data: boolean;
}

export function usePublishPermissions(): PublishPermissions {
  const localPermissions = useLocalParticipantPermissions();

  const canPublishSource = (source: Track.Source) => {
    return (
      !!localPermissions?.canPublish &&
      (localPermissions.canPublishSources.length === 0 ||
        localPermissions.canPublishSources.includes(
          trackSourceToProtocol(source),
        ))
    );
  };

  return {
    microphone: canPublishSource(Track.Source.Microphone),
    data: localPermissions?.canPublishData ?? false,
  };
}
