# GAIA Mobile Chat Interface Standards

> These standards define the bar for the most critical screen in the app.
> Every change to the chat interface must be evaluated against this document.
> Inspired by ChatGPT, Claude (Anthropic), and Grok — the best AI chat apps in the world.

---

## 1. Visual Language

### Background
- App background: `#060a14` (near-black, deep navy)
- No cards, no elevated surfaces in the message list — the content is the UI
- Zero chrome: no borders, no box shadows on the message list itself

### Typography
- AI responses: base font size, `#e4e4e7`, line-height 1.6 — readable, generous
- User messages: base font size, `#ffffff`, tight and clean
- Meta text (timestamps, separators): `xs` size, `rgba(255,255,255,0.35)`, muted
- No bold section headers inside the message list

### Color — the accent is a privilege, not a default
- GAIA accent: `#00bbff`
- Use accent ONLY on the active send button and primary CTAs
- Never use accent as background for AI text content

---

## 2. Message Layout

### Core principle: content is the UI
No avatars. No names above messages. No extra chrome.
Reference: Claude app, ChatGPT app — pure content, maximum reading area.

### User messages
- Right-aligned
- Soft dark pill: `backgroundColor: "rgba(28,28,32,0.95)"`, `borderRadius: 20`, no border
- Max width: 80% of screen width
- Padding: `12px vertical, 16px horizontal`
- Font: `#ffffff`, base size
- No user avatar — ever

### AI messages
- Left-aligned, full readable width (no artificial max-width constraint on text)
- No bubble background — text renders directly on app background
- Left padding: `16px` — aligned with the screen edge, breathing room
- Right padding: `16px`
- Font: `#e4e4e7`, base size, line-height 1.6
- Markdown rendering with subtle code block styling

### Spacing between messages
- Between user → AI: `16px`
- Between AI → user: `16px`
- Within a grouped AI message (multi-part): `6px`

### Emoji-only messages
- 1 emoji: `52px` font
- 2 emoji: `40px` font
- 3 emoji: `32px` font
- No bubble for emoji-only user messages

---

## 3. Message Actions (Copy / Thumbs)

### Standard: subtle, out of the way, appear below AI messages only

- Appear below AI message (last part or only part), inline row
- Icon size: `14px` — small, not demanding attention
- Color: `rgba(255,255,255,0.3)` by default, `rgba(255,255,255,0.7)` on press
- Spacing between icons: `20px`
- No background, no border, no container
- Copy: shows checkmark for 2s after copy, turns `#34c759`
- Thumbs up/down: no visual feedback yet (future: selected state)
- No label text next to icons

---

## 4. Composer / Input Bar

### Appearance
- Rounded rectangle container: `borderRadius: 20`, `backgroundColor: "rgba(23,25,32,0.95)"`, subtle `1px` border `rgba(255,255,255,0.08)`
- Padding: `12px` horizontal, `10px` vertical
- Single-line by default, expands to max 5 lines
- Placeholder: `"Ask anything"`, color `#52525b`

### Send button — the iMessage standard
This is the most important micro-interaction in the app.

**Inactive (no text):**
- Small circle, `28–32px`
- Background: `rgba(39,39,42,0.8)` (dark zinc)
- Icon: `ArrowUp02Icon`, color `#52525b`
- Not pressable (disabled)

**Active (text present):**
- Background: `#00bbff` (GAIA accent)
- Icon: `ArrowUp02Icon`, color `#000000` (black arrow on blue)
- Spring-scale animation on press: 0.85 → 1.0

**Streaming (AI responding):**
- Background: `rgba(239,68,68,0.9)` (red/danger)
- Icon: filled white square (stop)
- Pressing cancels the stream

**Transition:** instant color swap, no fade — mimics iMessage precision.

### Keyboard behavior
- Keyboard dismisses WITH animation after sending
- On Android: manual keyboard height tracking (no KAV behavior="height" inside DrawerLayout)
- Keyboard avoidance: smooth LayoutAnimation on show/hide

### Left side buttons
- `+` for attachments: secondary icon button, rounded, `#8e8e93` icon
- Connect drawer trigger: secondary, same styling

---

## 5. Empty State

### Standard: calm, centered, personal
Reference: Claude app — large centered logo, elegant greeting, nothing else.

- Centered vertically and horizontally
- GAIA logo: `72px`, no tint, no container background
- Greeting: `28px`, weight `600`, `#ffffff`, time-sensitive ("Good morning/afternoon/evening/night, [First name]")
- Subtitle: `"Ask me anything..."`, `base` size, `#52525b`
- Nothing else — no chips, no suggestions, no buttons

---

## 6. Date Separators

### Rules
- Show date separator between messages from different calendar days
- **DO NOT show "Today" separator when all messages are from today** — it adds noise with zero value when starting a fresh conversation
- Format: "Yesterday", "Month Day" (e.g. "April 12"), "Today" only when mixed with older dates
- Style: hairline `Separator` on left and right, label centered in `rgba(255,255,255,0.35)`

---

## 7. Streaming / Loading States

### Thinking indicator (no content yet)
- Use `ThinkingCard` with contextual message ("Thinking about X...")
- DO NOT show the default "Thinking..." unless there's no context

### Tool progress (tool running)
- Use `ToolProgressCard` with tool name + progress message
- Visible during the entire tool execution

### Post-stream
- Cancel/stop button disappears immediately when stream ends — no lag
- Transition is instant (state-driven, not animated)

---

## 8. Tool Output Cards

### Standard: visible, full-width, above message text
- Tool cards render at **full screen width** — never inside a max-width text container
- Tool cards appear above the AI's text response, in the order tools were called
- Styling follows the design system card contract: `rounded-2xl`, `bg-zinc-800 p-4`
- Inner data sections: `rounded-2xl bg-zinc-900 p-3`
- No borders on outer card

### Must be visible immediately after streaming completes
- Tool data should be preserved in message state and survive conversation reload

---

## 9. Thinking Bubbles (Chain of Thought)

- Collapsible, starts collapsed
- Subtle styling — secondary role, not primary content
- Shows thinking icon + truncated preview when collapsed
- Expand on tap to see full reasoning

---

## 10. Animations

- Message appearance: `FadeInUp` with `springify()`, 0ms delay
- Keyboard transitions: `LayoutAnimation.easeInEaseOut`
- Send button press: spring scale 0.85 → 1.0, 100ms
- Copy icon swap: fast opacity fade (100ms out, 150ms in)
- Composer height change: smooth, no jumps

---

## 11. Interaction Standards

### Long press
- 350ms delay
- Medium haptic
- Opens action sheet with: Reply, Copy, Pin, Retry (user), Regenerate (AI), Branch, Delete

### Send
- Light haptic on send
- Warning haptic on cancel (stop)
- Keyboard dismisses after send

### Scroll
- Stick to bottom during streaming
- "Scroll to bottom" FAB appears when scrolled up >80px from bottom
- Smooth scroll, no jumps on keyboard

---

## 12. What We DO NOT Do

- No user avatar — ever
- No AI avatar — ever
- No "Today" separator on a fresh conversation
- No bubble background on AI messages
- No inline `style={{}}` on text unless scale-adaptive
- No NativeWind className for button colors (use inline style — NativeWind unreliable on heroui-native buttons)
- No magic strings or hardcoded colors outside this spec
- No loading spinner inside the chat bubble
- No suggestion chips in the empty state

---

## Evaluation Checklist

Before shipping any chat UI change, verify:

- [ ] No avatars visible (user or AI)
- [ ] Send button turns `#00bbff` the moment text is typed
- [ ] Keyboard dismisses smoothly after send
- [ ] "Today" separator hidden on fresh conversations
- [ ] Tool cards render full-width above message text
- [ ] AI messages: no background bubble
- [ ] User messages: right-aligned dark pill
- [ ] Copy/thumbs: small, subtle, below AI message
- [ ] Empty state: logo + greeting only, nothing else
- [ ] Streaming state: ThinkingCard or ToolProgressCard visible
- [ ] Cancel button instant on stream end
- [ ] Long press action sheet works
- [ ] Scroll-to-bottom button appears when scrolled up
