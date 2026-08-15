"""User prompts for image-related functionality."""

IMAGE_TO_TEXT_PROMPT = """Look at this image and answer the user's request about it.

The user's request: '{message}'

Lead with the answer to what they actually asked. Then describe what you see: layout, subjects, colours, and any text or UI elements, transcribing important text exactly. Write plainly, like a person explaining what is in front of them. Vary your sentence length, skip the throat-clearing, and do not overcorrect into forced quirkiness."""


DOCUMENT_IMAGE_SUMMARY_PROMPT = """Provide a concise summary of the content in this image. Assume it is part of a document like a PDF or DOCX, and ensure the summary is relevant for semantic search and accurately describes the image.

Note: Only respond with the summary text, without any additional information or context."""


IMAGE_PROMPT_REFINER = """
You are an AI assistant specialized in refining prompts for generating high-quality images. Your task is to take a simple user prompt and transform it into a detailed, evocative description that will guide AI image generators to create stunning visuals.

**Input Analysis:**
- Identify the core subject, action, and setting from the original prompt
- Determine what artistic style or mood would best enhance the concept
- Consider what technical specifications would produce the best results

**Enhancement Guidelines:**
- Add precise descriptive adjectives for all key elements
- Include specific details about:
  * Subject attributes (appearance, expression, clothing, accessories)
  * Environmental elements (location details, time of day, weather, atmosphere)
  * Lighting conditions (quality, direction, color temperature)
  * Color palette and tonal preferences
  * Composition and framing (camera angle, perspective, focal length)
  * Artistic style references (artists, art movements, media types)
  * Mood and emotional qualities
  * Technical specifications (rendering quality, resolution)

**Output Format:**
- Create a comma-separated list of descriptive keywords and phrases
- Arrange terms from most important to supplementary details
- Prioritize specificity over generality
- Include 15-30 descriptive elements for optimal results
- Avoid contradictory or mutually exclusive descriptors
- Do not include explanations, headings, or formatting

Original user prompt: "{message}"

Enhanced image generation keywords:
"""
