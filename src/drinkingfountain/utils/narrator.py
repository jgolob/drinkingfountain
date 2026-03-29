"""Narrator utility functions for drinkingfountain.

This module provides utilities for transforming script content for the narrator,
including expanding INT/EXT abbreviations to their full forms for better speech
intelligibility.
"""

import re
from typing import Final


def transform_scene_heading(text: str, expand_int_ext: bool = True) -> str:
    """Transform a scene heading for narration by expanding INT/EXT abbreviations.

    When expand_int_ext is True, this function replaces common screenplay
    abbreviations at the beginning of scene headings with their full words:
    - "INT" or "INT." becomes "Interior"
    - "EXT" or "EXT." becomes "Exterior"

    The transformation is case-insensitive and preserves the rest of the
    heading text exactly as it appears (including case and punctuation).

    Args:
        text: The original scene heading text
        expand_int_ext: Whether to perform the expansion (default: True)

    Returns:
        The transformed scene heading text

    Examples:
        >>> transform_scene_heading("INT. HOUSE - DAY")
        'Interior HOUSE - DAY'
        >>> transform_scene_heading("int. house - day")
        'Interior house - day'
        >>> transform_scene_heading("EXT. PARK")
        'Exterior PARK'
        >>> transform_scene_heading("INT HOUSE - DAY")
        'Interior HOUSE - DAY'
        >>> transform_scene_heading("FADE IN.")
        'FADE IN.'
        >>> transform_scene_heading("INT. HOUSE - DAY", expand_int_ext=False)
        'INT. HOUSE - DAY'
    """
    if not expand_int_ext:
        return text

    # Separate leading whitespace to preserve it
    leading_ws = ""
    rest = text
    i = 0
    while i < len(text) and text[i].isspace():
        i += 1
    if i > 0:
        leading_ws = text[:i]
        rest = text[i:]

    # Pattern: INT or EXT optionally followed by a period, then optional whitespace
    # This operates on the rest (without leading whitespace)
    pattern: Final = r"^(INT|EXT)\.?\s*"

    def replace_match(match: re.Match) -> str:
        marker = match.group(1).upper()
        if marker == "INT":
            replacement = "Interior"
        else:  # marker == "EXT"
            replacement = "Exterior"
        # Preserve the whitespace after the marker if there was any
        matched_text = match.group(0)
        # Extract the part after the marker
        after_marker = matched_text[len(match.group(1)):]  # includes period and whitespace
        # Keep only whitespace characters (drop period if present)
        trailing_whitespace = "".join(c for c in after_marker if c.isspace())
        return replacement + trailing_whitespace

    result = re.sub(pattern, replace_match, rest, flags=re.IGNORECASE)
    return leading_ws + result
