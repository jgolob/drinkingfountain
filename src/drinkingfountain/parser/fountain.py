"""Fountain format parser.

This module provides a parser for Fountain screenplay format.
It reads a plain-text Fountain file and constructs a Script object
with scenes, dialogue, actions, and other elements.

The parser implements a state machine based on the official Fountain specification.
"""

import re
from collections.abc import Iterable
from pathlib import Path

from .script import (
    Action,
    Block,
    Dialogue,
    Parenthetical,
    Scene,
    SceneHeading,
    Script,
    Transition,
)


class FountainParser:
    """Parser for Fountain-format screenplays.

    The parser uses a state machine with the following state variables:
    - current_scene: the scene currently being built
    - current_character: the character whose dialogue is being collected
    - dialogue_lines: accumulated lines of the current dialogue block
    - parentheticals: parentheticals collected for the current dialogue block
    - prev_line_blank: whether the previous line was blank (important for elements requiring preceding blank)
    """

    # Regex patterns for element detection
    # Scene heading: starts with INT./EXT./INT/EXT./EXT/INT./EST./I/E. (case-insensitive)
    SCENE_PATTERN = re.compile(
        r"^(INT\.?|EXT\.?|INT/EXT\.?|EXT/INT\.?|EST\.?|I/E\.?)\s+", re.IGNORECASE
    )
    # Forced scene: line starts with a single period
    FORCED_SCENE_PATTERN = re.compile(r"^\.")
    # Transition: all caps ending with TO:
    TRANSITION_PATTERN = re.compile(r"^[A-Z][A-Z0-9\s]*TO:\s*$")
    # Forced transition: line starts with >
    FORCED_TRANSITION_PATTERN = re.compile(r"^>")
    # Character: all caps (letters, numbers, spaces), 1-3 words, at least one letter
    CHARACTER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\s]*[A-Za-z][A-Z0-9\s]*$")
    # Forced character: line starts with @
    FORCED_CHARACTER_PATTERN = re.compile(r"^@")
    # Parenthetical: line entirely in parentheses
    PARENTHETICAL_PATTERN = re.compile(r"^\([^)]+\)$")
    # Forced action: line starts with !
    FORCED_ACTION_PATTERN = re.compile(r"^!")
    # Fountain title page metadata before the first scene.
    TITLE_PAGE_KEY_PATTERN = re.compile(
        r"^(title|credit|author|authors|source|draft date|date|contact|copyright|"
        r"notes?|revision|revisions|about the author)\s*:",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self.line_number = 0

    def parse(self, file_path: Path) -> Script:
        """Parse a Fountain file into a Script object.

        Args:
            file_path: Path to the Fountain file.

        Returns:
            A Script object representing the parsed screenplay.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Script file not found: {file_path}")

        self.line_number = 0
        script = Script(title=file_path.stem)
        with open(file_path, encoding="utf-8") as f:
            return self._parse_lines(f, script)

    def parse_string(self, text: str, title: str | None = None) -> Script:
        """Parse Fountain text from a string.

        Args:
            text: Fountain-format screenplay text.
            title: Optional title for the script.

        Returns:
            A Script object representing the parsed screenplay.
        """
        self.line_number = 0
        script = Script(title=title)
        return self._parse_lines(text.splitlines(keepends=True), script)

    def _parse_lines(self, lines: Iterable[str], script: Script) -> Script:
        """Core line-processing state machine.

        Args:
            lines: Iterable of raw lines (with newlines).
            script: Script object to populate.

        Returns:
            The populated Script object.
        """
        current_scene: Scene | None = None
        current_character: str | None = None
        dialogue_lines: list[str] = []
        parentheticals: list[Parenthetical] = []
        prev_line_blank = True
        in_boneyard = False
        in_title_page_value = False

        for raw_line in lines:
            self.line_number += 1
            line = raw_line.rstrip("\n\r")  # keep all spaces except newline
            # Remove inline notes [[...]] from the line
            clean_line = re.sub(r"\[\[.*?\]\]", "", line)

            # After cleaning, check if line is effectively blank
            if clean_line.strip() == "":
                # Treat as blank line
                prev_line_blank = True
                in_title_page_value = False
                if current_character and dialogue_lines:
                    self._flush_dialogue(
                        script,
                        current_scene,
                        current_character,
                        dialogue_lines,
                        parentheticals,
                    )
                    current_character = None
                    dialogue_lines = []
                    parentheticals = []
                continue

            # At this point, clean_line is non-blank after note removal
            stripped = clean_line.strip()

            # Check for boneyard (skip lines)
            if in_boneyard:
                if "*/" in clean_line:
                    in_boneyard = False
                continue
            if "/*" in clean_line:
                if "*/" in clean_line:
                    # single-line boneyard, skip this line
                    continue
                else:
                    in_boneyard = True
                    continue

            if current_scene is None and self._is_title_page_key(stripped):
                in_title_page_value = True
                prev_line_blank = False
                continue

            if (
                current_scene is None
                and in_title_page_value
                and not (
                    prev_line_blank
                    and (
                        self._is_scene_heading(stripped)
                        or self.FORCED_SCENE_PATTERN.match(stripped)
                    )
                )
            ):
                prev_line_blank = False
                continue

            # Check for sections (#) and synopses (=) - ignore completely
            if stripped.startswith("#") or stripped.startswith("="):
                in_title_page_value = False
                continue

            # Check for page break (=== or more)
            if re.fullmatch(r"={3,}", stripped):
                continue

            # Check for centered text (>...<) - treat as action
            if stripped.startswith(">") and stripped.endswith("<"):
                content = stripped[1:-1].strip()
                block: Block = Action(self.line_number, content)
                self._flush_dialogue_if_needed(
                    script,
                    current_scene,
                    current_character,
                    dialogue_lines,
                    parentheticals,
                )
                if current_scene is None:
                    heading = SceneHeading(self.line_number, "", "UNKNOWN")
                    current_scene = script.add_block(heading, current_scene)
                assert current_scene is not None
                current_scene.blocks.append(block)
                current_character = None
                prev_line_blank = False
                continue

            # Check for lyrics (~) - treat as action with tilde removed
            if stripped.startswith("~"):
                content = stripped[1:].strip()
                block = Action(self.line_number, content)
                self._flush_dialogue_if_needed(
                    script,
                    current_scene,
                    current_character,
                    dialogue_lines,
                    parentheticals,
                )
                if current_scene is None:
                    heading = SceneHeading(self.line_number, "", "UNKNOWN")
                    current_scene = script.add_block(heading, current_scene)
                assert current_scene is not None
                current_scene.blocks.append(block)
                current_character = None
                prev_line_blank = False
                continue

            # 1. Check for scene heading (requires prev_line_blank)
            if prev_line_blank and (
                self._is_scene_heading(stripped)
                or self.FORCED_SCENE_PATTERN.match(stripped)
            ):
                in_title_page_value = False
                # Remove forced dot if present for content and parsing
                if stripped.startswith("."):
                    cleaned = stripped[1:].strip()
                else:
                    cleaned = stripped
                location, time_part = self._parse_scene_heading(cleaned)
                block = SceneHeading(self.line_number, cleaned, location, time_part)
                self._flush_dialogue_if_needed(
                    script,
                    current_scene,
                    current_character,
                    dialogue_lines,
                    parentheticals,
                )
                current_scene = script.add_block(block, current_scene)
                current_character = None
                prev_line_blank = False
                continue

            # 2. Check for transition (requires prev_line_blank)
            if prev_line_blank and (
                self._is_transition(stripped)
                or self.FORCED_TRANSITION_PATTERN.match(stripped)
            ):
                content = stripped[1:].strip() if stripped.startswith(">") else stripped
                block = Transition(self.line_number, content)
                self._flush_dialogue_if_needed(
                    script,
                    current_scene,
                    current_character,
                    dialogue_lines,
                    parentheticals,
                )
                if current_scene is None:
                    heading = SceneHeading(self.line_number, "", "UNKNOWN")
                    current_scene = script.add_block(heading, current_scene)
                assert current_scene is not None
                current_scene.blocks.append(block)
                current_character = None
                prev_line_blank = False
                continue

            # 3. Check for character (requires prev_line_blank)
            if prev_line_blank and (
                self._is_character(stripped)
                or self.FORCED_CHARACTER_PATTERN.match(stripped)
            ):
                name = self._clean_character_name(stripped)
                self._flush_dialogue_if_needed(
                    script,
                    current_scene,
                    current_character,
                    dialogue_lines,
                    parentheticals,
                )
                current_character = name
                dialogue_lines = []
                parentheticals = []
                prev_line_blank = False
                continue

            # 4. If in dialogue context, check for parenthetical
            if current_character is not None and self._is_parenthetical(stripped):
                text = stripped.strip("()")
                parentheticals.append(Parenthetical(self.line_number, text))
                prev_line_blank = False
                continue

            # 5. If in dialogue context, handle potential structural lines that lack blank
            if current_character is not None:
                # If this line is a scene heading or transition (including forced) but prev_line_blank is False,
                # it should end the dialogue and be treated as action.
                if (
                    self._is_scene_heading(stripped)
                    or self._is_transition(stripped)
                    or self.FORCED_SCENE_PATTERN.match(stripped)
                    or self.FORCED_TRANSITION_PATTERN.match(stripped)
                ):
                    # Flush current dialogue
                    self._flush_dialogue(
                        script,
                        current_scene,
                        current_character,
                        dialogue_lines,
                        parentheticals,
                    )
                    current_character = None
                    dialogue_lines = []
                    parentheticals = []
                    # Treat this line as action (forced scene/transition become action without their markers)
                    if self.FORCED_SCENE_PATTERN.match(stripped):
                        content = stripped[1:].strip()
                    elif self.FORCED_TRANSITION_PATTERN.match(stripped):
                        content = stripped[1:].strip()
                    else:
                        content = stripped
                    block = Action(self.line_number, content)
                    if current_scene is None:
                        heading = SceneHeading(self.line_number, "", "UNKNOWN")
                        current_scene = script.add_block(heading, current_scene)
                    assert current_scene is not None
                    current_scene.blocks.append(block)
                    prev_line_blank = False
                    continue
                else:
                    # Normal dialogue line
                    dialogue_lines.append(stripped)
                    prev_line_blank = False
                    continue

            # 6. Not in dialogue: this is an Action (or forced action)
            if self.FORCED_ACTION_PATTERN.match(stripped):
                content = stripped[1:].strip()
                block = Action(self.line_number, content)
            else:
                # Use clean_line to preserve leading whitespace (but without notes)
                block = Action(self.line_number, clean_line)

            self._flush_dialogue_if_needed(
                script,
                current_scene,
                current_character,
                dialogue_lines,
                parentheticals,
            )
            if current_scene is None:
                heading = SceneHeading(self.line_number, "", "UNKNOWN")
                current_scene = script.add_block(heading, current_scene)
            assert current_scene is not None
            current_scene.blocks.append(block)
            current_character = None
            prev_line_blank = False

        # After loop: flush any remaining dialogue
        if current_character and dialogue_lines:
            self._flush_dialogue(
                script, current_scene, current_character, dialogue_lines, parentheticals
            )

        return script

    def _is_scene_heading(self, line: str) -> bool:
        """Check if line is a scene heading."""
        if not line:
            return False
        upper = line.upper()
        prefixes = ["INT", "EXT", "INT/EXT", "EXT/INT", "EST", "I/E"]
        for prefix in prefixes:
            if upper.startswith(prefix):
                # Check that after the prefix, the next character is '.' or ' '
                idx = len(prefix)
                if idx < len(line):
                    next_char = line[idx]
                    if next_char in (".", " "):
                        return True
        return False

    def _is_transition(self, line: str) -> bool:
        """Check if line matches transition pattern."""
        if not line:
            return False
        return self.TRANSITION_PATTERN.match(line) is not None

    def _is_character(self, line: str) -> bool:
        """Check if line is a character name."""
        if not line:
            return False
        line = self._strip_full_line_emphasis(line)
        # Forced characters are handled separately; return False for them here.
        # Strip any trailing parenthetical (e.g., "JOHN (O.S.)" -> "JOHN")
        name = line
        match = re.search(r"\s*\([^)]*\)\s*$", line)
        if match:
            name = line[: match.start()].strip()
        # Also strip trailing caret for dual dialogue (e.g., "STEEL ^" -> "STEEL")
        if name.endswith(" ^"):
            name = name[:-2].strip()
        elif name.endswith("^"):
            name = name[:-1].strip()
        if not name:
            return False
        # Must be all uppercase letters, numbers, and spaces
        if not re.fullmatch(r"[A-Z0-9\s]+", name):
            return False
        # Must contain at least one alphabetical character
        if not any(c.isalpha() for c in name):
            return False
        # Character names are typically 1-3 words
        words = name.split()
        if len(words) > 3:
            return False
        # Ensure not a scene heading or transition (unlikely but safe)
        return True

    def _is_parenthetical(self, line: str) -> bool:
        """Check if line is a parenthetical."""
        if not line:
            return False
        return self.PARENTHETICAL_PATTERN.fullmatch(line) is not None

    def _is_title_page_key(self, line: str) -> bool:
        """Check if a line is a Fountain title-page metadata key."""
        return self.TITLE_PAGE_KEY_PATTERN.match(line) is not None

    def _clean_character_name(self, line: str) -> str:
        """Extract character name, removing parenthetical extension and dual dialogue caret."""
        if line.startswith("@"):
            line = line[1:].strip()
        line = self._strip_full_line_emphasis(line)
        # Remove trailing parenthetical: e.g., "MOM (O.S.)" -> "MOM"
        name = re.sub(r"\s*\(.*?\)\s*$", "", line).strip()
        # Remove trailing caret for dual dialogue: e.g., "STEEL ^" -> "STEEL"
        if name.endswith(" ^"):
            name = name[:-2].strip()
        elif name.endswith("^"):
            name = name[:-1].strip()
        return name

    def _strip_full_line_emphasis(self, line: str) -> str:
        """Remove Markdown emphasis when it wraps an entire character cue."""
        stripped = line.strip()
        for marker in ("**", "__", "*", "_"):
            if (
                stripped.startswith(marker)
                and stripped.endswith(marker)
                and len(stripped) > len(marker) * 2
            ):
                return stripped[len(marker) : -len(marker)].strip()
        return line

    def _parse_scene_heading(self, line: str) -> tuple[str, str | None]:
        """Parse scene heading into location and time."""
        # Remove forced scene prefix if present
        if line.startswith("."):
            line = line[1:].strip()
        # Try to split on " - " first
        if " - " in line:
            parts = line.split(" - ", 1)
            return parts[0].strip(), parts[1].strip()
        # Try " -" (no space after dash)
        if " -" in line:
            parts = line.split(" -", 1)
            return parts[0].strip(), parts[1].strip()
        # No time part
        return line, None

    def _flush_dialogue_if_needed(
        self,
        script: Script,
        current_scene: Scene | None,
        character: str | None,
        dialogue_lines: list[str],
        parentheticals: list[Parenthetical],
    ) -> None:
        """Flush pending dialogue if any."""
        if character is None or not dialogue_lines:
            return
        self._flush_dialogue(
            script, current_scene, character, dialogue_lines, parentheticals
        )

    def _flush_dialogue(
        self,
        script: Script,
        current_scene: Scene | None,
        character: str,
        dialogue_lines: list[str],
        parentheticals: list[Parenthetical],
    ) -> None:
        """Create a Dialogue block and add it to the script."""
        if not dialogue_lines:
            return
        content = "\n".join(dialogue_lines)
        line_num = parentheticals[0].line_number if parentheticals else self.line_number
        dialogue = Dialogue(
            line_number=line_num,
            character=character,
            content=content,
            parentheticals=parentheticals.copy(),
        )
        if current_scene is None:
            heading = SceneHeading(self.line_number, "", "UNKNOWN")
            current_scene = script.add_block(heading, current_scene)
        # Use script.add_block to add dialogue and track character
        script.add_block(dialogue, current_scene)
