"""Data structures for representing a Fountain script."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum


class BlockType(Enum):
    """Types of blocks in a Fountain script."""

    CHARACTER = "character"
    DIALOGUE = "dialogue"
    PARENTHETICAL = "parenthetical"
    SCENE_HEADING = "scene_heading"
    ACTION = "action"
    TRANSITION = "transition"


@dataclass
class Block:
    """Base class for all script blocks."""

    type: BlockType
    line_number: int
    content: str


@dataclass
class Character(Block):
    """A character name line."""

    name: str

    def __init__(self, line_number: int, name: str) -> None:
        super().__init__(BlockType.CHARACTER, line_number, name)
        self.name = name


@dataclass
class Dialogue(Block):
    """A dialogue line spoken by a character."""

    character: str
    parentheticals: list["Parenthetical"] = field(default_factory=list)

    def __init__(
        self,
        line_number: int,
        character: str,
        content: str,
        parentheticals: list["Parenthetical"] | None = None,
    ) -> None:
        super().__init__(BlockType.DIALOGUE, line_number, content)
        self.character = character
        self.parentheticals = parentheticals or []


@dataclass
class Parenthetical(Block):
    """A parenthetical direction within dialogue."""

    text: str

    def __init__(self, line_number: int, text: str) -> None:
        super().__init__(BlockType.PARENTHETICAL, line_number, text)
        self.text = text


@dataclass
class SceneHeading(Block):
    """A scene heading (INT./EXT. or SCENE:)."""

    location: str
    time: str | None = None

    def __init__(
        self,
        line_number: int,
        content: str,
        location: str,
        time: str | None = None,
    ) -> None:
        super().__init__(BlockType.SCENE_HEADING, line_number, content)
        self.location = location
        self.time = time


@dataclass
class Action(Block):
    """An action or description line."""

    def __init__(self, line_number: int, content: str) -> None:
        super().__init__(BlockType.ACTION, line_number, content)


@dataclass
class Transition(Block):
    """A transition (CUT TO:, FADE OUT., etc.)."""

    def __init__(self, line_number: int, content: str) -> None:
        super().__init__(BlockType.TRANSITION, line_number, content)


@dataclass
class Scene:
    """A scene containing a heading and a sequence of blocks."""

    heading: SceneHeading
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Script:
    """Complete representation of a screenplay."""

    title: str | None = None
    scenes: list[Scene] = field(default_factory=list)
    characters: set[str] = field(default_factory=set)  # Unique character names

    def add_block(
        self,
        block: Block,
        current_scene: Scene | None = None,
    ) -> Scene | None:
        """Add a block to the script, creating a new scene if needed.

        Args:
            block: The block to add.
            current_scene: The current scene being built, if any.

        Returns:
            The current scene (new or existing).
        """
        if isinstance(block, SceneHeading):
            scene = Scene(heading=block)
            self.scenes.append(scene)
            return scene
        elif current_scene is not None:
            current_scene.blocks.append(block)
            if isinstance(block, Character):
                self.characters.add(block.name)
            elif isinstance(block, Dialogue):
                self.characters.add(block.character)
        return current_scene

    def all_blocks(self) -> Sequence[Block]:
        """Return all blocks in the script in order."""
        blocks: list[Block] = []
        for scene in self.scenes:
            blocks.append(scene.heading)
            blocks.extend(scene.blocks)
        return blocks
