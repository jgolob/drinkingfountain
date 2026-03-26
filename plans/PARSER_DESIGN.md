# Fountain Parser Design

## 1. Overview

This document details the design of the Fountain parser for the Drinking Fountain project. The parser converts Fountain-format plain text files into a structured `Script` object containing scenes, dialogue, actions, and other elements.

The design follows the official Fountain specification (https://fountain.io/) with a focus on handling the core elements needed for audioplay generation.

## 2. Core Elements

### 2.1 Scene Heading

**Definition**: A line that marks the beginning of a new scene.

**Rules**:
- Must be preceded by at least one blank line (or be the first line of the file).
- Must begin with one of the following prefixes (case-insensitive):
  - `INT.` or `INT` (interior)
  - `EXT.` or `EXT` (exterior)
  - `INT/EXT.` or `INT/EXT`
  - `EXT/INT.` or `EXT/INT`
  - `EST.` (establishing)
  - `I/E.` (interior/exterior)
- Alternatively, can be **forced** by starting the line with a single period `.` (the period is removed in output).
- The content typically includes location and time of day (e.g., `INT. HOUSE - DAY`).
- The parser should split the heading into `location` and `time` when possible.

**Implementation**:
- Check `prev_line_blank == True`.
- Match against `SCENE_PATTERN` (prefixes) or `FORCED_SCENE_PATTERN` (leading `.`).
- Remove leading `.` if forced.
- Parse location/time by splitting on ` - ` or ` -`.
- Create `SceneHeading` block and start a new `Scene`.

### 2.2 Character

**Definition**: The name of a character speaking dialogue.

**Rules**:
- Must be preceded by at least one blank line
- Must be entirely in uppercase letters, numbers, and spaces (at least one alphabetical character).
- May include a **character extension** (parenthetical) on the same line, e.g., `MOM (O.S.)` or `JOHN (on the radio)`. These are stripped from the character name but may be used later for voice direction.
- Can be **forced** by preceding the line with `@` (allows mixed case).
- Character names are limited to 1-3 words (heuristic to avoid misclassifying long action lines as characters).

**Implementation**:
- Check `prev_line_blank == True`.
- Match `CHARACTER_PATTERN` (all caps) or `FORCED_CHARACTER_PATTERN` (starts with `@`).
- Strip any trailing parenthetical: `re.sub(r"\s*\(.*?\)\s*$", "", name)`.
- If forced, remove leading `@` and preserve case.
- Set `current_character` and reset dialogue state.
- Do **not** create a `Character` block; character names are part of `Dialogue` blocks.

### 2.3 Dialogue

**Definition**: The spoken lines of a character.

**Rules**:
- Dialogue follows a `Character` line directly (no blank line between).
- May span multiple lines; each line is a separate paragraph but combined into one `Dialogue` block.
- May contain **parentheticals** on separate lines within the dialogue.
- Empty lines within dialogue are not allowed (they would end the dialogue block).

**Implementation**:
- After a `Character` is recognized, subsequent non-blank lines that are not parentheticals are collected into `dialogue_lines`.
- When a blank line or a new structural block (scene, transition, character) is encountered, the dialogue is flushed into a `Dialogue` block.
- The `Dialogue` block includes the character name, combined content (joined with ` `), and any collected `parentheticals`.

### 2.4 Parenthetical

**Definition**: A direction for delivery, placed in parentheses.

**Rules**:
- Must be on a line by itself, entirely in parentheses: `(text)`.
- Can appear:
  - After a `Character` line and before the dialogue lines.
  - Between dialogue lines (to indicate a pause or action mid-speech).
- Parentheticals are attached to the current `Dialogue` block, not separate blocks.

**Implementation**:
- When `current_character` is active and a line matches `PARENTHETICAL_PATTERN`, create a `Parenthetical` block and add to `parentheticals` list.
- The text inside parentheses is stored (without the parentheses).
- When dialogue is flushed, the `parentheticals` list is attached to the `Dialogue` block.

### 2.5 Transition

**Definition**: A shot transition like `CUT TO:` or `FADE OUT.`

**Rules**:
- Must be preceded by at least one blank line.
- Must be entirely in uppercase.
- Must end with `TO:`
- Can be **forced** by preceding the line with `>` (the `>` is removed).
- Must be followed by a blank line (but we may not know until we read ahead; we'll accept it without requiring the following blank line for leniency).

**Implementation**:
- Check `prev_line_blank == True`.
- Match `TRANSITION_PATTERN` (ends with `TO:`) or `FORCED_TRANSITION_PATTERN` (starts with `>` and ends with `<`? Actually forced transition uses `>` at start, not necessarily `<` at end. The spec says: "force any line to be a transition by beginning it with a greater-than symbol >." So pattern: `^>.*`. We'll use that.
- Remove leading `>` if forced.
- Create `Transition` block and add to current scene.
- Flush any pending dialogue first.

### 2.6 Action

**Definition**: Any paragraph that doesn't meet the criteria for another element.

**Rules**:
- Action includes descriptions, character movements, scene settings, etc.
- Can be multiple lines; blank lines within action are preserved as empty lines in the output.
- Can be **forced** by preceding the line with `!` (useful when an action line is all caps and would otherwise be interpreted as character).
- Leading whitespace (tabs/spaces) is preserved in action (for indentation).
- Underlining, italics, bold can be added using Fountain's emphasis syntax (underscores, asterisks) – we will preserve the raw text; TTS can ignore or interpret later.

**Implementation**:
- If no other element matches and we are not in a dialogue context, treat as `Action`.
- For forced action (`!` prefix), strip the `!` and treat as action.
- Preserve original line content (including internal whitespace).
- Multiple consecutive action lines can be combined into one block with line breaks. In practice, consecutive non-blank lines that are action are often treated as a single paragraph with manual line breaks. However, for simplicity, we can treat each action line as a separate `Action` block. The TTS can read each action block as a separate narration segment.
- After an action block, `current_character` remains None.

### 2.7 Dual Dialogue

**Definition**: Two characters speaking simultaneously.

**Rules**:
- Indicated by placing a caret `^` at the end of the second character's line.
- The two characters' dialogue should be mixed to play at the same time.

**Implementation**:
- **Postponed to a future enhancement**. For MVP, we treat the `^` as part of the character name (which gets stripped) and the dialogue as sequential. This is acceptable for early development.

### 2.8 Title Page

**Definition**: Optional metadata at the start of the script.

**Rules**:
- Lines of the form `Key: Value` at the beginning, before the first blank line.
- Keys can include spaces (e.g., `Draft date:`).
- Values can be on the same line or indented on following lines (3+ spaces or a tab).
- Multiple values for the same key are allowed.

**Implementation**:
- **Postponed**. For MVP, we treat them as action blocks.

### 2.9 Other Elements (Deferred)

- **Lyrics** (`~` prefix) – treat as action or preserve marker.
- **Centered Text** (`>...<`) – treat as action, preserve markers.
- **Emphasis** (`*italic*`, `**bold**`, `_underline_`) – preserve raw text; TTS may ignore.
- **Notes** (`[[note]]`) – could be stripped or kept as action.
- **Boneyard** (`/* ... */`) – should be completely ignored.
- **Sections** (`# heading`) – ignored.
- **Synopses** (`= text`) – ignored.
- **Page Breaks** (`===`) – could be treated as transition or ignored.

For MVP, these will be handled as follows:
- Boneyard: skip entirely.
- Others: treat as action (preserving original text) or strip if appropriate.

## 3. State Machine

The parser operates as a line-by-line state machine with the following state variables:

- `current_scene: Optional[Scene]` – the scene currently being built.
- `current_character: Optional[str]` – the character whose dialogue is being collected, or `None` if not in dialogue.
- `dialogue_lines: List[str]` – accumulated lines of the current dialogue block.
- `parentheticals: List[Parenthetical]` – parentheticals collected for the current dialogue block.
- `prev_line_blank: bool` – whether the previous line was blank. Important for detecting elements that require a preceding blank line (scene, character, transition).

**State transitions**:

1. **Start / after blank line** (`prev_line_blank = True`):
   - If line matches scene pattern → create `SceneHeading`, new scene.
   - Else if line matches transition pattern → create `Transition` in current scene.
   - Else if line matches character pattern → set `current_character`, start dialogue collection.
   - Else → treat as `Action` (or forced action).

2. **During dialogue** (`current_character` is not `None`):
   - Blank line → flush dialogue, clear `current_character`.
   - Parenthetical line → add to `parentheticals`.
   - Any other non-blank line → append to `dialogue_lines`.
   - Structural block (scene, transition) → flush dialogue first, then handle the block.

3. **After action / between blocks** (`current_character = None`, `prev_line_blank = False`):
   - Non-blank line that is not a special block → `Action`.
   - Blank line → set `prev_line_blank = True` (but don't flush anything because action blocks are independent).

**Flushing dialogue**:
- Create a `Dialogue` block with:
  - `character` = `current_character`
  - `content` = `"\n".join(dialogue_lines)`
  - `parentheticals` = copy of collected parentheticals
- Append to `current_scene` (creating a default scene if necessary).
- Reset `dialogue_lines` and `parentheticals` (but keep `current_character` until a blank line or new block? Actually, after flushing, we keep `current_character` if we are still in the same dialogue block? Wait: we flush when we encounter a blank line or a new structural block. After flushing, we should set `current_character = None` because the dialogue block is complete. However, if we encounter another dialogue line (non-blank) after flushing due to a structural block? That would be a new dialogue block? Actually, if we flush because we saw a scene heading, that scene heading is a new block, and after that we would not be in dialogue. So it's fine to clear `current_character`. If we flush because of a blank line, that ends the dialogue, so `current_character` should be cleared. So after `_flush_dialogue`, set `current_character = None`.

But careful: In the state machine, when we are in dialogue and see a blank line, we flush and then `continue` (skip further processing). That sets `current_character = None`. Good.

When we are in dialogue and see a structural block (like scene heading), we flush, then handle the block, and in handling we will also set `current_character = None` (or it's already None after flush). So consistent.

## 4. Algorithm (Pseudocode)

```
script = Script(title)
current_scene = None
current_character = None
dialogue_lines = []
parentheticals = []
prev_line_blank = True

for each line in file:
    line_number += 1
    is_blank = line.strip() == ""

    if is_blank:
        prev_line_blank = True
        if current_character and dialogue_lines:
            flush_dialogue()
            current_character = None
        continue

    stripped = line.strip()
    block = None

    # 1. Check for scene heading (requires prev_line_blank)
    if prev_line_blank and (matches_scene_pattern(stripped) or forced_scene):
        parse location/time
        block = SceneHeading(...)
        flush_dialogue_if_needed()
        current_scene = script.add_block(block, current_scene)
        prev_line_blank = False
        continue

    # 2. Check for transition (requires prev_line_blank)
    if prev_line_blank and (matches_transition_pattern(stripped) or forced_transition):
        block = Transition(...)
        flush_dialogue_if_needed()
        if current_scene is None: create default scene
        current_scene.blocks.append(block)
        prev_line_blank = False
        continue

    # 3. Check for character (requires prev_line_blank)
    if prev_line_blank and (matches_character_pattern(stripped) or forced_character):
        name = clean_character_name(stripped)
        flush_dialogue_if_needed()
        current_character = name
        dialogue_lines = []
        parentheticals = []
        prev_line_blank = False
        continue

    # 4. If in dialogue context, check for parenthetical
    if current_character is not None and matches_parenthetical_pattern(stripped):
        parentheticals.append(Parenthetical(..., stripped.strip("()")))
        prev_line_blank = False
        continue

    # 5. If in dialogue context, any other line is dialogue content
    if current_character is not None:
        dialogue_lines.append(stripped)
        prev_line_blank = False
        continue

    # 6. Not in dialogue: this is an Action (or forced action)
    if forced_action_pattern(stripped):
        content = stripped[1:].strip()
        block = Action(..., content)
    else:
        block = Action(..., stripped)

    if current_scene is None:
        create default scene heading and add to script
    current_scene.blocks.append(block)
    # Action does not start dialogue
    current_character = None
    prev_line_blank = False

# After loop: flush any remaining dialogue
if current_character and dialogue_lines:
    flush_dialogue()

return script
```

## 5. Edge Cases and Error Handling

- **Orphan dialogue** (dialogue without a character): treated as action.
- **Orphan parenthetical** (parenthetical without a character): treated as action.
- **Character without dialogue** (character followed by blank line): the character is ignored (no dialogue block created). This is acceptable; the character will still be added to `script.characters` only when dialogue is flushed. Actually, we add characters to `script.characters` during `add_block` when a `Dialogue` is added. So a character with no dialogue won't appear in the character set. That's fine.
- **Long all-caps lines** that are not characters: if they exceed 3 words, they are not classified as characters, so they become action. This prevents misinterpreting long action lines as characters.
- **Scene heading without blank line before**: will be treated as action. This is a parsing error but we choose to be lenient.
- **Transition without blank line before**: treated as action.
- **Character without blank line before**: treated as action (or dialogue if already in dialogue? Actually, if not blank before, we are not in the `prev_line_blank` state, so it would fall through to action or dialogue continuation. If we are already in dialogue, a line that looks like a character but without blank line will be treated as dialogue content (since `current_character` is set). That's correct: it continues the current character's dialogue.
- **Multiple consecutive blank lines**: each sets `prev_line_blank = True`; no effect.
- **Empty file**: returns empty script.
- **File with only title page**: treated as action blocks; no scenes.

## 6. Data Model Integration

The parser constructs the `Script` object defined in `script.py`:

- `Script.title` is set from the file stem.
- `Script.scenes` is built by calling `script.add_block(block, current_scene)`.
  - When a `SceneHeading` is added, a new `Scene` is created and appended to `scenes`, and `current_scene` is updated.
  - Other blocks are appended to `current_scene.blocks`.
- `Script.characters` is a set populated automatically when `Dialogue` blocks are added (via `add_block` method). The `add_block` method in `Script` adds character names to the set when encountering `Character` or `Dialogue` blocks. Actually, in our `Script.add_block`, we only add characters for `Character` and `Dialogue` when they are added directly. But in our parser, we don't add `Character` blocks; we only add `Dialogue` blocks. So we need to ensure that when we add a `Dialogue` block, the `Script.add_block` method adds the character to the set. In the `Script` class we wrote, the `add_block` method checks:
  ```python
  if isinstance(block, Character):
      self.characters.add(block.name)
  elif isinstance(block, Dialogue):
      self.characters.add(block.character)
  ```
  That's perfect. So we just need to make sure we call `script.add_block` for the `Dialogue` block (which we do in `_flush_dialogue`). Good.

## 7. Implementation Notes

- **Line numbers**: All blocks record the line number from the source file where they start. For `Dialogue`, we use the current `line_number` (which may be the blank line that triggered the flush, or the line of the block that caused the flush). To be more accurate, we could store the line number of the character line or first dialogue line. But it's not critical for MVP.
- **Parenthetical ordering**: Parentheticals are collected in order and attached to the dialogue block. The TTS engine can decide how to use them (e.g., insert pauses before certain lines).
- **Scene default**: If we encounter a block (action, dialogue, transition) before any scene heading, we create a default scene with location "UNKNOWN". This ensures all blocks belong to a scene.
- **Forced elements**: The forced syntaxes (`.`, `@`, `>`, `!`) are handled by stripping the prefix and treating the remainder as the respective element type.
- **Boneyard**: Not yet implemented; will be added as a pre-processing step or during line parsing (skip lines between `/*` and `*/`).
- **Dual dialogue**: Not yet implemented; the `^` character at end of character line will be ignored (treated as part of character name and stripped).

## 8. Testing Strategy

The parser will be unit tested with a variety of Fountain examples covering:
- Simple one-scene, one-character dialogue.
- Multiple scenes.
- Character with parentheticals.
- Mixed action and dialogue.
- Transitions.
- Scene heading variations (with/without time, forced).
- Edge cases: blank lines, long lines, orphan lines, empty file.

Tests will assert:
- Correct number of scenes.
- Correct block types and order.
- Character names extracted correctly.
- Dialogue content combined properly.
- Parentheticals attached to dialogue.
- Line numbers recorded.

## 9. Future Enhancements

- Implement boneyard skipping.
- Implement dual dialogue (simultaneous speech).
- Implement title page parsing.
- Implement emphasis, centered text, lyrics, sections, synopses (mostly ignored but could be preserved as metadata).
- Better error reporting (line numbers for malformed constructs).
- Support for more scene heading formats (e.g., `INT. HOUSE - DAY #1#` with scene numbers).

## 10. Summary

This design provides a clear, state-based approach to parsing Fountain scripts that respects the official specification while being robust to common variations. The implementation will be straightforward to code once the state machine and element detection are as described.
