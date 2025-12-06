PERSONALITY_PHRASE_PROMPT = """Analyze this user's profile deeply to create a truly unique, soulful, and distinctive 2-3 word personality phrase that captures their essence.

User Context:
- Profession: {profession} (Use this as a lens, not a constraint)
- Memories/Insights: {memory_summary}

Core Instructions:
1. Look for the underlying themes, values, and motivations in their memories - what drives them?
2. Identify patterns in how they think, create, communicate, or solve problems
3. Consider their energy: Are they a catalyst, observer, builder, connector, explorer, guardian?
4. Notice contradictions or dualities that make them interesting
5. Avoid generic, corporate, or cliché phrases at all costs

What to AVOID:
❌ Corporate buzzwords: "Hard Worker", "Team Player", "Self Starter", "Go-Getter"
❌ Generic descriptors: "Creative Mind", "Tech Savvy", "Problem Solver"
❌ Obvious profession references: "Code Guru", "Data Wizard", "Design Master"
❌ Overused metaphors: "Thought Leader", "Change Maker", "Dream Chaser"

What to AIM FOR:
✓ Poetic and metaphorical: "Midnight Architect", "Storm Whisperer", "Velvet Rebel"
✓ Unexpected combinations: "Neon Philosopher", "Gentle Anarchist", "Lunar Pragmatist"
✓ Evocative imagery: "Ember Keeper", "Atlas Dreamer", "Prism Thinker"
✓ Personality-driven: "Curious Wanderer", "Quiet Thunder", "Fierce Optimist"
✓ Abstract concepts: "Pattern Seeker", "Bridge Builder", "Chaos Navigator"
✓ Sensory/emotional: "Golden Hour Soul", "Silver Tongue", "Diamond Heart"

Generate ONLY the 2-3 word phrase. No explanations, quotes, or additional text."""


USER_BIO_PROMPT = """Write a sassy, insightful 2-3 sentence bio about {name} that makes them think "wow, how does GAIA know me so well?"

Context:
- Profession: {profession}
- Inferred from their digital footprint: {memory_summary}

Style: Sassy best friend who sees through them. Third person. Call out patterns and quirks, not job titles.

DO: Read between the lines. Notice contradictions. Make observations that feel earned.
DON'T: Resume speak. Generic compliments. List obvious facts.

Examples:

❌ "Alex is a passionate software engineer who loves coding and problem-solving."

✅ "Alex writes code like poetry—elegant, intentional, and probably refactored three times. The type to have 47 browser tabs open about some niche framework at 2am, while maintaining a pristine todo list. Chaotic method that somehow always delivers."

❌ "Sarah is a designer who creates beautiful experiences and cares about her craft."

✅ "Sarah notices the 2-pixel misalignment haunting everyone else's dreams. Unreasonable Figma hours, strong kerning opinions, will die on the hill of good UX. The design world doesn't deserve her, but we're grateful anyway."

Generate ONLY the bio. No intro, quotes, or labels."""
