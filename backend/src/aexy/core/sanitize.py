"""Input sanitization utilities for user-generated content."""

import html
import re


# Regex to match HTML tags
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# Maximum lengths for different content types
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000
MAX_COMMENT_LENGTH = 2000


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text.

    Args:
        text: Input string that may contain HTML tags.

    Returns:
        String with all HTML tags removed.
    """
    if not text:
        return text
    return HTML_TAG_PATTERN.sub("", text)


def sanitize_text(
    text: str | None,
    max_length: int | None = None,
    strip_html: bool = True,
) -> str | None:
    """Sanitize user-provided text content.

    Performs the following operations:
    1. Strips leading/trailing whitespace
    2. Removes HTML tags (optional)
    3. Escapes remaining HTML entities
    4. Truncates to max length if specified

    Args:
        text: Input text to sanitize.
        max_length: Maximum allowed length (truncates if exceeded).
        strip_html: Whether to strip HTML tags (default True).

    Returns:
        Sanitized text string, or None if input was None.
    """
    if text is None:
        return None

    # Strip whitespace
    result = text.strip()

    if not result:
        return result

    # Strip HTML tags if requested
    if strip_html:
        result = strip_html_tags(result)

    # Escape any remaining HTML entities for safety
    result = html.escape(result)

    # Truncate if max_length specified
    if max_length and len(result) > max_length:
        result = result[:max_length]

    return result


def sanitize_title(text: str | None) -> str | None:
    """Sanitize a title field.

    Args:
        text: Title text to sanitize.

    Returns:
        Sanitized title, truncated to MAX_TITLE_LENGTH.
    """
    return sanitize_text(text, max_length=MAX_TITLE_LENGTH)


def sanitize_description(text: str | None) -> str | None:
    """Sanitize a description field.

    Args:
        text: Description text to sanitize.

    Returns:
        Sanitized description, truncated to MAX_DESCRIPTION_LENGTH.
    """
    return sanitize_text(text, max_length=MAX_DESCRIPTION_LENGTH)


def sanitize_comment(text: str | None) -> str | None:
    """Sanitize a comment field.

    Args:
        text: Comment text to sanitize.

    Returns:
        Sanitized comment, truncated to MAX_COMMENT_LENGTH.
    """
    return sanitize_text(text, max_length=MAX_COMMENT_LENGTH)
