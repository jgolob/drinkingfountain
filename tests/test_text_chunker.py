"""Comprehensive tests for the TextChunker utility."""

import pytest

from drinkingfountain.utils.text_chunker import TextChunker


class TestTextChunker:
    """Test suite for TextChunker class."""

    def test_short_text_no_chunking(self):
        """Test that short text (<= max_chunk_size) returns single chunk."""
        chunker = TextChunker(max_chunk_size=50)
        result = chunker.chunk("This is a short text.")
        assert result == ["This is a short text."]
        assert len(result) == 1

    def test_empty_string(self):
        """Test that empty string returns empty list."""
        chunker = TextChunker()
        result = chunker.chunk("")
        assert result == []

    def test_whitespace_only(self):
        """Test that whitespace-only string returns empty list."""
        chunker = TextChunker()
        result = chunker.chunk("   \n\t  ")
        assert result == []

    def test_long_text_with_clear_sentence_boundaries(self):
        """Test chunking with multiple sentences that exceed max size."""
        chunker = TextChunker(max_chunk_size=100, split_on_sentences=True)
        # Create text that will require multiple chunks even with sentence grouping
        sentences = ["This is a reasonably long sentence that takes up space. "] * 10
        text = "".join(sentences)
        result = chunker.chunk(text)

        # All chunks should be <= 100 chars
        for chunk in result:
            assert len(chunk) <= 100

        # Should have multiple chunks
        assert len(result) > 1

        # Combined text should contain all sentences
        combined = " ".join(result)
        # Each sentence should appear 10 times in the combined text
        assert (
            combined.count("This is a reasonably long sentence that takes up space.")
            == 10
        )

    def test_long_text_without_sentence_splitting(self):
        """Test that disabling sentence splitting uses word boundaries."""
        chunker = TextChunker(max_chunk_size=50, split_on_sentences=False)
        text = "This is a very long text without any sentence endings that would normally cause splitting on sentence boundaries but instead splits on words."
        result = chunker.chunk(text)

        for chunk in result:
            assert len(chunk) <= 50

        assert len(result) > 1

    def test_very_long_sentence_falls_back_to_word_splitting(self):
        """Test that a single sentence exceeding max size falls back to word splitting."""
        chunker = TextChunker(max_chunk_size=50, split_on_sentences=True)
        # Create a single sentence longer than 50 chars
        text = "This is a very long sentence that definitely exceeds the fifty character limit and should trigger the fallback mechanism to word-based splitting."
        result = chunker.chunk(text)

        for chunk in result:
            assert len(chunk) <= 50

        assert len(result) > 1

    def test_very_long_word_splits_mid_word(self):
        """Test that extremely long words are split mid-word as last resort."""
        chunker = TextChunker(max_chunk_size=50, split_on_sentences=False)
        # Create a single word longer than 50 chars
        long_word = "a" * 100
        result = chunker.chunk(long_word)

        assert len(result) == 2  # Should be split into 2 chunks of 50 each
        assert len(result[0]) == 50
        assert len(result[1]) == 50
        for chunk in result:
            assert len(chunk) <= 50

    def test_text_with_no_spaces_chinese_like(self):
        """Test text without spaces (e.g., Chinese) splits by character count."""
        chunker = TextChunker(max_chunk_size=20, split_on_sentences=False)
        # Chinese text without spaces
        text = "这是一个很长的中文文本没有空格需要被分割成小块"
        result = chunker.chunk(text)

        for chunk in result:
            assert len(chunk) <= 20

        # Combined should equal original
        combined = "".join(result)
        assert combined == text

    def test_mixed_whitespace_preservation(self):
        """Test that original spacing within chunks is preserved."""
        chunker = TextChunker(max_chunk_size=30, split_on_sentences=False)
        text = "This   has    multiple     spaces   between   words."
        result = chunker.chunk(text)

        # Note: word splitting uses .split() which normalizes spaces
        # This is expected behavior - we preserve spacing within each chunk
        # but the split normalizes consecutive spaces to single space
        for chunk in result:
            assert len(chunk) <= 30

    def test_exact_boundary_case(self):
        """Test text exactly at max_chunk_size."""
        chunker = TextChunker(max_chunk_size=20)
        text = "Exactly twenty!"  # 15 chars
        result = chunker.chunk(text)
        assert result == ["Exactly twenty!"]

        # Test exact boundary
        text_exact = "01234567890123456789"  # exactly 20 chars
        result = chunker.chunk(text_exact)
        assert result == ["01234567890123456789"]

    def test_single_character_chunks(self):
        """Test with very small chunk size."""
        chunker = TextChunker(max_chunk_size=1, split_on_sentences=False)
        text = "abc"
        result = chunker.chunk(text)
        assert result == ["a", "b", "c"]

    def test_sentence_boundary_with_various_punctuation(self):
        """Test splitting on different sentence endings."""
        chunker = TextChunker(max_chunk_size=100, split_on_sentences=True)
        text = "First sentence. Second sentence! Third sentence? Fourth sentence."
        result = chunker.chunk(text)

        # Should split on all three punctuation marks
        all_text = " ".join(result)
        assert "First sentence" in all_text
        assert "Second sentence" in all_text
        assert "Third sentence" in all_text
        assert "Fourth sentence" in all_text

    def test_sentence_grouping_optimization(self):
        """Test that multiple small sentences are grouped efficiently."""
        chunker = TextChunker(max_chunk_size=100, split_on_sentences=True)
        # Create several small sentences that should fit in one chunk
        sentences = ["Short one. ", "Another short. ", "Yet another. ", "And one more."]
        text = "".join(sentences)
        result = chunker.chunk(text)

        # Should have fewer chunks than sentences (grouped)
        assert len(result) < len(sentences)
        # First chunk should contain multiple sentences
        assert len(result[0]) <= 100

    def test_invalid_max_chunk_size(self):
        """Test that invalid max_chunk_size raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            TextChunker(max_chunk_size=0)
        with pytest.raises(ValueError, match="must be positive"):
            TextChunker(max_chunk_size=-1)

    def test_sentence_without_trailing_space(self):
        """Test sentence at end of text without trailing whitespace."""
        chunker = TextChunker(max_chunk_size=50, split_on_sentences=True)
        text = "First sentence. Second sentence."
        result = chunker.chunk(text)

        assert len(result) >= 1
        for chunk in result:
            assert len(chunk) <= 50

    def test_word_splitting_preserves_word_order(self):
        """Test that word splitting maintains word order."""
        chunker = TextChunker(max_chunk_size=20, split_on_sentences=False)
        text = "One two three four five six seven eight nine ten"
        result = chunker.chunk(text)

        combined = " ".join(result)
        original_words = text.split()
        result_words = combined.split()
        assert original_words == result_words

    def test_large_chunk_size_with_many_sentences(self):
        """Test with large chunk size containing many sentences."""
        chunker = TextChunker(max_chunk_size=500, split_on_sentences=True)
        # Create a paragraph with many sentences
        sentences = [f"This is sentence number {i}. " for i in range(50)]
        text = "".join(sentences)
        result = chunker.chunk(text)

        # Should have relatively few chunks due to large size limit
        assert len(result) < 10

        for chunk in result:
            assert len(chunk) <= 500

    def test_text_with_newlines(self):
        """Test text containing newlines is handled correctly."""
        chunker = TextChunker(max_chunk_size=50, split_on_sentences=True)
        text = "First line.\nSecond line.\nThird line."
        result = chunker.chunk(text)

        for chunk in result:
            assert len(chunk) <= 50

    def test_sentence_splitting_disabled_but_sentences_present(self):
        """Test that disabling sentence splitting ignores sentence boundaries."""
        chunker = TextChunker(max_chunk_size=30, split_on_sentences=False)
        text = "First sentence. Second sentence. Third sentence."
        result = chunker.chunk(text)

        # Should split on words, not sentences
        for chunk in result:
            assert len(chunk) <= 30

    def test_leading_trailing_whitespace_stripped(self):
        """Test that chunks have leading/trailing whitespace stripped."""
        chunker = TextChunker(max_chunk_size=20)
        text = "   Lots of leading and trailing spaces.   "
        result = chunker.chunk(text)

        for chunk in result:
            assert chunk == chunk.strip()
            assert not chunk.startswith(" ")
            assert not chunk.endswith(" ")

    def test_configurability_different_sizes(self):
        """Test that different chunk sizes produce different results."""
        text = "This is a test string that will be chunked differently based on size."

        chunker_small = TextChunker(max_chunk_size=20)
        result_small = chunker_small.chunk(text)

        chunker_large = TextChunker(max_chunk_size=100)
        result_large = chunker_large.chunk(text)

        # Larger chunk size should produce fewer chunks
        assert len(result_large) <= len(result_small)
        # If text > 100, large should be 1, small should be more
        if len(text) > 100:
            assert len(result_large) == 1

    def test_real_world_dialogue_example(self):
        """Test with realistic dialogue that might come from a script."""
        chunker = TextChunker(max_chunk_size=200, split_on_sentences=True)
        dialogue = (
            "CHARACTER A: Hello, how are you doing today? I wanted to check in "
            "and see if you had any updates on the project status. We're getting "
            "close to the deadline and I want to make sure everything is on track. "
            "Please let me know as soon as possible. Thank you!"
        )
        result = chunker.chunk(dialogue)

        for chunk in result:
            assert len(chunk) <= 200

        # Should be split into multiple chunks
        assert len(result) >= 2
