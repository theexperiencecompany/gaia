## ADDED Requirements

### Requirement: Voice-agent Infisical fetch happens once per worker host process

The voice-agent worker SHALL contact Infisical exactly once per host process lifetime, from the main process at `start_worker()` (and `download_files()`) startup. LiveKit JobProcess children (forkserver descendants) SHALL inherit the resulting environment variables from the parent and SHALL NOT contact Infisical again from `prewarm()` or any other room-lifecycle hook.

#### Scenario: Worker starts and spawns the initial idle JobProcess pool

- **WHEN** `start_worker()` runs in the main process and forks N idle JobProcesses
- **THEN** Infisical is contacted exactly once (in the main process); each child's `prewarm()` reads its settings from the inherited environment without any `Connecting to Infisical...` log entry

#### Scenario: A new JobProcess is spawned later because the idle pool is exhausted

- **WHEN** the worker spawns a new JobProcess after the initial pool is consumed and a new room is being assigned
- **THEN** the child's `prewarm()` builds settings from the inherited environment without contacting Infisical

### Requirement: TTS receives only spoken text, never UI directives or fenced OpenUI blocks

The voice-agent worker SHALL filter backend SSE events before adding any text to the TTS buffer. Events whose primary field is `tool_data`, `tool_output`, `follow_up_actions`, `main_response_complete`, `conversation_id`, or `conversation_description` SHALL NOT contribute to the TTS buffer. Only `response` payloads SHALL be considered candidate TTS text.

`sanitize_for_tts` SHALL strip `:::openui ... :::` fenced blocks (including unterminated trailing fences in streaming-tail cases) and `:::<directive>` prefixes in addition to existing HTML tag, sentinel token, markdown, and whitespace normalisation.

#### Scenario: Backend emits an OpenUI block inside a response chunk

- **WHEN** a `response` event arrives with content `'bet, drafting that for u now.\\n\\n:::openui\\nroot = TextDocument("Email Draft", ...'`
- **THEN** the TTS buffer receives `"bet, drafting that for u now."` and the OpenUI block is dropped before reaching ElevenLabs

#### Scenario: Backend emits a tool_data event with renderable text content

- **WHEN** an event arrives with shape `{"tool_data": {"tool_name": "calendar_list", "data": {...}}}`
- **THEN** no part of that event is added to the TTS buffer regardless of regex sanitisation

#### Scenario: Backend emits an OpenUI fence that spans multiple SSE chunks

- **WHEN** chunk N contains `':::openui\\nroot = '` and chunk N+1 contains `'TextDocument("title", ...):::'`
- **THEN** the worker defers TTS flush while the open fence is unterminated, then sanitises the combined content so no OpenUI text reaches ElevenLabs

### Requirement: Frontend receives every backend payload as-is

The voice-agent worker SHALL forward every backend SSE payload to the frontend on `backend-stream-event` immediately on receipt, with no filtering and no waiting on TTS alignment. This includes `response` payloads carrying OpenUI fenced blocks, `tool_data`, `follow_up_actions`, `main_response_complete`, and `[DONE]`. The frontend is the canonical renderer of all backend content; TTS sanitisation is a separate, worker-side concern that does not affect the frontend stream.

#### Scenario: Backend emits a response chunk containing an OpenUI block

- **WHEN** a `response` event arrives with content containing `:::openui ... :::` markup
- **THEN** the frontend receives the chunk on `backend-stream-event` unchanged, parses the OpenUI block into a tool card, and renders it inside the bot bubble

#### Scenario: Backend emits a tool_data event mid-stream

- **WHEN** a `tool_data` event arrives during a turn
- **THEN** the frontend receives it on `backend-stream-event` immediately, with no delay

### Requirement: Voice mode survives the first conversation-id discovery

When a fresh `/c` voice session receives its first `conversation_id` from the worker, the URL SHALL update to `/c/:id` without triggering a Next.js navigation. The React tree, the LiveKit `Room`, and the voice session SHALL remain mounted across the URL change so the first user transcription, first bot response, and first TTS playback are preserved.

#### Scenario: User starts a voice call from /c with no existing conversation

- **WHEN** the user activates voice mode on `/c`, speaks "draft a todo", and the worker discovers a new conversation id from the backend
- **THEN** the URL updates to `/c/:id` in place via `window.history.replaceState`, the chat bubble for the first user transcription stays visible, the first bot response continues filling in, and TTS playback is not interrupted

#### Scenario: User starts a voice call from /c/:id (existing conversation)

- **WHEN** the user activates voice mode on an existing conversation page
- **THEN** no URL update is required and the session proceeds with no change to history state

### Requirement: User transcriptions survive preemptive bot turns

The frontend voice-mode hook `useVoiceMessages` SHALL render every STT-final user transcription as a chat bubble, even when an active bot turn is in flight at the time the transcription finalises. The new user bubble's `createdAt` SHALL be set so it sorts after the currently active bot turn but before any subsequent bot turn that responds to it.

#### Scenario: User speaks while the bot is mid-response

- **WHEN** the bot is still speaking its response to utterance A and the user finishes utterance B
- **THEN** the chat surface shows `[user A] [bot for A] [user B]` and, once the bot responds to B, `[user A] [bot for A] [user B] [bot for B]`, with no transcription silently dropped

#### Scenario: User pauses mid-thought between two transcription chunks of the same utterance

- **WHEN** two STT-final transcriptions arrive sequentially with no bot turn between them
- **THEN** they are still grouped into a single user bubble joined by `NEW_MESSAGE_BREAK` (existing behaviour preserved)

### Requirement: Voice spectrum stops processing when muted or hidden

The `useVoiceSpectrum` hook SHALL cancel its `requestAnimationFrame` loop when both of the following are true: the source is `"mic"` AND the microphone is muted. The hook SHALL also cancel the loop when `document.hidden` is true regardless of source. The loop SHALL restart on unmute or visibility return. The agent-track analyser pipeline SHALL be unaffected by mute, because the mute state applies to the local microphone only.

#### Scenario: User mutes the microphone during a voice call

- **WHEN** the user presses the mute button while in mic-source mode
- **THEN** the spectrum raf loop is cancelled within one frame, the gradient settles to its last frame, and no `getByteFrequencyData` calls or render work occur until unmute

#### Scenario: User switches to another browser tab during a voice call

- **WHEN** the document becomes hidden while a voice call is active
- **THEN** the spectrum raf loop is cancelled until the document is visible again

### Requirement: Structured logger never crashes on token content containing braces

Log calls in `apps/voice-agent/src/llm.py` and `apps/voice-agent/src/agent.py` SHALL NOT include arbitrary backend or user-supplied content directly inside f-string message templates that Loguru parses for `{name}` placeholders. Such content SHALL be passed as logger keyword arguments only, or have its braces escaped to `{{` and `}}` before interpolation.

#### Scenario: Backend token contains a JSON dictionary string

- **WHEN** a backend `response` token arrives with content `' "<p>Hi,</p><p>I have been experiencing... {"label": "foo"} ...</p>"'`
- **THEN** the worker's debug logger records the token without raising `KeyError: '"label"'` and the stream proceeds to TTS as normal
