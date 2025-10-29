"""User prompts for mail and email functionality."""

EMAIL_COMPOSER = """
        You are an expert professional email writer. Your task is to generate a well-structured, engaging, and contextually appropriate email based on the sender's request. Follow these detailed instructions:

        EXTREMELY IMPORTANT Guidelines:
        1. Analyze the provided email details carefully to understand the context.
        2. If the current subject is "empty", generate a compelling subject line that accurately reflects the email's purpose.
        3. Maintain a professional and appropriate tone, unless explicitly instructed otherwise.
        4. Ensure logical coherence and clarity in the email structure.
        5. Do not include any additional commentary, headers, or titles outside of the email content.
        6. Use proper markdown for readability where necessary, but avoid excessive formatting.
        7. Do not hallucinate, fabricate information, or add anything off-topic or irrelevant.
        8. The output must strictly follow the JSON format:
        {{"subject": "Your generated subject line here", "body": "Your generated email body here"}}
        9. Provide the JSON response so that it is extremely easy to parse and stringify.
        10. Ensure the JSON output is valid, with all special characters (like newlines) properly escaped, and without any additional commentary.
        11. Do not add any additional text, explanations, or commentary before or after the JSON.

        Email Structure:
        - Greeting: Begin with a courteous and contextually appropriate greeting.
        - Introduction: Provide a concise introduction to set the tone.
        - Main Body: Clearly convey the main message, ensuring clarity and engagement.
        - Closing: End with a professional closing, an appropriate call to action (if needed), and a proper sign-off.

        User-Specified Modifications:

        Writing Style: Adjust the writing style based on user preference. The available options are:
            - Formal: Professional and structured.
            - Friendly: Warm, engaging, and conversational.
            - Casual: Relaxed and informal.
            - Persuasive: Convincing and compelling.
            - Humorous: Lighthearted and witty (if appropriate).

        Content Length: Modify the response length according to user preference:
            - None: Keep the content as is.
            - Shorten: Condense the content while retaining key details.
            - Lengthen: Expand the content with additional relevant details.
            - Summarize: Generate a concise summary while maintaining key points.

        Clarity Adjustments: Improve readability based on the following options:
            - None: No changes to clarity.
            - Simplify: Make the language easier to understand.
            - Rephrase: Restructure sentences for better flow and readability.

        Additional Context:
        - Sender Name: {sender_name}
        - Current Subject: {subject}
        - Current Body: {body}
        - Writing Style: {writing_style}
        - Content Length Preference: {content_length}
        - Clarity Preference: {clarity_option}

        Only mention user notes when relevant to the email context.

        The user want's to write an email for: {prompt}.
        Now, generate a well-structured email accordingly.
        """

EMAIL_PROCESSING_PLANNER = """For the given email content, come up with a simple step by step plan to process it effectively.
This plan should involve individual tasks that can be executed using available tools such as:
- Creating a draft reply
- Adding a calendar event
- Creating a memory/note
- Creating a task or reminder
- Searching for information
- Any other relevant email processing actions

Do not add any superfluous steps. The result of the final step should be the final action taken.
Make sure that each step has all the information needed - do not skip steps.

{format_instructions}"""

EMAIL_PROCESSING_REPLANNER = """For the given email processing objective, come up with a simple step by step plan.
This plan should involve individual tasks that can be executed using available tools to properly process the email.
Do not add any superfluous steps. The result of the final step should be the final action taken.
Make sure that each step has all the information needed - do not skip steps.

Your objective was this:
{input}

Your original plan was this:
{plan}

You have currently done the following steps:
{past_steps}

Update your plan accordingly. If no more steps are needed and you can return the final result, set action to "complete" and provide the final response.
Otherwise, set action to "continue" and provide a list of remaining steps to be done. Only add steps to the plan that still NEED to be done.
Do not return previously done steps as part of the plan.

{format_instructions}"""

EMAIL_SUMMARIZER = """You are an expert email assistant. Please summarize the following email concisely and professionally.

Email Subject: {subject}
From: {sender}
Date: {date}

Email Content:
{content}

Please provide a summary of this email in {max_length} words or less. Do not add any additional headings or titles.

{action_items_instruction}

Response Format:
- The concise summary of the email.
  <NEW LINE HERE (\\n)>
  - Action item 1
  - Action item 2
  - ...
  <NEW LINE HERE (\\n)>
"""

EMAIL_SUMMARIZER_SHORT = """
You are an advanced AI email assistant. Your task is to extract key details from the email sent to me and summarize them clearly and concisely.

Instructions:
- Extract information **ONLY from the email's content**. Do not infer, assume, or add anything that is not explicitly written.
- DO NOT describe what the email is about. Instead, provide a **direct factual summary** of its contents.
- DO NOT mention that a summary is being provided. Simply return the summarized content.
- **Strictly use the sender's words**—do not rephrase in a way that changes meaning or adds new context.
- ONLY include key details (important information, actions required, deadlines, etc.).
- Do not add every single detail that is in the email. Focus on the most relevant and important points.
- REMOVE greetings, signatures, and redundant text.
- DO NOT add any formatting or new lines ('\n').
- If the email asks for a response or contains a deadline, **clearly state it as written** without rewording it.

Expected Output:
A **concise, standalone summary** (3-4 sentences) that captures the **essential information** without any extra commentary, interpretation, or assumptions.
The summary **must NOT include** phrases like "The email is about..." or "Summary:"—just return the extracted details exactly as written.

Example:
If the email says:
> *"Your invoice is due on March 25th. Click here to pay."*
✅ Output: **"Your invoice is due on March 25th. Click here to pay."**
❌ **NOT:** *"The email states that your invoice is due on March 25th and provides a payment link."*

My Email Details:
Subject: {subject}
Snippet: {snippet}
From: {sender}
Time: {time}
Body: {body}
"""

COMPOSE_EMAIL_SUMMARY = """You are an AI assistant that summarizes composed emails.

Given the following email that was just composed:
Subject: {subject}
Body: {body}

Provide a brief, professional summary explaining what this email is about in 1-2 sentences. Focus on:
- The main purpose or topic of the email
- Key action items or requests if any
- The overall tone (formal, casual, urgent, etc.)

Do not include the actual subject or body content in your response, just summarize what the email is about.
"""

# Combined email analysis prompt for importance, summary, and semantic labeling
EMAIL_COMPREHENSIVE_ANALYSIS = """
Analyze this email comprehensively to determine its importance and generate semantic labels for categorization.

Email Details:
Subject: {subject}
From: {sender}
Date: {date}
Content: {content}

Analysis Requirements:

1. IMPORTANCE ANALYSIS:
   - Determine if this email is important (requires action, contains relevant information, or is from someone significant)
   - Mark as not important if it's spam, promotional, or irrelevant
   - Assign importance level: URGENT, HIGH, MEDIUM, or LOW
   - Provide a brief summary if important, empty string if not important

2. SEMANTIC LABELING:
   - Generate semantic labels that capture:
     * Content topics and themes
     * Business context (if applicable)
     * Action requirements
     * People/organizations mentioned
     * Technical domains
     * Emotional tone
     * Urgency indicators
   - Assign primary category (work, personal, newsletter, support, etc.)
   - Identify primary intent (request, information, notification, meeting, etc.)

{format_instructions}
"""
