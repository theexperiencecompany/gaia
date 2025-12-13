FETCH_PROMPT = """
Below is web content retrieved for the question from GAIA Webpage Fetch:

SOURCE: {urls}

CONTENT:
{page_content}

Please analyze this information and provide a detailed response addressing the user's question. Your response should:

1. Extract relevant facts and details from the content
2. Organize information in a helpful, structured format
3. Provide specific details from the webpage (including numbers, names, and specifications when available)
4. Reference the source website when citing specific information
5. Indicate clearly if the information is incomplete or insufficient to fully answer the question

If the retrieved content doesn't contain enough information, suggest what additional data might be needed.
\n\nUSE THE ABOVE INFORMATION TO PROVIDE A COMPREHENSIVE, DETAILED RESPONSE. DO NOT JUST ACKNOWLEDGE RECEIPT OF THIS DATA.
"""
