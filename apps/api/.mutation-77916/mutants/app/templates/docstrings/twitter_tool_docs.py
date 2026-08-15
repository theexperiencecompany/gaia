"""Docstrings for Twitter custom tools."""

CUSTOM_BATCH_FOLLOW_DOC = """
Follow multiple Twitter users at once.

This tool allows you to follow multiple Twitter users in a single operation.
It's more efficient than following users one by one.

Use this tool when the user wants to:
- Follow multiple users at once
- Follow a list of people (e.g., "follow all these tech influencers")
- Follow users by username or user ID

Parameters:
- usernames (list[str], optional): Twitter usernames to follow (without @)
- user_ids (list[str], optional): Twitter user IDs to follow

At least one of usernames or user_ids must be provided.

Returns:
- success: Whether all operations completed
- results: List of individual operation results
- followed_count: Number successfully followed
- failed_count: Number of failures

Example usage:
- "Follow @elonmusk, @sama, and @satyanadella"
- "Follow these users: user1, user2, user3"
"""

CUSTOM_BATCH_UNFOLLOW_DOC = """
Unfollow multiple Twitter users at once.

⚠️ DESTRUCTIVE ACTION: This tool requires explicit user consent before execution.

This tool allows you to unfollow multiple Twitter users in a single operation.
ALWAYS confirm with the user before unfollowing anyone.

Use this tool when the user wants to:
- Unfollow multiple users at once
- Clean up their following list
- Unfollow a specific list of accounts

Parameters:
- usernames (list[str], optional): Twitter usernames to unfollow (without @)
- user_ids (list[str], optional): Twitter user IDs to unfollow

At least one of usernames or user_ids must be provided.

Returns:
- success: Whether all operations completed
- results: List of individual operation results
- unfollowed_count: Number successfully unfollowed
- failed_count: Number of failures

Example usage:
- "Unfollow these accounts: user1, user2, user3"
- "Remove these people from my following list"
"""

CUSTOM_CREATE_THREAD_DOC = """
Create a Twitter thread (multiple connected tweets in sequence).

This tool creates a series of tweets where each one is a reply to the previous,
forming a connected thread. More efficient than multiple individual posts.

Use this tool when the user wants to:
- Post long-form content split into multiple tweets
- Create a tweet storm or tweetorial
- Share a story or explanation across multiple tweets

Parameters:
- tweets (list[str]): List of tweet texts (2-25 tweets). Each tweet max 280 chars.
- media_ids (list[list[str]], optional): Media IDs per tweet (use TWITTER_UPLOAD_MEDIA first)

Returns:
- success: Whether the thread was created
- thread_id: ID of the first tweet (thread root)
- tweet_ids: List of all tweet IDs in order
- thread_url: URL to view the thread

Example usage:
- "Create a thread about the benefits of AI with 5 points"
- "Post this article as a tweetstorm: [long content]"
- "Thread these thoughts: 1. First point... 2. Second point..."
"""

CUSTOM_SEARCH_USERS_DOC = """
Search for Twitter users by name, bio, or keywords.

This tool helps discover Twitter users when you don't know their exact username.
It searches recent tweets to find authors matching the query.

Use this tool when the user wants to:
- Find someone to follow by name (e.g., "find Elon Musk on Twitter")
- Search for people in a specific field (e.g., "find AI researchers")
- Look up someone they know but don't have their handle

Parameters:
- query (str): Search query - name, company, keywords, or partial username
- max_results (int, default=10): Maximum users to return (1-50)

Returns:
- users: List of matching users with profile info
- count: Number of users found

Example usage:
- "Find Elon Musk on Twitter"
- "Search for AI researchers"
- "Who is @dhruv or someone named Dhruv?"
"""

CUSTOM_SCHEDULE_TWEET_DOC = """
Schedule a tweet for later posting.

This tool creates a draft tweet with a scheduled time.
Note: Full scheduling requires a backend scheduler service.

Use this tool when the user wants to:
- Schedule a tweet for a specific time
- Plan posts in advance
- Set up tweets for optimal posting times

Parameters:
- text (str): The tweet text content (max 280 characters)
- scheduled_time (str): ISO 8601 datetime (e.g., '2024-12-25T10:00:00Z')
- media_urls (list[str], optional): Media URLs to attach
- reply_to_tweet_id (str, optional): Tweet ID to reply to

Returns:
- success: Whether the draft was created
- draft: The scheduled tweet draft data
- message: Status message

Example usage:
- "Schedule a tweet for tomorrow at 9am: 'Good morning everyone!'"
- "Post 'Happy holidays!' on December 25th at noon"
"""
