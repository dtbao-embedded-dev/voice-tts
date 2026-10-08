"""System tray icon: keeps Voice TTS reachable while no window is showing.

The desktop window hides here when it is minimized or closed, and
``serve --tray`` lives here with no window at all. Only "Thoát" ends the app.

pystray and Pillow are imported when an icon is actually made, so importing
this module costs nothing on a headless server.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import webbrowser
from typing import Callable

log = logging.getLogger("voice-tts.tray")

TITLE = "Voice TTS"


def copy_text(text: str) -> bool:
    """Put ``text`` on the clipboard with whatever the platform ships."""
    if sys.platform == "win32":
        cmd = ["clip"]
    elif sys.platform == "darwin":
        cmd = ["pbcopy"]
    else:
        cmd = next((c for c in (["wl-copy"], ["xclip", "-selection", "clipboard"],
                                ["xsel", "--clipboard", "--input"]) if shutil.which(c[0])), None)
    if cmd is None:
        return False
    try:
        subprocess.run(cmd, input=text.encode(), check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class Tray:
    """One tray icon and its menu.

    ``url`` is what the browser opens (loopback, token included); ``lan_url``
    is what "Sao chép URL" copies, so it can be pasted on another machine.
    ``on_show`` is None when there is no window to bring back.
    """

    def __init__(self, url: str, on_quit: Callable[[], None],
                 on_show: Callable[[], None] | None = None, lan_url: str | None = None) -> None:
        self.url, self.lan_url = url, lan_url or url
        self.on_show, self.on_quit = on_show, on_quit
        self.icon = None

    def menu_items(self) -> list[tuple[str, Callable[[], None]]]:
        items = []
        if self.on_show:
            items.append(("Mở cửa sổ", self.on_show))
        items += [
            ("Mở trong trình duyệt", lambda: webbrowser.open(self.url)),
            ("Sao chép URL", self._copy_url),
            ("Thoát", self._quit),
        ]
        return items

    def _copy_url(self) -> None:
        if copy_text(self.lan_url):
            self.notify(f"Đã chép {self.lan_url}")
        else:
            self.notify(self.lan_url)

    def _quit(self) -> None:
        self.stop()
        self.on_quit()

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message, TITLE)
        except Exception:  # not every backend has notifications; the copy still happened
            log.info(message)

    def _make_icon(self):
        import pystray

        import icon

        items = self.menu_items()
        # The first entry is the default: a click on the icon reopens the window,
        # or opens the browser when there is none.
        menu = pystray.Menu(*(pystray.MenuItem(label, _call(fn), default=(i == 0))
                              for i, (label, fn) in enumerate(items)))
        return pystray.Icon("voice-tts", icon.image(), TITLE, menu)

    def start(self) -> bool:
        """Show the icon from a background thread; False if there is no tray."""
        try:
            self.icon = self._make_icon()
            self.icon.run_detached()
            return True
        except Exception as exc:
            log.warning("no system tray (%s: %s); continuing without it", type(exc).__name__, exc)
            self.icon = None
            return False

    def run(self) -> bool:
        """Show the icon and block until "Thoát"; False at once if there is no tray."""
        try:
            self.icon = self._make_icon()
        except Exception as exc:
            log.warning("no system tray (%s: %s); continuing without it", type(exc).__name__, exc)
            return False
        self.icon.run()
        return True

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()


def _call(fn: Callable[[], None]):
    # pystray inspects the callback's arity; hand it one that takes (icon, item).
    return lambda _icon, _item: fn()
