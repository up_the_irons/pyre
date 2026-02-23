# Pyre

## Setup

Always activate the virtualenv before running any Python/pip commands:

```
. venv/bin/activate
```

## Textual TUI Gotchas

- **Rich markup in Labels**: `[A]` is parsed as a Rich style tag. Escape with `\[A]` to display literal brackets.
- **Dialog sizing**: Use `height: auto; max-height: 80%;` on modal dialog containers. `Vertical` defaults to `height: 1fr` (fills parent) and will clip content. (`VerticalGroup` defaults to `auto`.)
- **Select widget**: Use `Select.NULL` as the no-selection sentinel. Use `allow_blank=True` without setting an explicit value.
- **`Tree.select_node()`** posts a `Tree.NodeSelected` message. If you handle `NodeSelected` to dismiss, add a guard so programmatic selection (e.g. during search filtering) doesn't trigger dismissal.
- **Footer pollution**: Set `show=False` on bindings you don't want in the Footer.
- **Text wrapping in Labels**: Labels don't wrap by default. Use `Label("text", shrink=True)` to let text wrap within a fixed-width container. Without `shrink=True`, the Label insists on its full single-line width and text gets clipped.
- **Confirmation dialogs**: Use `Vertical` (not `VerticalGroup`) with a fixed `width` + `height: auto`. Use `shrink=True` on any Label whose text may vary in length.
- **Key bindings**: Always use `BINDINGS` + `action_*` methods for keyboard shortcuts. Never use `on_key()` for keys that should appear in the key bindings panel. Only use `on_key()` for dynamic/conditional key handling (e.g. number keys mapped at runtime, or keys conditional on specific widget focus state).

## Code Style

- **No unicode in comments**: Use plain ASCII in comments. No fancy dashes, arrows, or box-drawing characters in comments.
- **Never duplicate code**: If a function, dict, or constant already exists somewhere in the codebase, import and reuse it. Do not copy-paste it into a new location. Search before writing.

## Git Rules

- **NEVER use `git commit --amend`**. Always create a new commit. Amending can overwrite another agent's work.
