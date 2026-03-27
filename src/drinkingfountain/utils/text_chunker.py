"""Text chunking utility for handling long dialogue lines."""

import re


class TextChunker:
    """Chunks text into smaller pieces based on configurable size limits.

    The chunker implements a multi-strategy approach:
    1. If text is already under the size limit, return as-is
    2. If sentence splitting is enabled, try to split on sentence boundaries
    3. If sentences are too long, fall back to word-boundary splitting
    4. As a last resort, split by character count (for very long words or no spaces)

    Attributes:
        max_chunk_size: Maximum size of each chunk in characters
        split_on_sentences: Whether to prioritize sentence boundary splits
    """

    def __init__(self, max_chunk_size: int = 500, split_on_sentences: bool = True):
        """Initialize the TextChunker.

        Args:
            max_chunk_size: Maximum number of characters per chunk (default: 500)
            split_on_sentences: If True, attempt to split on sentence boundaries first
        """
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size must be positive")
        self.max_chunk_size = max_chunk_size
        self.split_on_sentences = split_on_sentences

    def chunk(self, text: str) -> list[str]:
        """Split text into chunks respecting the size limit.

        Args:
            text: The input text to chunk

        Returns:
            List of text chunks, each <= max_chunk_size

        Edge cases:
            - Empty string returns empty list
            - Preserves original whitespace within chunks (strips leading/trailing)
            - Handles very long words by splitting mid-word if necessary
            - Works with text without spaces (e.g., Chinese) via character splitting
        """
        if not text:
            return []

        # If text already fits, return as-is (but check if stripped text is non-empty)
        if len(text) <= self.max_chunk_size:
            stripped = text.strip()
            return [stripped] if stripped else []

        chunks = []

        # Try sentence-based splitting if enabled
        if self.split_on_sentences:
            chunks = self._chunk_by_sentences(text)

        # Fall back to word-based splitting if sentence splitting didn't work
        if not chunks:
            chunks = self._chunk_by_words(text)

        # Last resort: character-based splitting (for text with no spaces or very long words)
        if not chunks:
            chunks = self._chunk_by_characters(text)

        # Filter out any empty chunks and strip whitespace
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def _chunk_by_sentences(self, text: str) -> list[str]:
        """Split text on sentence boundaries while respecting chunk size.

        Attempts to group multiple sentences into chunks up to max_chunk_size.
        If a single sentence exceeds max_chunk_size, returns empty list to
        signal that word-based splitting should be used instead.
        """
        # Split on sentence boundaries while preserving the delimiter
        # Pattern: split on . ! ? followed by whitespace or end of string
        sentence_pattern = r"(?<=[.!?])\s+"
        sentences = re.split(sentence_pattern, text)

        # Filter out empty sentences
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return []

        chunks = []
        current_chunk = []
        current_size = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            # If a single sentence is too long, sentence splitting won't work
            if sentence_len > self.max_chunk_size:
                return []  # Signal to use word-based splitting

            # Would adding this sentence exceed the limit?
            # Account for space between sentences if chunk not empty
            projected_size = current_size + (1 if current_chunk else 0) + sentence_len

            if projected_size <= self.max_chunk_size:
                # Add to current chunk
                current_chunk.append(sentence)
                current_size = projected_size
            else:
                # Current chunk is full, start new one
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_size = sentence_len

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def _chunk_by_words(self, text: str) -> list[str]:
        """Split text on word boundaries (spaces) while respecting chunk size."""
        words = text.split()

        if not words:
            return []

        # Check if any word exceeds max_chunk_size - if so, we need character splitting
        if any(len(word) > self.max_chunk_size for word in words):
            return []  # Signal to use character-based splitting

        chunks = []
        current_chunk = []
        current_size = 0

        for word in words:
            word_len = len(word)

            # Account for space between words if chunk not empty
            projected_size = current_size + (1 if current_chunk else 0) + word_len

            if projected_size <= self.max_chunk_size:
                # Add to current chunk
                current_chunk.append(word)
                current_size = projected_size
            else:
                # Current chunk is full, start new one
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                current_chunk = [word]
                current_size = word_len

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def _chunk_by_characters(self, text: str) -> list[str]:
        """Split text by character count as a last resort."""
        chunks = []
        for i in range(0, len(text), self.max_chunk_size):
            chunk = text[i : i + self.max_chunk_size]
            chunks.append(chunk.strip())
        return chunks
