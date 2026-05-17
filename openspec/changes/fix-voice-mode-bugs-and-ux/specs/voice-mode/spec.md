## ADDED Requirements

### Requirement: Voice mode state persists across route navigation

Voice mode activation state SHALL be stored in a global Zustand store (`voiceModeStore`), not in any single page or component's local state. The store SHALL hold at minimum:

- `voiceModeActive: boolean`
- `voiceSessionId: string | null` — a fresh id minted on every `enterVoiceMode()` call
- `discoveredConversationId: string | null`

Components rendering voice mode UI SHALL read these values from the store, so that a Next.js route remount (e.g., the `/c → /c/:id` redirect after the worker emits `conversation_id`) does not cause voice mode to deactivate.

#### Scenario: Worker emits conversation_id after voice mode starts in `/c`

- **WHEN** the user activates voice mode on `/c` (no id), the worker emits a `conversation_id`, and `router.replace("/c/<id>")` is called
- **THEN** the new route mounts with voice mode still active, the gradient still visible, and the same voice session continuing — no flash of the new-chat template

#### Scenario: User leaves voice mode

- **WHEN** the user presses end-call
- **THEN** `voiceModeActive` becomes false in the store, `voiceSessionId` is cleared, and the next time voice mode is entered a new `voiceSessionId` is generated

### Requirement: Voice and text messages share a single store

Voice turns (user transcriptions grouped per session boundary, agent turns) SHALL be written into the same `chatStore` that text-mode messages flow through. The chat message renderer SHALL read messages exclusively from `chatStore` (via `useConversation()`); it SHALL NOT accept an override prop for voice-mode messages.

#### Scenario: User activates voice mode mid-conversation with existing text history

- **WHEN** the user has a `/c/<id>` conversation with prior text messages and activates voice mode
- **THEN** all prior text messages remain visible in the message list, and any subsequent voice turns appear below them in chronological order

#### Scenario: Voice turn message_ids reconcile with server canonical on sync

- **WHEN** the user ends a voice call and `syncSingleConversation(id)` runs
- **THEN** the server-canonical messages reconcile by `message_id` with the locally-stored voice turns; no duplicate bubble is rendered, even if the canonical version includes content (e.g., emoji) that the local voice turn omitted

### Requirement: Consecutive user transcriptions group into a single message

User transcriptions arriving between two bot turns SHALL be merged into a single `MessageType` for that user group. The grouped message's `response` field SHALL join each transcription's text with the `<NEW_MESSAGE_BREAK>` token. The renderer SHALL use `splitMessageByBreaks` (from `libs/shared/ts/src/utils/messageBreakUtils.ts`) to display each split as a paragraph break within the same user bubble. When a bot turn starts, the active user group SHALL be closed and the next transcription SHALL open a new group.

#### Scenario: User pauses three times while speaking, then bot responds

- **WHEN** the user speaks, pauses, speaks, pauses, speaks, pauses, speaks — producing four finalised LiveKit transcriptions — and then the bot responds
- **THEN** the message list shows a single user bubble containing all four utterances separated by paragraph breaks, followed by one bot bubble (or loading indicator) below it

#### Scenario: User speaks again after a bot response

- **WHEN** the user, having received a bot response, speaks a new utterance
- **THEN** a brand-new user bubble appears below the bot bubble (the prior user group is closed; the new transcription starts a fresh group)

### Requirement: Connection-state procedural spectrum animation

While the voice session is in the `isConnecting` state (room not yet connected, or agent state is `connecting`), the spectrum SHALL be driven by a procedural low-pass-filtered random walk source, producing a visibly vibrating gradient. When `isConnecting` transitions to false, the loading amplitude SHALL decay to zero over approximately 300 ms, after which the spectrum source SHALL switch to `"mic"` (agent state `listening`) or `"agent-track"` (agent state `speaking`) per the existing source selection.

#### Scenario: User activates voice mode

- **WHEN** the user clicks the voice-mode button and the LiveKit room is still negotiating
- **THEN** the gradient's waveforms visibly vibrate (procedural jitter, organic feel, not buzzy), the "Preparing voice mode" chip is visible, and the gradient does not appear flat or dead

#### Scenario: Agent transitions to listening

- **WHEN** the agent state transitions from `connecting` to `listening`
- **THEN** the loading jitter fades smoothly to zero over ~300 ms, the "Preparing voice mode" chip dismisses, and the gradient transitions to mic-driven spectrum without a visual snap or jump

### Requirement: Gradient initialization guards against silent shader link failure

The `VoiceGradient` component SHALL check `gl.getProgramParameter(prog, gl.LINK_STATUS)` after every `linkProgram` call. On failure, the component SHALL log the program info log via `console.warn`, delete the program, recompile both shaders, and attempt one re-link. If the re-link also fails, the component SHALL log an explicit permanent-failure message via `console.error` and render nothing (no silent black canvas, no infinite RAF loop). The `VoiceModeBackground` component SHALL pass `key={voiceSessionId}` to the gradient to force a fresh canvas mount on every voice session.

#### Scenario: Dev-mode StrictMode mount/cleanup/remount cycle

- **WHEN** React StrictMode invokes the gradient's ref callback twice in dev (mount → cleanup → mount), and the second `linkProgram` succeeds
- **THEN** the gradient renders normally (no warn), the LINK_STATUS check passes on both attempts, and the spectrum animates

#### Scenario: Voice session restarts via enterVoiceMode

- **WHEN** the user exits voice mode and re-enters it
- **THEN** `voiceSessionId` changes, the gradient unmounts the previous canvas and mounts a fresh canvas, and the gradient renders without depending on any state from the prior session

## MODIFIED Requirements

### Requirement: Voice messages render through the existing chat renderer

Voice-mode user transcriptions and agent turns SHALL be rendered by `ChatRenderer` (via `ChatBubbleUser` and `ChatBubbleBot`). `ChatRenderer` SHALL read its data source EXCLUSIVELY from `useConversation()` (the shared chat store) — it SHALL NOT accept a `convoMessages` prop override. Tool calls, tool outputs, OpenUI cards, loading indicators, and follow-up actions produced during a voice turn SHALL appear in the same visual form as in text mode.

#### Scenario: Agent invokes tools during a voice call

- **WHEN** the agent issues tool calls (e.g., fetch calendar events and send email) during a voice response
- **THEN** the message stream displays the same tool cards (integration required cards, executor task list, tool-output cards) that text mode would render for the same agent action

#### Scenario: Final response includes follow-up actions

- **WHEN** the agent's final response is accompanied by suggested follow-up actions
- **THEN** the follow-up-action chips render under the agent bubble exactly as in text mode

#### Scenario: Loading indicator during agent thinking

- **WHEN** the agent is in the `thinking` state with no message text yet streamed
- **THEN** the existing `LoadingIndicator` component is shown beneath the last bubble, using the same loading-text/tool-info pipeline as text mode

#### Scenario: Bot turn sequences after a closed user group

- **WHEN** a user group closes (because a bot turn started) and the bot bubble appears
- **THEN** the bot bubble renders strictly BELOW the user group in the message list — even if the bot's first event timestamp predates the user transcription's finalisation timestamp (preemptive generation)

### Requirement: Voice visualizer is the gradient, driven by the active audio source

The voice visualizer SHALL be the WebGL2 `VoiceGradient` component. A single spectrum hook SHALL select its audio source based on the LiveKit agent state and connection state:

- `isConnecting === true` → procedural loading source (low-pass-filtered jitter, fades on transition)
- `listening` → local microphone input
- `speaking` → remote agent audio track
- `thinking`, `disconnected` (after connection) → idle envelope (low-amplitude synthetic)

The previous orb and bar-visualizer components SHALL NOT be rendered in voice mode.

#### Scenario: Agent transitions from listening to speaking

- **WHEN** the agent state changes from `listening` to `speaking`
- **THEN** the spectrum source switches from microphone to the remote agent audio track within one render frame, and the gradient reacts to the agent's TTS audio

#### Scenario: Agent enters thinking state

- **WHEN** the agent state is `thinking` (post user-turn, pre-response)
- **THEN** the gradient renders the idle envelope (subtle ambient motion) and not the prior speaking-track waveform

#### Scenario: While connecting

- **WHEN** the room is not yet connected or `agentState === "connecting"`
- **THEN** the spectrum source is the procedural loading source and the gradient visibly vibrates

#### Scenario: WebGL2 is unavailable

- **WHEN** the browser does not support WebGL2
- **THEN** voice mode SHALL still function (audio + control bar + message rendering) and a non-animated fallback visual is shown in place of the gradient

### Requirement: Known limitation — mid-utterance pause may end the user turn

Voice turn detection MAY occasionally treat a short mid-sentence pause as end-of-turn from LiveKit's perspective, producing multiple finalised transcription streams in succession. The UI SHALL collapse such consecutive transcriptions into a single user bubble with paragraph breaks (see "Consecutive user transcriptions group into a single message"). The system SHALL NOT introduce a fixed minimum-silence threshold long enough to materially degrade response latency.

#### Scenario: User pauses briefly while still speaking

- **WHEN** a user pauses for a fraction of a second mid-utterance and LiveKit finalises the transcription stream
- **THEN** the next transcription appends to the same user bubble with a `<NEW_MESSAGE_BREAK>` separator; the user does not see a fragmentation of their utterance into multiple bubbles

### Requirement: No post-disconnect URL refetch

Ending a voice call SHALL NOT push a new route with a `?sync=true` (or equivalent) query parameter to trigger a refetch of the conversation. Voice turns are already in the chat store (written during the call); after hang-up `syncSingleConversation(id)` SHALL run silently to reconcile with server canonical, but the URL SHALL NOT change.

#### Scenario: User ends call

- **WHEN** the user presses the end-call button
- **THEN** the route remains at `/c/<id>` (no query string is appended), the voice control bar is replaced by the text composer, and all turns produced during the call remain rendered in the message list (with stable `message_id`s that reconcile with server canonical)
