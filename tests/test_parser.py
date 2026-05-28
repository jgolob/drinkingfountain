"""Tests for the Fountain parser."""

from pathlib import Path

import pytest

from drinkingfountain.parser.fountain import FountainParser
from drinkingfountain.parser.script import (
    Action,
    Dialogue,
    SceneHeading,
    Transition,
)


@pytest.fixture
def parser() -> FountainParser:
    return FountainParser()


def test_parse_simple_script(parser: FountainParser, tmp_path: Path) -> None:
    """Test parsing a minimal script."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. HOUSE - DAY

JOHN
Hello, Mary.

MARY
Hi, John.
"""
    )
    script = parser.parse(script_file)

    assert script.title == "test"
    assert len(script.scenes) == 1
    scene = script.scenes[0]
    assert isinstance(scene.heading, SceneHeading)
    assert scene.heading.location == "INT. HOUSE"
    assert scene.heading.time == "DAY"

    # Check blocks: should have character and dialogue for each
    # Note: parser doesn't add Character blocks directly; they're part of Dialogue
    assert len(scene.blocks) == 2
    first = scene.blocks[0]
    assert isinstance(first, Dialogue)
    assert first.character == "JOHN"
    assert first.content == "Hello, Mary."
    assert len(first.parentheticals) == 0

    second = scene.blocks[1]
    assert isinstance(second, Dialogue)
    assert second.character == "MARY"
    assert second.content == "Hi, John."

    assert script.characters == {"JOHN", "MARY"}


def test_parse_string_resets_line_numbers(parser: FountainParser) -> None:
    """Test that parse_string can safely reuse a parser instance."""
    first = parser.parse_string(
        """INT. ROOM - DAY

JOHN
Hello.
"""
    )
    second = parser.parse_string(
        """EXT. STREET - NIGHT

MARY
Hi.
"""
    )

    assert first.scenes[0].heading.line_number == 1
    assert second.scenes[0].heading.line_number == 1


def test_parse_with_parentheticals(parser: FountainParser, tmp_path: Path) -> None:
    """Test parsing dialogue with parentheticals."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. CAFE - DAY

JOHN
(sighs)
I don't know.
(beat)
Maybe we should try again.
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 1
    scene = script.scenes[0]
    assert len(scene.blocks) == 1
    dialogue = scene.blocks[0]
    assert isinstance(dialogue, Dialogue)
    assert dialogue.character == "JOHN"
    assert dialogue.content == "I don't know.\nMaybe we should try again."
    assert len(dialogue.parentheticals) == 2
    assert dialogue.parentheticals[0].text == "sighs"
    assert dialogue.parentheticals[1].text == "beat"


def test_parse_multiple_scenes(parser: FountainParser, tmp_path: Path) -> None:
    """Test parsing multiple scenes."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. HOUSE - DAY

JOHN
Hello.

EXT. PARK - NIGHT

JOHN
(whispering)
It's dark here.
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 2
    scene1 = script.scenes[0]
    assert scene1.heading.location == "INT. HOUSE"
    assert scene1.heading.time == "DAY"
    assert len(scene1.blocks) == 1
    assert scene1.blocks[0].content == "Hello."

    scene2 = script.scenes[1]
    assert scene2.heading.location == "EXT. PARK"
    assert scene2.heading.time == "NIGHT"
    assert len(scene2.blocks) == 1
    dialogue = scene2.blocks[0]
    assert isinstance(dialogue, Dialogue)
    assert dialogue.character == "JOHN"
    assert "(whispering)" not in dialogue.content  # parenthetical removed from content
    assert "It's dark here." in dialogue.content


def test_parse_action_lines(parser: FountainParser, tmp_path: Path) -> None:
    """Test that non-dialogue lines become action blocks."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

John enters the room.
He looks around.

JOHN
What are you doing?
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 1
    scene = script.scenes[0]
    # Should have 2 action blocks and 1 dialogue
    assert len(scene.blocks) == 3
    assert isinstance(scene.blocks[0], Action)
    assert scene.blocks[0].content == "John enters the room."
    assert isinstance(scene.blocks[1], Action)
    assert scene.blocks[1].content == "He looks around."
    assert isinstance(scene.blocks[2], Dialogue)
    assert scene.blocks[2].character == "JOHN"


def test_parse_transitions(parser: FountainParser, tmp_path: Path) -> None:
    """Test parsing transition lines."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN
Hello.

CUT TO:

EXT. STREET - DAY
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 2
    scene1 = script.scenes[0]
    # The transition should be in the first scene's blocks
    # Actually, after CUT TO:, we have a new scene heading, so transition is before new scene
    # Our parser: when it sees a transition, it flushes dialogue and adds transition to current scene
    # Then the next scene heading creates a new scene.
    # So scene1 should have dialogue and transition
    assert any(isinstance(b, Transition) for b in scene1.blocks)


def test_parse_character_with_direction(parser: FountainParser, tmp_path: Path) -> None:
    """Test that character names with parentheticals are cleaned."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN (O.S.)
Hello from off-screen.

MARY (V.O.)
Narration.
"""
    )
    script = parser.parse(script_file)

    characters = script.characters
    assert "JOHN" in characters
    assert "MARY" in characters
    # The (O.S.) and (V.O.) should be stripped
    for scene in script.scenes:
        for block in scene.blocks:
            if isinstance(block, Dialogue):
                assert block.character in {"JOHN", "MARY"}
                assert "(" not in block.character


def test_parse_empty_and_whitespace(parser: FountainParser, tmp_path: Path) -> None:
    """Test handling of empty lines and whitespace."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """
INT. ROOM - DAY

JOHN
Hello.




MARY
Hi.
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 1
    scene = script.scenes[0]
    assert len(scene.blocks) == 2
    assert all(isinstance(b, Dialogue) for b in scene.blocks)


def test_parse_long_dialogue_with_continuation(
    parser: FountainParser, tmp_path: Path
) -> None:
    """Test that multi-line dialogue is combined."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN
This is a long line that continues
on the next line and maybe even
a third line.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    dialogue = scene.blocks[0]
    assert isinstance(dialogue, Dialogue)
    assert (
        dialogue.content
        == "This is a long line that continues\non the next line and maybe even\na third line."
    )


def test_parse_scene_heading_variations(parser: FountainParser, tmp_path: Path) -> None:
    """Test different scene heading formats."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. HOUSE - DAY

EXT. PARK - NIGHT

.SCENE 1: THE BEGINNING
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 3
    assert script.scenes[0].heading.location == "INT. HOUSE"
    assert script.scenes[0].heading.time == "DAY"
    assert script.scenes[1].heading.location == "EXT. PARK"
    assert script.scenes[1].heading.time == "NIGHT"
    # Forced scene heading: dot removed, content is the whole line after dot
    assert script.scenes[2].heading.content == "SCENE 1: THE BEGINNING"
    assert script.scenes[2].heading.location == "SCENE 1: THE BEGINNING"
    assert script.scenes[2].heading.time is None


def test_parse_mixed_content(parser: FountainParser, tmp_path: Path) -> None:
    """Test a realistic mix of elements."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """FADE IN:

INT. COFFEE SHOP - DAY

A bustling coffee shop.

SARAH
(early 30s, tired)
Another day, another dollar.

JOHN
(smiling)
You're optimistic today.

SARAH
(sipping coffee)
Well, the coffee is good.

CUT TO:

EXT. STREET - DAY

John follows Sarah out.

JOHN
Hey, wait up!

SARAH
(without looking back)
I can't do this anymore.

FADE OUT.
"""
    )
    script = parser.parse(script_file)

    # Should have multiple scenes
    assert len(script.scenes) >= 2
    # Check characters
    assert "SARAH" in script.characters
    assert "JOHN" in script.characters
    # Check that parentheticals are captured
    for scene in script.scenes:
        for block in scene.blocks:
            if isinstance(block, Dialogue):
                if block.character == "SARAH":
                    if "early 30s, tired" in block.content:
                        # First line of Sarah has parenthetical
                        assert any(
                            p.text == "early 30s, tired" for p in block.parentheticals
                        )


def test_forced_scene_heading(parser: FountainParser, tmp_path: Path) -> None:
    """Test forced scene heading with leading dot."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. HOUSE - DAY

.SNIPER SCOPE POV

From what seems like only INCHES AWAY.
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 2
    # Second scene heading should have content without dot
    assert script.scenes[1].heading.content == "SNIPER SCOPE POV"
    assert script.scenes[1].heading.location == "SNIPER SCOPE POV"
    assert script.scenes[1].heading.time is None


def test_forced_transition(parser: FountainParser, tmp_path: Path) -> None:
    """Test forced transition with leading >."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN
Hello.

>Burn to White.

EXT. HELL - NIGHT
"""
    )
    script = parser.parse(script_file)

    assert len(script.scenes) == 2
    # First scene should contain a transition
    scene1 = script.scenes[0]
    transitions = [b for b in scene1.blocks if isinstance(b, Transition)]
    assert len(transitions) == 1
    assert transitions[0].content == "Burn to White."


def test_forced_character(parser: FountainParser, tmp_path: Path) -> None:
    """Test forced character with leading @."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

@McCLANE
Yippie ki-yay!

"""
    )
    script = parser.parse(script_file)

    assert "McCLANE" in script.characters
    scene = script.scenes[0]
    dialogue = scene.blocks[0]
    assert isinstance(dialogue, Dialogue)
    assert dialogue.character == "McCLANE"
    assert dialogue.content == "Yippie ki-yay!"


def test_markdown_emphasized_character(parser: FountainParser, tmp_path: Path) -> None:
    """Test that bold Markdown character cues are parsed as dialogue."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. CONTROL ROOM - DAY

**AUTOMATED VOICE**
(OVER SPEAKERS)
_Tri-tone alert._
This is an Earthquake Early Warning.
"""
    )

    script = parser.parse(script_file)

    assert script.characters == {"AUTOMATED VOICE"}
    dialogue = script.scenes[0].blocks[0]
    assert isinstance(dialogue, Dialogue)
    assert dialogue.character == "AUTOMATED VOICE"
    assert dialogue.content == "_Tri-tone alert._\nThis is an Earthquake Early Warning."
    assert dialogue.parentheticals[0].text == "OVER SPEAKERS"


def test_title_page_metadata_before_forced_scene(
    parser: FountainParser, tmp_path: Path
) -> None:
    """Test that Fountain title-page metadata does not become a render scene."""
    script_file = tmp_path / "fission.fountain"
    script_file.write_text(
        """Title: FISSION EPISODE 101
Credit: written by
Author: Jonathan Golob
Copyright: (c) 2026 Jonathan Golob
Notes:
The world's most dangerous technology. A disaster.
About the Author:
Jonathan Golob lives in Seattle.
Revision: 2026-03-24

# ACT I

.INT. FUKUSHIMA DAIICHI - UNITS 1 & 2 CENTRAL CONTROL ROOM - DAY

CLAIRE
Welcome to the central control room.

**AUTOMATED VOICE**
(OVER SPEAKERS)
_Tri-tone alert._
This is an Earthquake Early Warning.
"""
    )

    script = parser.parse(script_file)

    assert len(script.scenes) == 1
    assert script.scenes[0].heading.content == (
        "INT. FUKUSHIMA DAIICHI - UNITS 1 & 2 CENTRAL CONTROL ROOM - DAY"
    )
    assert script.characters == {"CLAIRE", "AUTOMATED VOICE"}

    dialogue_blocks = [
        block for block in script.scenes[0].blocks if isinstance(block, Dialogue)
    ]
    assert [block.character for block in dialogue_blocks] == [
        "CLAIRE",
        "AUTOMATED VOICE",
    ]


def test_forced_action(parser: FountainParser, tmp_path: Path) -> None:
    """Test forced action with leading !."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. CASINO - NIGHT

!SCANNING THE AISLES…
Where is that pit boss?
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # Should have two action blocks
    actions = [b for b in scene.blocks if isinstance(b, Action)]
    assert len(actions) == 2
    assert actions[0].content == "SCANNING THE AISLES…"
    assert actions[1].content == "Where is that pit boss?"


def test_boneyard_skipped(parser: FountainParser, tmp_path: Path) -> None:
    """Test that boneyard comments are completely ignored."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

This is visible.

/* This is a boneyard
   multiple lines
   still ignored */

This is also visible.

/* Single line boneyard */

End of scene.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # Only the visible action lines should be present
    actions = [b for b in scene.blocks if isinstance(b, Action)]
    # Should have 3 action blocks: "This is visible.", "This is also visible.", "End of scene."
    assert len(actions) == 3
    contents = [a.content for a in actions]
    assert "This is visible." in contents
    assert "This is also visible." in contents
    assert "End of scene." in contents


def test_section_and_synopsis_ignored(parser: FountainParser, tmp_path: Path) -> None:
    """Test that sections and synopses are ignored."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """# Act I

= This act sets up the story.

INT. HOUSE - DAY

JOHN
Hello.

## Sequence

= John introduces himself.

MARY
Hi.
"""
    )
    script = parser.parse(script_file)

    # Should have one scene with two dialogue blocks
    assert len(script.scenes) == 1
    scene = script.scenes[0]
    # Should have two dialogue blocks, no sections or synopses
    assert all(isinstance(b, Dialogue) for b in scene.blocks)
    assert len(scene.blocks) == 2


def test_whole_line_note_ignored(parser: FountainParser, tmp_path: Path) -> None:
    """Test that whole-line notes are ignored."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

[[This is a note]]

JOHN
Hello.

[[Another note]]

MARY
Hi.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # Should have two dialogue blocks, notes are ignored
    assert all(isinstance(b, Dialogue) for b in scene.blocks)
    assert len(scene.blocks) == 2
    john = scene.blocks[0]
    mary = scene.blocks[1]
    assert isinstance(john, Dialogue)
    assert isinstance(mary, Dialogue)
    assert john.character == "JOHN"
    assert mary.character == "MARY"


def test_inline_note_stripped(parser: FountainParser, tmp_path: Path) -> None:
    """Test that inline notes are stripped from dialogue."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN
Hello[[note1]], Mary.

MARY
Hi[[note2]].
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    assert len(scene.blocks) == 2
    john_dialogue = scene.blocks[0]
    mary_dialogue = scene.blocks[1]
    assert "note" not in john_dialogue.content
    assert john_dialogue.content == "Hello, Mary."
    assert "note" not in mary_dialogue.content
    assert mary_dialogue.content == "Hi."


def test_lyrics_as_action(parser: FountainParser, tmp_path: Path) -> None:
    """Test that lyrics (starting with ~) are treated as action with tilde removed."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. STAGE - DAY

~Willy Wonka! Willy Wonka! The amazing chocolatier!

NARRATOR
Let's sing along.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # First block should be action (lyric) without tilde
    action = scene.blocks[0]
    assert isinstance(action, Action)
    assert action.content == "Willy Wonka! Willy Wonka! The amazing chocolatier!"
    # Second block is dialogue
    dialogue = scene.blocks[1]
    assert isinstance(dialogue, Dialogue)
    assert dialogue.character == "NARRATOR"


def test_centered_text_as_action(parser: FountainParser, tmp_path: Path) -> None:
    """Test that centered text (>...<) is treated as action with markers removed."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. THEATER - NIGHT

> THE END <

Curtains close.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # First block should be action with content "THE END"
    action = scene.blocks[0]
    assert isinstance(action, Action)
    assert action.content == "THE END"
    # Second block is action
    action2 = scene.blocks[1]
    assert isinstance(action2, Action)
    assert action2.content == "Curtains close."


def test_page_break_ignored(parser: FountainParser, tmp_path: Path) -> None:
    """Test that page breaks (===) are ignored."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN
Hello.

===

MARY
Hi.

===

JOHN
Again.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # Should have three dialogue blocks, page breaks ignored
    assert all(isinstance(b, Dialogue) for b in scene.blocks)
    assert len(scene.blocks) == 3
    john1 = scene.blocks[0]
    mary = scene.blocks[1]
    john2 = scene.blocks[2]
    assert isinstance(john1, Dialogue)
    assert isinstance(mary, Dialogue)
    assert isinstance(john2, Dialogue)
    assert john1.character == "JOHN"
    assert mary.character == "MARY"
    assert john2.character == "JOHN"


def test_dual_dialogue_caret(parser: FountainParser, tmp_path: Path) -> None:
    """Test that dual dialogue caret (^) is stripped from character name."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

BRICK
Screw retirement.

STEEL ^
Screw retirement.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    assert len(scene.blocks) == 2
    # Both should be dialogue
    assert all(isinstance(b, Dialogue) for b in scene.blocks)
    brick = scene.blocks[0]
    steel = scene.blocks[1]
    assert isinstance(brick, Dialogue)
    assert isinstance(steel, Dialogue)
    assert brick.character == "BRICK"
    assert steel.character == "STEEL"  # caret stripped
    # Note: dual dialogue simultaneous mixing not implemented; they are sequential.


def test_orphan_parenthetical(parser: FountainParser, tmp_path: Path) -> None:
    """Test that a parenthetical without a character is treated as action."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

(sighs)

JOHN
Hello.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # First block should be action (the orphan parenthetical)
    assert isinstance(scene.blocks[0], Action)
    assert scene.blocks[0].content == "(sighs)"
    # Second block is dialogue
    assert isinstance(scene.blocks[1], Dialogue)
    assert scene.blocks[1].character == "JOHN"


def test_long_all_caps_becomes_action(parser: FountainParser, tmp_path: Path) -> None:
    """Test that a long all-caps line (4+ words) is treated as action, not character."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

THIS IS A VERY LONG ALL CAPS LINE THAT SHOULD BE ACTION

JOHN
Hello.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # First block should be action
    assert isinstance(scene.blocks[0], Action)
    assert (
        scene.blocks[0].content
        == "THIS IS A VERY LONG ALL CAPS LINE THAT SHOULD BE ACTION"
    )
    # Second block is dialogue
    assert isinstance(scene.blocks[1], Dialogue)
    assert scene.blocks[1].character == "JOHN"


def test_action_preserves_whitespace(parser: FountainParser, tmp_path: Path) -> None:
    """Test that leading whitespace in action lines is preserved."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

    Indented action line.
Not indented.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    assert len(scene.blocks) == 2
    assert isinstance(scene.blocks[0], Action)
    # Leading spaces should be preserved (exact content)
    assert scene.blocks[0].content == "    Indented action line."
    assert scene.blocks[1].content == "Not indented."


def test_scene_without_blank_becomes_action(
    parser: FountainParser, tmp_path: Path
) -> None:
    """Test that a scene heading without preceding blank line is treated as action."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY
EXT. GARDEN - NIGHT

JOHN
Hello.
"""
    )
    script = parser.parse(script_file)

    # Only one scene (first line), second line becomes action within that scene
    assert len(script.scenes) == 1
    scene = script.scenes[0]
    # First block is action (the second line)
    assert isinstance(scene.blocks[0], Action)
    assert scene.blocks[0].content == "EXT. GARDEN - NIGHT"
    # Second block is dialogue
    assert isinstance(scene.blocks[1], Dialogue)


def test_transition_without_blank_becomes_action(
    parser: FountainParser, tmp_path: Path
) -> None:
    """Test that a transition without preceding blank line is treated as action."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN
Hello.
CUT TO:
EXT. STREET - DAY
"""
    )
    script = parser.parse(script_file)

    # Should have one scene with dialogue and then action (CUT TO:) and then maybe new scene? Actually after CUT TO: without blank, it's action, then next line is scene heading? But next line "EXT. STREET - DAY" is on the next line, which is not preceded by blank (since CUT TO: line was not blank). So it would be action as well? Let's see: after dialogue, we have line "CUT TO:" - not blank, prev_line_blank is False (since dialogue line set it false). So transition check requires prev_line_blank True, so it fails, becomes action. Then next line "EXT. STREET - DAY" is not blank, prev_line_blank is False (from previous action), so scene check fails, becomes action. So all become action in same scene. That's expected.
    scene = script.scenes[0]
    actions = [b for b in scene.blocks if isinstance(b, Action)]
    assert len(actions) >= 2
    # Check that CUT TO: is an action
    assert any(b.content == "CUT TO:" for b in actions)


def test_character_without_blank_becomes_action_or_continuation(
    parser: FountainParser, tmp_path: Path
) -> None:
    """Test character line without preceding blank: if not in dialogue, becomes action; if in dialogue, continues."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

JOHN
Hello
MARY
Hi.
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # Since there is no blank line between "Hello" and "MARY", MARY becomes part of JOHN's dialogue.
    # This tests the continuation behavior.
    assert len(scene.blocks) == 1
    dialogue = scene.blocks[0]
    assert isinstance(dialogue, Dialogue)
    assert dialogue.character == "JOHN"
    assert dialogue.content == "Hello\nMARY\nHi."


def test_empty_file(parser: FountainParser, tmp_path: Path) -> None:
    """Test parsing an empty file."""
    script_file = tmp_path / "empty.fountain"
    script_file.write_text("")
    script = parser.parse(script_file)
    assert script.title == "empty"
    assert len(script.scenes) == 0
    assert len(script.characters) == 0


def test_only_blank_lines(parser: FountainParser, tmp_path: Path) -> None:
    """Test file with only blank lines."""
    script_file = tmp_path / "blank.fountain"
    script_file.write_text("\n\n\n")
    script = parser.parse(script_file)
    assert len(script.scenes) == 0
    assert len(script.characters) == 0


def test_inline_note_in_action(parser: FountainParser, tmp_path: Path) -> None:
    """Test that inline notes are stripped from action lines."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

This is action[[note]].

JOHN
Hello[[note2]].
"""
    )
    script = parser.parse(script_file)

    scene = script.scenes[0]
    # First block is action
    action = scene.blocks[0]
    assert isinstance(action, Action)
    assert action.content == "This is action."
    # Dialogue also stripped
    dialogue = scene.blocks[1]
    assert isinstance(dialogue, Dialogue)
    assert dialogue.content == "Hello."


def test_unclosed_boneyard(parser: FountainParser, tmp_path: Path) -> None:
    """Test that unclosed boneyard ignores everything until EOF."""
    script_file = tmp_path / "test.fountain"
    script_file.write_text(
        """INT. ROOM - DAY

/* This boneyard never closes

JOHN
Hello.

MARY
Hi.
"""
    )
    script = parser.parse(script_file)

    # Only the first action and maybe? Actually after "INT. ROOM - DAY" blank line, then we see "/*", we enter boneyard and skip all subsequent lines. So the scene should have no blocks? The scene heading is added, but then boneyard skips everything else. So scene would have no blocks? That's okay.
    assert len(script.scenes) == 1
    scene = script.scenes[0]
    # No blocks should be added after the scene heading because all skipped
    assert len(scene.blocks) == 0
