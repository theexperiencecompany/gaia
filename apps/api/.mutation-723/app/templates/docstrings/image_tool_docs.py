"""Docstrings for image generation tools."""

GENERATE_IMAGE = """
Generate an image based on an enhanced text prompt and return its URL.

Parameters:
    prompt: YOUR ENHANCED VERSION of the user's image request. You should expand the original request
           with details about artistic style, lighting, composition, colors, mood, perspective,
           and specific visual elements. Make it comprehensive (50-100+ words) for best results.

IMPORTANT: After calling this tool, the image will be automatically displayed to the user.
DO NOT include markdown image syntax like ![alt](url) or attachment:// references in your response.
Simply describe what you generated in natural language.

Prompt Enhancement Guidelines:
    1. Start with the user's core concept
    2. Add specific visual details about what should appear in the image
    3. Specify an artistic style (e.g., photorealistic, oil painting, digital art)
    4. Include lighting information (e.g., golden hour, studio lighting, moonlight)
    5. Add mood and atmosphere descriptors (e.g., serene, dramatic, whimsical)
    6. Mention perspective, composition and framing details
    7. Include technical aspects (e.g., 4K, high resolution, detailed)
    8. Avoid restricted content (real people, offensive imagery, etc.)

Example Process:
    1. User request: "Create an image of a mountain landscape"
    2. Your enhanced prompt (what you pass to this tool):
       "A breathtaking mountain landscape at golden hour, with snow-capped peaks reflecting the warm orange
       and pink hues of sunset. Dense pine forests cover the lower slopes, with a crystal-clear alpine lake
       in the foreground that perfectly mirrors the mountains. A small wooden cabin sits by the lakeside with
       smoke curling from its chimney. Dramatic clouds partially shroud the highest peaks. Photorealistic
       style with dramatic lighting, sharp details, and rich colors. Ultra high-definition 4K quality with
       stunning depth of field."
"""
