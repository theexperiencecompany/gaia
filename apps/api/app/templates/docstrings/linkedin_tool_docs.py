"""Docstrings for LinkedIn custom tools."""

CUSTOM_CREATE_IMAGE_POST_DOC = """
Create a LinkedIn post with an image from a URL.

Use this tool when the user wants to:
- Share an image on LinkedIn with commentary
- Post visual content to their professional network
- Create an engaging image-based post

Parameters:
- commentary (str): The text content of the post (max 3000 chars). Supports mentions and hashtags.
- image_url (str): URL of the image to include (must be publicly accessible)
- image_title (str, optional): Title for the image
- image_description (str, optional): Description for the image
- visibility (str): 'PUBLIC' for everyone or 'CONNECTIONS' for 1st degree only
- organization_id (str, optional): Organization URN to post on behalf of

Returns:
- success: Whether the post was created
- post_id: URN of the created post
- url: Direct link to the post on LinkedIn

Example usage:
- "Post this image with a caption about our team offsite"
- "Share the product screenshot on LinkedIn"
- "Create a LinkedIn post with the infographic from this URL"
"""

CUSTOM_CREATE_ARTICLE_POST_DOC = """
Create a LinkedIn post sharing an article/link with optional custom preview.

Use this tool when the user wants to:
- Share a blog post, news article, or webpage on LinkedIn
- Share content with custom title/description/thumbnail
- Promote external content to their network

Parameters:
- commentary (str): The text content accompanying the shared article
- article_url (str): URL of the article to share
- article_title (str, optional): Custom title for the article preview
- article_description (str, optional): Custom description for the preview
- thumbnail_url (str, optional): Custom thumbnail image URL
- visibility (str): 'PUBLIC' or 'CONNECTIONS'
- organization_id (str, optional): Organization URN to post on behalf of

Returns:
- success: Whether the post was created
- post_id: URN of the created post
- url: Direct link to the post on LinkedIn

Example usage:
- "Share our latest blog post on LinkedIn"
- "Post this article with a custom description"
- "Share the news article about AI trends"
"""

CUSTOM_CREATE_DOCUMENT_POST_DOC = """
Create a LinkedIn post with an attached document (PDF, slides, etc.).

Use this tool when the user wants to:
- Share a PDF, presentation, or document on LinkedIn
- Post thought leadership content in document format
- Share slideshows, whitepapers, or reports

Parameters:
- commentary (str): The text content of the post
- document_url (str): URL of the document (PDF, PPT, etc.)
- document_title (str): Title for the document
- visibility (str): 'PUBLIC' or 'CONNECTIONS'
- organization_id (str, optional): Organization URN to post on behalf of

Returns:
- success: Whether the post was created
- post_id: URN of the created post
- url: Direct link to the post

Example usage:
- "Post the quarterly report PDF on LinkedIn"
- "Share my presentation slides with the network"
- "Upload the whitepaper as a LinkedIn document post"
"""

CUSTOM_ADD_COMMENT_DOC = """
Add a comment to a LinkedIn post (share or ugcPost).

Use this tool when the user wants to:
- Comment on someone's LinkedIn post
- Reply to a comment on a post
- Engage with content in their network

Parameters:
- post_urn (str): URN of the post to comment on (e.g., 'urn:li:share:12345')
- comment_text (str): The text content of the comment (max 1250 chars)
- parent_comment_urn (str, optional): For nested replies, the parent comment URN

Returns:
- success: Whether the comment was added
- comment_id: URN of the created comment
- post_urn: URN of the post commented on

Example usage:
- "Comment 'Great insights!' on that post"
- "Reply to the comment saying congratulations"
- "Add my thoughts to the discussion"
"""

CUSTOM_GET_POST_COMMENTS_DOC = """
Retrieve comments on a LinkedIn post.

Use this tool when the user wants to:
- See what people are saying about a post
- Read the discussion on a LinkedIn share
- Monitor engagement on their content

Parameters:
- post_urn (str): URN of the post to get comments from
- count (int): Number of comments to retrieve (default: 10, max: 100)
- start (int): Starting index for pagination (default: 0)

Returns:
- success: Whether comments were retrieved
- comments: List of comments with author, text, and timestamps
- total_count: Total number of comments on the post
- post_urn: URN of the post

Example usage:
- "Show me the comments on my latest post"
- "What are people saying about this article?"
- "Get the discussion on that announcement"
"""

CUSTOM_REACT_TO_POST_DOC = """
Add a reaction to a LinkedIn post.

Use this tool when the user wants to:
- Like a post on LinkedIn
- React with celebrate, support, love, insightful, or funny
- Engage with someone's content

Parameters:
- post_urn (str): URN of the post to react to
- reaction_type (str): Type of reaction:
  - 'LIKE': Standard like
  - 'CELEBRATE': Celebration/clapping
  - 'SUPPORT': Heart/support
  - 'LOVE': Love reaction
  - 'INSIGHTFUL': Lightbulb/insight
  - 'FUNNY': Laughing reaction

Returns:
- success: Whether the reaction was added
- post_urn: URN of the reacted post
- reaction_type: Type of reaction added

Example usage:
- "Like that post about the product launch"
- "React with celebrate to the promotion announcement"
- "Add an insightful reaction to the industry analysis"
"""

CUSTOM_DELETE_REACTION_DOC = """
Remove your reaction from a LinkedIn post.

Use this tool when the user wants to:
- Unlike a post
- Remove their reaction from content
- Undo a previous reaction

Parameters:
- post_urn (str): URN of the post to remove reaction from

Returns:
- success: Whether the reaction was removed
- post_urn: URN of the post

REQUIRES USER CONSENT - This is a destructive action.
"""

CUSTOM_GET_POST_REACTIONS_DOC = """
Retrieve reactions on a LinkedIn post.

Use this tool when the user wants to:
- See who reacted to a post
- Get reaction counts and types
- Analyze engagement on content

Parameters:
- post_urn (str): URN of the post to get reactions from
- count (int): Number of reactions to retrieve (default: 10, max: 100)

Returns:
- success: Whether reactions were retrieved
- reactions: List of reactions with reactor info and type
- total_count: Total number of reactions
- post_urn: URN of the post
"""
