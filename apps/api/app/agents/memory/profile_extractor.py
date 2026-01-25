"""LLM-based profile username extraction from platform emails using structured output.

Flow:
1. Filter emails sent FROM trusted platforms (GitHub, LinkedIn, Twitter, etc.)
2. For each platform, send last 10 emails to LLM with extraction prompt
3. LLM returns username + confidence score using structured output
4. Validate username against platform-specific regex patterns
5. Build canonical profile URLs (e.g., https://x.com/username)
6. Return validated profile URLs ready for crawling
"""

import json
import os
import re
import time
from difflib import SequenceMatcher
from typing import Dict, List

import ftfy
from app.agents.llm.client import init_llm
from app.config.loggers import memory_logger as logger
from app.config.settings import settings
from app.constants.general import (
    DEDUPLICATION_SIMILARITY_THRESHOLD,
    MAX_EMAILS_PER_PLATFORM,
    PROFILE_EXTRACTION_LLM_MODEL,
    PROFILE_EXTRACTION_LLM_PROVIDER,
)
from bs4 import BeautifulSoup  # For HTML cleaning
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

PLATFORM_CONFIG = {
    "twitter": {
        "sender_domains": [
            "twitter.com",
            "x.com",
            "info.twitter.com",
            "notify.twitter.com",
        ],
        "url_template": "https://x.com/{username}",
        "regex_pattern": r"^[a-zA-Z0-9_]{1,15}$",
    },
    "github": {
        "sender_domains": ["github.com", "notifications.github.com"],
        "url_template": "https://github.com/{username}",
        "regex_pattern": r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$",
    },
    "linkedin": {
        "sender_domains": [
            "linkedin.com",
            "e.linkedin.com",
            "messages-noreply.linkedin.com",
        ],
        "url_template": "https://linkedin.com/in/{username}",
        "regex_pattern": r"^[\w-]{3,100}$",
    },
    "reddit": {
        "sender_domains": ["reddit.com", "noreply.reddit.com"],
        "url_template": "https://reddit.com/user/{username}",
        "regex_pattern": r"^[a-zA-Z0-9_-]{3,20}$",
    },
    "medium": {
        "sender_domains": ["medium.com", "mg.medium.com"],
        "url_template": "https://medium.com/@{username}",
        "regex_pattern": r"^[a-zA-Z0-9_-]{3,50}$",
    },
    "instagram": {
        "sender_domains": ["instagram.com", "ig.me", "mail.instagram.com"],
        "url_template": "https://instagram.com/{username}",
        "regex_pattern": r"^[a-zA-Z0-9._]{1,30}$",
    },
    "tiktok": {
        "sender_domains": ["tiktok.com"],
        "url_template": "https://tiktok.com/@{username}",
        "regex_pattern": r"^[a-zA-Z0-9._]{2,24}$",
    },
    "youtube": {
        "sender_domains": ["youtube.com", "youtubecreators.com"],
        "url_template": "https://youtube.com/@{username}",
        "regex_pattern": r"^[a-zA-Z0-9_.-]{3,30}$",
    },
    "dribbble": {
        "sender_domains": ["dribbble.com"],
        "url_template": "https://dribbble.com/{username}",
        "regex_pattern": r"^[a-zA-Z0-9_-]{1,30}$",
    },
    "behance": {
        "sender_domains": ["behance.net", "mail.behance.net"],
        "url_template": "https://behance.net/{username}",
        "regex_pattern": r"^[a-zA-Z0-9_-]{1,30}$",
    },
    "devto": {
        "sender_domains": ["dev.to", "forem.com"],
        "url_template": "https://dev.to/{username}",
        "regex_pattern": r"^[a-zA-Z0-9_]{1,30}$",
    },
    "hashnode": {
        "sender_domains": ["hashnode.com"],
        "url_template": "https://hashnode.com/@{username}",
        "regex_pattern": r"^[a-zA-Z0-9_-]{1,39}$",
    },
    "substack": {
        "sender_domains": ["substack.com"],
        "url_template": "https://{username}.substack.com",
        "regex_pattern": r"^[a-zA-Z0-9-]{1,63}$",
    },
    "twitch": {
        "sender_domains": ["twitch.tv"],
        "url_template": "https://twitch.tv/{username}",
        "regex_pattern": r"^[a-zA-Z0-9_]{4,25}$",
    },
    "facebook": {
        "sender_domains": ["facebookmail.com", "fb.com"],
        "url_template": "https://facebook.com/{username}",
        "regex_pattern": r"^[a-zA-Z0-9.]{5,50}$",
    },
    "quora": {
        "sender_domains": ["quora.com"],
        "url_template": "https://quora.com/profile/{username}",
        "regex_pattern": r"^[\w-]{1,50}$",
    },
}


# Structured output model
class UsernameExtraction(BaseModel):
    """Structured output for username extraction."""

    username: str = Field(
        description="The extracted username/handle without @ or / symbols. Return 'NOT_FOUND' if not found."
    )
    confidence: str = Field(
        description="Confidence level: 'high' if explicitly stated, 'medium' if inferred from context, 'low' if uncertain"
    )


# Prompt template string
EXTRACTION_PROMPT = """You are extracting the EMAIL RECIPIENT'S username/handle on {platform} from notification emails they RECEIVED.

USER CONTEXT:
{user_context}

CRITICAL RULE: The username MUST be written EXACTLY in the email. DO NOT create, construct, guess, or infer usernames.

CONTEXT: These emails were SENT TO the user. You need to find the RECIPIENT's username that is explicitly written in the email text.

ABSOLUTELY FORBIDDEN:
- DO NOT convert the user's name into a username (e.g., "John Doe" → "john-doe" is WRONG)
- DO NOT extract full names as usernames (e.g., "Dhruv Maradiya" is a NAME, not a username)
- DO NOT create usernames from email addresses (e.g., "john@example.com" → "john" is WRONG unless explicitly shown)
- DO NOT guess usernames based on context
- DO NOT extract newsletter author names (they're senders, not the recipient)
- DO NOT extract sender usernames or handles
- DO NOT make up ANY username that isn't explicitly written

PLATFORM-SPECIFIC GUIDANCE:
- YouTube: Look for handles like "@username" or "youtube.com/@username" (NOT full names like "John Doe")
- Discord: Look for usernames like "username" or "@username" (modern Discord usernames are alphanumeric, 2-32 chars)
- GitHub: Look for @mentions in PR descriptions, commit messages, or URLs like "github.com/username" (NOT "github.com/org/repo")
- Twitter/X: Look for @handles (e.g., "@jack", not "Jack Dorsey")
- LinkedIn: Look for profile URLs like "linkedin.com/in/username"

FOR GITHUB SPECIFICALLY:
- @mentions in PR bodies like "by @username" or "@username made their first contribution"
- Author in commit messages: "@username pushed"
- URLs like "github.com/username" (single path segment after domain)
- IGNORE: Organization/repo paths like "github.com/org/repo" or "github.com/org/repo/pull/123"

ONLY extract if you see EXACT TEXT like:
- "Your username: @username" or "Welcome back, @username"
- "You are signed in as @username"
- "Your {platform} handle is @username"
- A URL that says "your profile" or "view your profile": {platform}.com/@username
- Email footer: "You're receiving this because you're @username"
- Account settings showing: "Username: username"
- Channel/profile links: "youtube.com/@channelname"

The username must be LITERALLY WRITTEN in the email. If you have to guess, infer, or construct it → return "NOT_FOUND"

EXTRACTION RULES:
1. The username MUST appear as text in the email (not just implied)
2. Copy it EXACTLY as shown (preserve case, hyphens, underscores, periods, numbers)
3. Remove only @ or / prefix symbols if present
4. If unsure in ANY way → return "NOT_FOUND"
5. If you only see a full name (with spaces), return "NOT_FOUND" unless it's in a URL or clearly marked as username

EXAMPLES OF VALID EXTRACTION:
Email: "Welcome back, @johndoe123!"
Extract: "johndoe123" ✓

Email: "Your channel: youtube.com/@john.doe"
Extract: "john.doe" ✓

Email: "You're signed in as @john_doe"
Extract: "john_doe" ✓

Email: "Your Discord username: dhruvmaradiya"
Extract: "dhruvmaradiya" ✓

Email: "* fix: pricing page issues by @Dhruv-Maradiya in https://github.com/..."
Extract: "Dhruv-Maradiya" ✓ (GitHub @mention in PR description)

Email: "@aryanranderiya pushed 1 commit."
Extract: "aryanranderiya" ✓ (GitHub @mention for commit author)

Email: "View it on GitHub: https://github.com/octocat"
Extract: "octocat" ✓ (profile URL with single path segment)

EXAMPLES OF INVALID EXTRACTION (return "NOT_FOUND"):
Email: "Hi John Doe, thanks for subscribing!"
Extract: "NOT_FOUND" (full name with space, not a username)

Email: "Dhruv Maradiya uploaded a video"
Extract: "NOT_FOUND" (this is a channel NAME displayed, not the @handle)

Email: "Newsletter from John's Blog"
Extract: "NOT_FOUND" (John is the sender, not recipient's username)

Email: "Your email is john@example.com"
Extract: "NOT_FOUND" (email address, not username)

Email: "https://github.com/facebook/react"
Extract: "NOT_FOUND" (this is org/repo path, not a user profile)

Email: "https://github.com/microsoft/vscode/pull/123"
Extract: "NOT_FOUND" (PR URL, not a profile)

{format_instructions}

Platform: {platform}

Here are recent emails RECEIVED by the user from {platform}:

{emails_text}

Extract the RECIPIENT's username/handle ONLY if explicitly written (not inferred):"""


def filter_emails_by_platform(emails: List[Dict], platform: str) -> List[Dict]:
    """
    Filter emails sent from a specific platform.

    Args:
        emails: List of all emails
        platform: Platform name (e.g., 'twitter', 'github')

    Returns:
        List of emails from that platform (max MAX_EMAILS_PER_PLATFORM most recent)
    """
    if platform not in PLATFORM_CONFIG:
        return []

    platform_domains = PLATFORM_CONFIG[platform]["sender_domains"]
    filtered = []

    for email in emails:
        sender = (email.get("sender", "") or email.get("from", "")).lower()

        if "@" in sender:
            domain = sender.split("@")[-1].rstrip(">").strip()
            if any(domain.endswith(pd) for pd in platform_domains):
                filtered.append(email)

    return filtered[:MAX_EMAILS_PER_PLATFORM]


def validate_username(username: str, platform: str) -> bool:
    """
    Validate extracted username against platform regex pattern.

    Args:
        username: Extracted username
        platform: Platform name

    Returns:
        True if username matches the expected pattern
    """
    if not username or username == "NOT_FOUND":
        return False

    if platform not in PLATFORM_CONFIG:
        return False

    pattern: str = PLATFORM_CONFIG[platform]["regex_pattern"]  # type: ignore
    return bool(re.match(pattern, username.strip()))


def build_profile_url(username: str, platform: str) -> str:
    """
    Build full profile URL from username and platform.

    Args:
        username: Validated username
        platform: Platform name

    Returns:
        Full profile URL
    """
    if platform not in PLATFORM_CONFIG:
        return ""

    template: str = PLATFORM_CONFIG[platform]["url_template"]  # type: ignore
    return template.format(username=username)


def _filter_garbage_content(text: str) -> str:
    """
    Remove garbage content from email text using proper libraries.

    Uses:
    - BeautifulSoup for HTML cleaning
    - ftfy for fixing text encoding
    - Regex for specific patterns (file paths, base64, etc.)

    Args:
        text: Raw email text

    Returns:
        Cleaned text with garbage removed
    """
    # Fix text encoding issues (mojibake, unicode errors, etc.)
    text = ftfy.fix_text(text)

    # Remove HTML tags using BeautifulSoup (much better than regex)
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ")

    # Remove excessive repetitive special characters (e.g., -----, ====, *****)
    text = re.sub(r"([^a-zA-Z0-9@])\1{5,}", " ", text)

    # Remove markdown/code block markers
    text = re.sub(r"```[a-z]*", " ", text)
    text = re.sub(r"---+", " ", text)

    # Remove URLs (keep domain but remove query params and long paths)
    text = re.sub(r"https?://[^\s]{50,}", " ", text)

    return text


def _deduplicate_emails(emails: List[Dict]) -> List[Dict]:
    """
    Remove duplicate/similar emails based on full content similarity.

    Uses Levenshtein-like similarity ratio on entire normalized email bodies
    to filter out redundant emails before sending to LLM.

    Args:
        emails: List of email dictionaries

    Returns:
        List of unique emails (no arbitrary limit, just removes duplicates)
    """
    if not emails:
        return []

    def normalize_content(text: str) -> str:
        """Normalize email content for comparison."""
        # Remove numbers (IDs, dates, counts)
        text = re.sub(r"\d+", "", text)
        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)
        # Remove email addresses
        text = re.sub(r"\S+@\S+", "", text)
        # Remove extra whitespace and normalize
        text = re.sub(r"\s+", " ", text)
        # Remove punctuation
        text = re.sub(r"[^\w\s]", "", text)
        return text.strip().lower()

    def calculate_similarity(text1: str, text2: str) -> float:
        """
        Calculate similarity ratio between two texts using sequence matching.
        Returns value between 0 (completely different) and 1 (identical).
        """
        if not text1 or not text2:
            return 0.0

        # Use SequenceMatcher for robust similarity comparison
        return SequenceMatcher(None, text1, text2).ratio()

    unique_emails = []
    normalized_bodies: List[str] = []

    for email in emails:
        # Get full email body (not truncated)
        content = email.get("messageText", "").strip()

        if not content:
            continue

        # Normalize the entire body
        normalized = normalize_content(content)

        if not normalized:
            continue

        # Check similarity against all existing unique emails
        is_duplicate = False
        for existing_normalized in normalized_bodies:
            similarity = calculate_similarity(normalized, existing_normalized)

            # If similarity exceeds threshold, consider it a duplicate
            if similarity >= DEDUPLICATION_SIMILARITY_THRESHOLD:
                is_duplicate = True
                break

        if not is_duplicate:
            normalized_bodies.append(normalized)
            unique_emails.append(email)
            # NO LIMIT - just remove duplicates

    return unique_emails if unique_emails else emails


async def extract_username_with_llm(
    platform: str, emails: List[Dict], user_name: str | None = None
) -> str:
    """
    Use LLM with structured output to extract username from platform emails.

    Args:
        platform: Platform name (e.g., 'twitter', 'github')
        emails: List of emails from that platform (max 10)
        user_name: User's full name to help identify their username

    Returns:
        Extracted username or "NOT_FOUND"
    """
    start_time = time.time()

    if not emails or platform not in PLATFORM_CONFIG:
        return "NOT_FOUND"

    # Deduplicate similar emails to avoid sending redundant context
    unique_emails = _deduplicate_emails(emails)
    logger.info(
        f"Deduplicated {len(emails)} emails down to {len(unique_emails)} unique emails for {platform}"
    )

    # Debug: Log deduplication results
    if settings.DEBUG_EMAIL_PROCESSING:
        debug_dir = os.path.join(os.path.dirname(__file__), "debug_logs")
        os.makedirs(debug_dir, exist_ok=True)
        dedup_file = os.path.join(debug_dir, f"{platform}_deduplication.json")
        with open(dedup_file, "w") as f:
            json.dump(
                {
                    "platform": platform,
                    "original_count": len(emails),
                    "deduplicated_count": len(unique_emails),
                    "removed_count": len(emails) - len(unique_emails),
                    "unique_emails": [
                        {"subject": e.get("subject"), "sender": e.get("sender")}
                        for e in unique_emails
                    ],
                },
                f,
                indent=2,
            )

    # Build context from unique emails with better cleaning
    email_context = []
    for i, email in enumerate(unique_emails, 1):
        subject = email.get("subject", "[No Subject]")
        raw_content = email.get("messageText", "")

        # Filter garbage content first
        cleaned_content = _filter_garbage_content(raw_content)

        # Clean content: remove excessive newlines, special chars, but keep @mentions
        content = cleaned_content.replace("\r\n", " ").replace("\n", " ")
        content = re.sub(r"\s+", " ", content)  # Collapse multiple spaces
        content = content.strip()

        # Skip if content is too short after cleaning (likely all garbage)
        if len(content) < 20:
            continue

        # Extract all @mentions for easier detection
        mentions = re.findall(r"@([a-zA-Z0-9_-]+)", raw_content)
        mentions_str = ", ".join(f"@{m}" for m in mentions) if mentions else "None"

        email_context.append(
            f"Email {i}:\nSubject: {subject}\nMentions: {mentions_str}\nContent: {content}\n"
        )

    emails_text = "\n---\n".join(email_context)

    # Build user context
    user_context = "The recipient's name is unknown."
    if user_name:
        user_context = f"The recipient's name is {user_name}. Look for usernames/handles associated with this person."

    # Debug: Log what's being sent to LLM
    debug_dir = os.path.join(os.path.dirname(__file__), "debug_logs")
    if settings.DEBUG_EMAIL_PROCESSING:
        os.makedirs(debug_dir, exist_ok=True)
        llm_input_file = os.path.join(debug_dir, f"{platform}_llm_input.json")
        with open(llm_input_file, "w") as f:
            json.dump(
                {
                    "platform": platform,
                    "num_emails_sent": len(unique_emails),
                    "emails_text_length": len(emails_text),
                    "emails_text": emails_text,
                },
                f,
                indent=2,
            )

    try:
        # Create parser
        parser = PydanticOutputParser(pydantic_object=UsernameExtraction)

        # Get LLM client with Gemini 2.5 Pro for profile extraction
        llm = init_llm(
            preferred_provider=PROFILE_EXTRACTION_LLM_PROVIDER, fallback_enabled=True
        ).with_config(configurable={"model": PROFILE_EXTRACTION_LLM_MODEL})

        # Format the prompt with parser instructions
        formatted_prompt = EXTRACTION_PROMPT.format(
            platform=platform,
            user_context=user_context,
            emails_text=emails_text,
            format_instructions=parser.get_format_instructions(),
        )

        # Generate response using LLM
        llm_response = await llm.ainvoke(formatted_prompt)

        # Parse the response content
        response_content = getattr(llm_response, "content", str(llm_response))
        result: UsernameExtraction = parser.parse(response_content)

        username = result.username.strip()
        confidence = result.confidence

        # Clean up response
        username = username.replace("@", "").replace("\\n", "").strip()

        elapsed = time.time() - start_time
        logger.info(
            f"LLM extracted username for {platform}: '{username}' "
            f"(confidence: {confidence}) in {elapsed:.2f}s"
        )

        # Debug: Log LLM response
        if settings.DEBUG_EMAIL_PROCESSING:
            debug_dir = os.path.join(os.path.dirname(__file__), "debug_logs")
            llm_output_file = os.path.join(debug_dir, f"{platform}_llm_output.json")
            with open(llm_output_file, "w") as f:
                json.dump(
                    {
                        "platform": platform,
                        "username": username,
                        "confidence": confidence,
                        "elapsed_seconds": elapsed,
                        "raw_response": response_content,
                    },
                    f,
                    indent=2,
                )

        return username

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"LLM extraction failed for {platform} after {elapsed:.2f}s: {e}")
        return "NOT_FOUND"
