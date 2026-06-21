"""Docstrings for desktop tools — actions executed on the user's own computer.

These descriptions are embedded into ChromaDB for tool discovery, so they must
make clear the action happens on the user's machine via the GAIA desktop app.
"""

TAKE_SCREENSHOT = """
Look at the user's screen. Captures a screenshot of the user's computer display
via the GAIA desktop app and returns a detailed description of what is visible.

Use this whenever the user references what they are looking at ("what's on my
screen?", "help me with this error", "summarize this page I have open") or when
you need visual context from their computer.

Args:
    query (str): What to look for or describe. Be specific — e.g. "the error
        dialog text", "what app is focused and what is it showing".

Returns:
    str: A detailed description of the screen contents, focused on the query.
"""

READ_CLIPBOARD = """
Read the current text contents of the user's clipboard via the GAIA desktop app.

Use when the user says things like "what's on my clipboard", "use what I just
copied", or asks you to work with copied text.

Returns:
    str: The clipboard text, or a message if the clipboard is empty.
"""

WRITE_CLIPBOARD = """
Copy text to the user's clipboard via the GAIA desktop app.

Use when the user asks you to copy something for them ("copy that to my
clipboard", "put this on my clipboard so I can paste it").

Args:
    text (str): The exact text to place on the clipboard.

Returns:
    str: Confirmation that the text was copied.
"""

OPEN_APP = """
Open (or focus) an application on the user's computer via the GAIA desktop app.

Use when the user asks to launch or switch to an app ("open Safari", "launch
Spotify").

Args:
    app_name (str): The application's name as it appears on the user's system,
        e.g. "Safari", "Notes", "Visual Studio Code".

Returns:
    str: Confirmation that the app was opened, or an error if it was not found.
"""

OPEN_URL = """
Open a URL in the user's default browser via the GAIA desktop app.

Use when the user asks to open a website or when you want to hand off a page
for the user to view ("open the booking page", "take me to that article").
Only http(s) URLs are allowed.

Args:
    url (str): The full http(s) URL to open.

Returns:
    str: Confirmation that the URL was opened.
"""

LIST_WINDOWS = """
List the windows currently open on the user's computer via the GAIA desktop
app, including the owning application and window title.

Use to understand what the user is working on or to find the right app/window
before describing the screen.

Returns:
    str: A list of open windows with their application names and titles.
"""
