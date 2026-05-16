## ADDED Requirements

### Requirement: Unified chat surface for text and voice modes

Voice mode SHALL render inside the same chat layout used by text mode. The chat layout SHALL accept a swappable bottom-bar slot that displays the text composer in text mode and the voice control bar in voice mode. All other chrome — scrollable message area, scroll-to-bottom button, drag-and-drop file handling, conversation header — SHALL be identical across modes.

#### Scenario: User enters voice mode from an active conversation

- **WHEN** a user activates voice mode while viewing a conversation in `/c/<id>`
- **THEN** the URL does not change, the message scroll area remains mounted with its existing messages, and the bottom composer is replaced by the voice control bar without unmounting the message renderer

#### Scenario: User leaves voice mode

- **WHEN** the user ends the voice call
- **THEN** the voice control bar is replaced by the text composer in place, the message list remains intact, and the URL is unchanged (no `?sync=true` query parameter is appended)

### Requirement: Voice messages render through the existing chat renderer

Voice-mode user transcriptions and agent turns SHALL be rendered by `ChatRenderer` (via `ChatBubbleUser` and `ChatBubbleBot`). Tool calls, tool outputs, OpenUI cards, loading indicators, and follow-up actions produced during a voice turn SHALL appear in the same visual form as in text mode.

#### Scenario: Agent invokes tools during a voice call

- **WHEN** the agent issues tool calls (e.g., fetch calendar events and send email) during a voice response
- **THEN** the message stream displays the same tool cards (integration required cards, executor task list, tool-output cards) that text mode would render for the same agent action

#### Scenario: Final response includes follow-up actions

- **WHEN** the agent's final response is accompanied by suggested follow-up actions
- **THEN** the follow-up-action chips render under the agent bubble exactly as in text mode

#### Scenario: Loading indicator during agent thinking

- **WHEN** the agent is in the `thinking` state with no message text yet streamed
- **THEN** the existing `LoadingIndicator` component is shown beneath the last bubble, using the same loading-text/tool-info pipeline as text mode

### Requirement: Voice visualizer is the gradient, driven by the active audio source

The voice visualizer SHALL be the WebGL2 `VoiceGradient` component. A single spectrum hook SHALL select its audio source based on the LiveKit agent state:

- `listening` → local microphone input
- `speaking` → remote agent audio track
- `thinking`, `connecting`, `disconnected` → idle envelope (low-amplitude synthetic)

The previous orb and bar-visualizer components SHALL NOT be rendered in voice mode.

#### Scenario: Agent transitions from listening to speaking

- **WHEN** the agent state changes from `listening` to `speaking`
- **THEN** the spectrum source switches from microphone to the remote agent audio track within one render frame, and the gradient reacts to the agent's TTS audio

#### Scenario: Agent enters thinking state

- **WHEN** the agent state is `thinking` (post user-turn, pre-response)
- **THEN** the gradient renders the idle envelope (subtle ambient motion) and not the prior speaking-track waveform

#### Scenario: WebGL2 is unavailable

- **WHEN** the browser does not support WebGL2
- **THEN** voice mode SHALL still function (audio + control bar + message rendering) and a non-animated fallback visual is shown in place of the gradient

### Requirement: TTS speaks only the final assistant response prose

Only text from the chat-stream `response` events SHALL be forwarded to TTS. After the `main_response_complete` boundary event, no further chunks SHALL be forwarded to TTS. Each `response` chunk SHALL be sanitized before TTS to remove:

- OpenUI / HTML-style tags (e.g., `<Label …>`, `</Section>`, `<Text foo="bar">`) including their attributes
- Sentinel tokens `_BREAK`, `_MESSAGE`, `NEW`, and bare `<` / `>` characters
- Markdown structural characters (`*`, `_`, `#`, backticks) that have no spoken form

Other chat-stream event types (`tool_data`, `tool_output`, `follow_up_actions`, `conversation_id`, `conversation_description`) SHALL NEVER be forwarded to TTS.

#### Scenario: Agent response contains OpenUI markup

- **WHEN** a `response` chunk contains text like `<Section><Label text="Google Calendar">Schedule meetings…</Label></Section>`
- **THEN** the chunk forwarded to TTS contains only the spoken prose with all tag names, attributes, and angle brackets removed; the OpenUI card still renders in the chat UI

#### Scenario: Tool-only turn

- **WHEN** a turn produces only `tool_data` and `tool_output` events with no spoken `response` text before `main_response_complete`
- **THEN** the TTS pipeline emits nothing for that turn

#### Scenario: Boundary marker received mid-stream

- **WHEN** the worker receives `{"main_response_complete": true}`
- **THEN** any text buffered up to that point is flushed to TTS as the final chunk, and all subsequent `response` chunks for the same turn are dropped from TTS

### Requirement: Microphone-device selector in the voice control bar

The voice control bar SHALL render a microphone-device picker dropdown immediately adjacent to the mic mute toggle. The picker SHALL list audio-input devices reported by `navigator.mediaDevices.enumerateDevices()` and SHALL update the active mic track when a different device is selected. The list SHALL refresh in response to `devicechange` events.

#### Scenario: User selects an alternate microphone

- **WHEN** the user opens the device dropdown and selects a different audio-input device
- **THEN** the LiveKit local participant's microphone switches to that device, and the spectrum hook reacts to the new mic stream

#### Scenario: A new device is plugged in mid-call

- **WHEN** a new audio input device is connected during a voice call
- **THEN** the dropdown list refreshes to include the new device without requiring a page reload

#### Scenario: No devices available

- **WHEN** no audio input devices are enumerable (e.g., permission not yet granted)
- **THEN** the dropdown shows a read-only "No devices detected" item and does not crash

### Requirement: No post-disconnect URL refetch

Ending a voice call SHALL NOT push a new route with a `?sync=true` (or equivalent) query parameter to trigger a refetch of the conversation. Voice-turn persistence SHALL happen in-session via the same chat store that text mode reads from, so the UI shows turns live during the call and they remain visible after hang-up without any refetch.

#### Scenario: User ends call

- **WHEN** the user presses the end-call button
- **THEN** the route remains at `/c/<id>` (no query string is appended), the voice control bar is replaced by the text composer, and all turns produced during the call remain rendered in the message list

### Requirement: Known limitation — mid-utterance pause may end the user turn

Voice turn detection MAY occasionally treat a short mid-sentence pause as end-of-turn. This is a documented known limitation driven by the tradeoff between latency and turn-detection accuracy. The system SHALL NOT introduce a fixed minimum-silence threshold long enough to materially degrade response latency.

#### Scenario: User pauses briefly while still speaking

- **WHEN** a user pauses for a fraction of a second mid-utterance
- **THEN** the system may interpret the pause as end-of-turn and begin a new agent response; this is a known limitation and SHALL be observable without crashing the UI
