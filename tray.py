"""System tray icon: keeps Voice TTS reachable while no window is showing.

The desktop window hides here when it is minimized or closed, and
``serve --tray`` lives here with no window at all. Only "Thoát" ends the app.
With a window loop running on Windows, right-click opens ``PopupMenu`` - the
same entries drawn in the app's own style - and the native menu is the fallback.

pystray and Pillow are imported when an icon is actually made, so importing
this module costs nothing on a headless server.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import webbrowser
from typing import Callable
from urllib.parse import urlsplit

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
        # Set once a window loop exists to draw it: right-click then opens this
        # instead of the native menu, which stays as the fallback.
        self.popup: PopupMenu | None = None

    def entries(self) -> list[tuple[str, str, Callable[[], None]]]:
        """``(key, label, action)`` per menu entry; the key names its icon in the popup."""
        items = []
        if self.on_show:
            items.append(("show", "Mở cửa sổ", self.on_show))
        items += [
            ("browser", "Mở trong trình duyệt", lambda: webbrowser.open(self.url)),
            ("copy", "Sao chép URL", self._copy_url),
            ("quit", "Thoát", self._quit),
        ]
        return items

    def menu_items(self) -> list[tuple[str, Callable[[], None]]]:
        return [(label, fn) for _, label, fn in self.entries()]

    def _copy_url(self) -> None:
        if copy_text(self.lan_url):
            self.notify(f"Đã chép {self.lan_url}")
        else:
            self.notify(self.lan_url)

    def _quit(self) -> None:
        self.stop()
        if self.popup is not None:
            self.popup.destroy()  # a hidden window would keep the window loop alive
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
        cls = pystray.Icon
        if sys.platform == "win32":
            from pystray._util import win32

            tray = self

            class Icon(pystray.Icon):
                # pystray maps WM_NOTIFY to this method when the icon is made,
                # so overriding it is the one way in to the right-click.
                def _on_notify(self, wparam, lparam):
                    if lparam == win32.WM_RBUTTONUP and tray.popup is not None:
                        try:
                            if tray.popup.open():
                                return
                        except Exception as exc:
                            log.warning("tray popup failed (%s); native menu instead", exc)
                    super()._on_notify(wparam, lparam)

            cls = Icon
        return cls("voice-tts", icon.image(), TITLE, menu)

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


class PopupMenu:
    """The tray menu as a small dark window drawn by ``web/tray.html`` (Windows).

    The window is made hidden next to the main one and kept, so a right-click
    only moves and shows it - it appears as fast as the native menu would.
    It opens with its corner at the pointer, like the native menu, and hides
    when it loses focus, on Esc, or once an entry is picked.
    """

    WIDTH = 272  # CSS px; the page reports its own height once it has laid out

    def __init__(self, tray: Tray, base_url: str) -> None:
        import webview

        self.tray = tray
        self.height = 236
        self.hwnd: int | None = None
        self.window = webview.create_window(
            "Voice TTS menu", base_url.rstrip("/") + "/web/tray.html", js_api=_PopupApi(self),
            width=self.WIDTH, height=self.height, frameless=True, easy_drag=False,
            resizable=False, on_top=True, hidden=True, background_color="#1C1C1E")
        self.window.events.loaded += self._loaded

    def _loaded(self) -> None:
        import ctypes

        form = self.window.native
        hwnd = form.Handle.ToInt64()
        user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
        # A tool window: no taskbar button and no Alt+Tab entry. The style is
        # set while hidden, which is when Windows reads it.
        GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        # Windows 11 rounds the corners and draws a hairline in the separator
        # colour; earlier versions ignore both and stay square.
        for attr, value in ((33, 2),             # DWMWA_WINDOW_CORNER_PREFERENCE: round
                            (34, 0x003C3A3A)):   # DWMWA_BORDER_COLOR: #3A3A3C as BGR
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        form.Deactivate += lambda *_: self.hide()
        self.hwnd = hwnd

    def open(self) -> bool:
        """Show the menu at the pointer; False if it is not ready yet."""
        if self.hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        scale = user32.GetDpiForWindow(wintypes.HWND(self.hwnd)) / 96
        w, h = round(self.WIDTH * scale), round(self.height * scale)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(user32.MonitorFromPoint(pt, 2), ctypes.byref(info))  # NEAREST
        work, gap = info.rcWork, round(8 * scale)
        # Bottom-right corner at the pointer, kept inside the work area: above a
        # bottom taskbar, which is where the tray almost always is.
        x = min(max(pt.x - w, work.left + gap), work.right - w - gap)
        y = min(max(pt.y - h, work.top + gap), work.bottom - h - gap)

        HWND_TOPMOST, SWP_NOACTIVATE = -1, 0x0010
        user32.SetWindowPos(wintypes.HWND(self.hwnd), wintypes.HWND(HWND_TOPMOST),
                            x, y, w, h, SWP_NOACTIVATE)
        self.window.evaluate_js("menu.open()")  # fresh status, no highlight, enter motion
        self.window.show()
        # The shell lets the process that owns the clicked icon take the
        # foreground, and the menu needs focus for its keys and to know when
        # the user has clicked elsewhere.
        user32.SetForegroundWindow(wintypes.HWND(self.hwnd))
        return True

    def hide(self) -> None:
        # Deactivate fires on the UI thread, and hide() waits on that thread.
        threading.Thread(target=self.window.hide, daemon=True).start()

    def destroy(self) -> None:
        self.window.destroy()


class _PopupApi:
    """What ``web/tray.html`` may call. Private attributes stay hidden from JS."""

    def __init__(self, popup: PopupMenu) -> None:
        self._popup = popup

    def info(self) -> dict:
        tray = self._popup.tray
        return {"title": TITLE, "address": urlsplit(tray.lan_url).netloc,
                "items": [{"key": key, "label": label} for key, label, _ in tray.entries()]}

    def resize(self, height: float) -> None:
        self._popup.height = max(1, round(height))

    def pick(self, key: str) -> bool:
        """Run one entry. "copy" reports back and the page closes itself after
        showing the result; everything else closes the menu first."""
        tray = self._popup.tray
        if key == "copy":
            return copy_text(tray.lan_url)
        self._popup.hide()
        for k, _, fn in tray.entries():
            if k == key:
                threading.Thread(target=fn, daemon=True).start()
        return True

    def dismiss(self) -> None:
        self._popup.hide()


def _call(fn: Callable[[], None]):
    # pystray inspects the callback's arity; hand it one that takes (icon, item).
    return lambda _icon, _item: fn()
