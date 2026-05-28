## MODIFIED Requirements

### Requirement: Frontend receives every backend payload as-is

The voice-agent worker SHALL forward every backend SSE payload to the frontend on `backend-stream-event` immediately on receipt, with one exception: the `response` field of a `response` event SHALL be split into a UI-only fragment and a TTS-spoken fragment.

- The UI-only fragment (whatever the TTS sanitiser would strip — OpenUI fences, directive prefixes, sentinel tokens, HTML tags) SHALL be forwarded immediately to the frontend as a `{"response_ui": "<fragment>"}` event on `backend-stream-event`
- The TTS-spoken fragment (what survives sanitisation) SHALL NOT be forwarded on `backend-stream-event`; the frontend receives this text via LiveKit's TTS-aligned agent transcription channel

All other event keys (`tool_data`, `tool_output`, `follow_up_actions`, `main_response_complete`, `conversation_id`, `conversation_description`, `[DONE]`) SHALL continue to forward as-is, immediately, with no filtering and no waiting on TTS alignment.

#### Scenario: Backend emits a response chunk containing only OpenUI markup

- **WHEN** a `response` event arrives with content that is entirely an OpenUI fenced block (e.g. `':::openui\\nroot = TextDocument("Email", ...)\\n:::'`)
- **THEN** the frontend receives a single `{"response_ui": ":::openui ... :::"}` event on `backend-stream-event` immediately, the OpenUI parser renders the card inside the bot bubble, and nothing is added to the TTS buffer

#### Scenario: Backend emits a response chunk mixing spoken prose and an OpenUI block

- **WHEN** a `response` event arrives with content `'bet, drafting that for u now.\\n\\n:::openui\\nroot = TextDocument("Email Draft", ...)\\n:::'`
- **THEN** the frontend receives `{"response_ui": ":::openui ... :::"}` immediately on `backend-stream-event`, the TTS buffer accumulates `"bet, drafting that for u now."`, and the spoken text reaches the frontend later via the TTS-aligned transcription as ElevenLabs plays the audio

#### Scenario: Backend emits a tool_data event mid-stream

- **WHEN** a `tool_data` event arrives during a turn
- **THEN** the frontend receives it on `backend-stream-event` immediately, with no delay

#### Scenario: Backend emits a response chunk that is entirely spoken text

- **WHEN** a `response` event arrives with content `'hey vinit, what is up?'` (no markup, no fences)
- **THEN** no `response_ui` event is forwarded on `backend-stream-event`, the entire chunk is buffered for TTS, and the frontend receives the text via the TTS-aligned transcription as audio plays

## ADDED Requirements

### Requirement: Spoken bot text fills the bubble in lockstep with TTS audio

The frontend voice-mode hook SHALL receive the agent's spoken text via LiveKit's TTS-aligned transcription channel (`useTranscriptions()` filtered to the agent participant identity) and append each new transcription's text to the active bot turn in `chatStore`. The bot bubble's spoken-text content SHALL fill in synchronisation with the agent's TTS audio playback rather than ahead of it.

#### Scenario: Agent speaks a sentence during a voice turn

- **WHEN** the agent's TTS plays the sentence "here's a draft for u" over ~1.2 seconds of audio
- **THEN** the bot bubble's `response` field accumulates the text "here's a draft for u" across the same ~1.2-second window, character-aligned with what the user hears

#### Scenario: Agent emits an OpenUI card alongside spoken text

- **WHEN** the response chunk contains both prose and an OpenUI block (e.g. "here's a draft:" then a TextDocument)
- **THEN** the OpenUI card appears in the bot bubble immediately (via the `response_ui` event), and the prose "here's a draft:" appears in the bubble's text as the audio plays — the card may visually precede its introductory speech, by design

#### Scenario: User starts a new bot turn before the prior turn's transcription is fully delivered

- **WHEN** `main_response_complete` arrives for turn N and the next backend event opens turn N+1 before all of turn N's TTS-aligned transcriptions have arrived
- **THEN** late-arriving transcription chunks for turn N continue to update the closed turn N's bubble (matched by their transcription stream id), and turn N+1 opens a fresh bubble for new events

### Requirement: Bot transcription deduplication by stream id

The voice-mode hook SHALL track which TTS-aligned transcription stream ids have already been applied to a bot turn and SHALL NOT re-append a transcription chunk that has already been consumed for that turn. Each bot turn SHALL own its own consumed-id set; the set SHALL be reset when the turn opens.

#### Scenario: useTranscriptions emits the same chunk twice across renders

- **WHEN** the transcriptions array re-emits a chunk that has already been applied to the active bot turn
- **THEN** the hook detects the chunk's `streamInfo.id` in the turn's consumed set and skips it; the bubble text does not double up

### Requirement: Worker emits `response_ui` for UI-only response fragments

The voice-agent worker SHALL emit a `{"response_ui": "<fragment>"}` event on `FRONTEND_STREAM_TOPIC` whenever a backend `response` event yields a non-empty UI-only fragment after splitting. The worker SHALL NOT emit `response_ui` for fragments that are empty after splitting. The worker SHALL emit `response_ui` *before* buffering the corresponding TTS-text fragment so the frontend always sees UI updates first.

#### Scenario: Response event yields both UI and spoken fragments

- **WHEN** the worker parses a `response` event whose payload contains both an OpenUI fence and surrounding prose
- **THEN** the worker publishes the OpenUI portion as `{"response_ui": ":::openui ... :::"}` on the frontend topic before appending the prose to the TTS buffer

#### Scenario: Response event yields only spoken fragment

- **WHEN** a `response` event contains only prose with no UI markup
- **THEN** no `response_ui` event is published; the prose is buffered for TTS and reaches the frontend later via the aligned transcription

#### Scenario: Response event yields only UI fragment

- **WHEN** a `response` event contains only an OpenUI fence with no surrounding prose
- **THEN** exactly one `response_ui` event is published with the fence content, nothing is appended to the TTS buffer, and the TTS pipeline emits no audio for that event
