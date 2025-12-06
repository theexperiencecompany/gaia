PERSONALITY_PHRASE_PROMPT = """Analyze this user's profile deeply to create a truly unique, soulful, and distinctive 2-3 word personality phrase.

User Context:
- Profession: {profession} (Use this as a lens, not a constraint)
- Memories/Insights: {memory_summary}

Instructions:
1. Look for the underlying themes, values, and motivations in their memories.
2. Avoid generic, corporate, or cliché phrases (e.g., avoid "Hard Worker", "Team Player").
3. Aim for a poetic, metaphorical, or highly specific description that captures their essence.
4. Combine abstract concepts with concrete traits if possible.

Examples of the VIBE (do not copy): "Digital Alchemist", "Quiet Storm", "Code Poet", "Restless Voyager", "Mindful Architect".

Generate ONLY the 2-3 word phrase. No explanations."""


USER_BIO_PROMPT = """Write a brief, engaging bio paragraph (2-3 sentences) about {name}.

Profession: {profession}
What we know: {memory_summary}

Make it personal and interesting, like an 'About Me' section.
Respond with ONLY the paragraph, no introduction or formatting."""
