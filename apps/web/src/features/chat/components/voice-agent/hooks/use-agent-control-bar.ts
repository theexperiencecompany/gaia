import {
  type TrackReferenceOrPlaceholder,
  useLocalParticipant,
  usePersistentUserChoices,
  useRoomContext,
  useTrackToggle,
} from "@livekit/components-react";
import { Track } from "livekit-client";
import * as React from "react";

import { usePublishPermissions } from "./use-publish-permissions";

export interface ControlBarControls {
  microphone?: boolean;
  chat?: boolean;
  leave?: boolean;
}

export interface UseAgentControlBarProps {
  controls?: ControlBarControls;
  saveUserChoices?: boolean;
  onDeviceError?: (error: { source: Track.Source; error: Error }) => void;
}

export interface UseAgentControlBarReturn {
  micTrackRef: TrackReferenceOrPlaceholder;
  visibleControls: ControlBarControls;
  microphoneToggle: ReturnType<typeof useTrackToggle<Track.Source.Microphone>>;
  handleDisconnect: () => void;
  handleAudioDeviceChange: (deviceId: string) => void;
}

export function useAgentControlBar(
  props: UseAgentControlBarProps = {},
): UseAgentControlBarReturn {
  const { controls, saveUserChoices = true } = props;
  const visibleControls = {
    leave: true,
    ...controls,
  };
  const { microphoneTrack, localParticipant } = useLocalParticipant();
  const publishPermissions = usePublishPermissions();
  const room = useRoomContext();

  const microphoneToggle = useTrackToggle({
    source: Track.Source.Microphone,
    onDeviceError: (error) =>
      props.onDeviceError?.({ source: Track.Source.Microphone, error }),
  });

  const micTrackRef = React.useMemo(() => {
    return {
      participant: localParticipant,
      source: Track.Source.Microphone,
      publication: microphoneTrack,
    };
  }, [localParticipant, microphoneTrack]);

  visibleControls.microphone ??= publishPermissions.microphone;
  visibleControls.chat ??= publishPermissions.data;

  const { saveAudioInputEnabled, saveAudioInputDeviceId } =
    usePersistentUserChoices({
      preventSave: !saveUserChoices,
    });

  const handleDisconnect = React.useCallback(async () => {
    if (room) {
      await room.disconnect();
    }
  }, [room]);

  const handleAudioDeviceChange = React.useCallback(
    (deviceId: string) => {
      saveAudioInputDeviceId(deviceId ?? "default");
    },
    [saveAudioInputDeviceId],
  );

  const handleToggleMicrophone = React.useCallback(
    async (enabled?: boolean) => {
      await microphoneToggle.toggle(enabled);
      // persist audio input enabled preference
      saveAudioInputEnabled(!microphoneToggle.enabled);
    },
    [microphoneToggle, saveAudioInputEnabled],
  );

  return {
    micTrackRef,
    visibleControls,
    microphoneToggle: {
      ...microphoneToggle,
      toggle: handleToggleMicrophone,
    },
    handleDisconnect,
    handleAudioDeviceChange,
  };
}
