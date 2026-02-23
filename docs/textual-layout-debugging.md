# Debugging Textual Layout Issues

Lessons learned from a painful debugging session replacing a Select dropdown
with a FuzzySelect widget in modal dialogs.

## The Core Problem

A modal dialog had a large gap between a widget and the fields below it. Hours
were wasted guessing at CSS values (`max-height: 80%`, `70%`, `60%`, `height: 1fr`, `height: auto`) without understanding what was actually happening.

## What You Should Do Instead

### 1. Measure Before You Change

Use a test script to print the actual rendered regions of every widget in the
dialog. This tells you exactly what is taking up space and where the gap is:

```python
import sqlite3, asyncio
from pyre.db import SCHEMA
from pyre.ui.app import PyreApp

con = sqlite3.connect(':memory:')
con.row_factory = sqlite3.Row
con.executescript(SCHEMA)
con.execute("INSERT INTO accounts (id, name, type) VALUES ('chk', 'Checking', 'asset')")
con.commit()

app = PyreApp(con=con)

async def check():
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.press('e')  # open the screen
        await pilot.pause()
        screen = app.screen
        dialog = screen.query_one('#rs-dialog')
        print(f'Dialog region: {dialog.region}')
        for child in dialog.children:
            r = child.region
            print(f'  {child.__class__.__name__} id={child.id} y={r.y} h={r.height} display={child.display}')

asyncio.run(check())
```

This immediately shows you which widget is creating the gap.

### 2. Check Widget Default CSS

Textual widgets have built-in DEFAULT_CSS that you might not be aware of:

```python
from textual.containers import Vertical, VerticalGroup
from textual.widgets import OptionList, Static
print(Vertical.DEFAULT_CSS)
print(OptionList.DEFAULT_CSS)
```

Key defaults to know:

- `Vertical`: `height: 1fr` (fills parent)
- `VerticalGroup`: `height: auto` (shrinks to content)
- `OptionList`: `height: auto; max-height: 100%`
- `Static`: `height: auto`
- `ModalScreen`: `layout: vertical; overflow-y: auto`

Your component CSS (`DEFAULT_CSS` on your class) overrides widget defaults,
so `#my-dialog { height: auto; }` will override `Vertical`'s `1fr`. You do
NOT need to switch to `VerticalGroup` just for this -- either works identically
when you set the CSS explicitly.

### 3. Hidden Empty Widgets Still Take Space

This was the actual root cause. Two empty Labels with `margin-top: 1` were
sitting between the account picker and the date fields:

```python
yield Label("", id="rs-last-info", classes="rs-info")       # empty, h=1
yield Label("", id="rs-beginning-bal", classes="rs-field-label")  # empty, h=1 + margin-top=1
```

These invisible-but-present widgets created a ~4 row gap. The fix was trivial:

```python
# Hide empty labels on mount
self.query_one("#rs-last-info").display = False
self.query_one("#rs-beginning-bal").display = False

# Show them when they have content
def on_account_picked(self, event):
    self.query_one("#rs-last-info").display = True
    self.query_one("#rs-beginning-bal").display = True
    self._update_account_info(event.value)
```

### 4. Stop Guessing at max-height

If you find yourself trying `max-height: 80%`, then `70%`, then `60%`, you
are not debugging -- you are guessing. Stop. Run the measurement script above.
Find out what is actually taking the space. The answer is almost never "the
dialog needs a different max-height".

Common actual causes of unexpected gaps:

- Empty widgets with margins still occupying space
- `height: 1fr` on a child expanding to fill its parent
- OptionList `max-height: 100%` resolving against a full-screen ancestor
- Margins/padding you forgot about on intermediate containers

### 5. Fixed Height vs Auto for OptionList

If you want an OptionList that does NOT resize as the user filters (stable UI):
use `height: 12` (fixed). The list will always be 12 rows and scroll internally.

If you want it to shrink to content: use `height: auto` with `max-height: 12`.
But this means the dialog resizes as the user types, which looks bad.

Pick one. Users strongly prefer a stable, non-resizing layout.
