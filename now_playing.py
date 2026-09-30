"""
Now Playing Widget
-------------------
A small always-on-top dark panel that shows what's currently playing on
Windows (Spotify, browser tab, or anything else that reports media info
to the OS via SMTC - System Media Transport Controls).

Windows only. Requires:
    pip install winsdk pillow

Run:
    python now_playing.py
"""

import asyncio
import datetime
import io
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageTk, ImageDraw

from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winsdk.windows.storage.streams import DataReader, Buffer, InputStreamOptions

# ---------------------------------------------------------------------------
# Colors / style
# ---------------------------------------------------------------------------
BG = "#161616"
CARD = "#1c1c1c"
FG = "#f2f2f2"
SUBFG = "#8f8f8f"
ACCENT = "#ffffff"
HOVER = "#2c2c2c"
PRESS = "#3d3d3d"
ACTIVE = "#3a3a3a"
PROGRESS_BG = "#333333"
PROGRESS_FG = "#eeeeee"
ART_SIZE = 48
WIDTH = 300
HEIGHT = 138

POLL_MS = 1000    # how often we actually ask Windows for fresh data
TICK_MS = 40      # how often we redraw the progress bar (smooth motion)

# ---------------------------------------------------------------------------
# Media reading (async, runs on a background thread/loop)
# ---------------------------------------------------------------------------

async def _read_stream_to_bytes(thumb_ref):
    if thumb_ref is None:
        return None
    stream = await thumb_ref.open_read_async()
    size = stream.size
    if size == 0:
        return None
    buf = Buffer(size)
    await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
    reader = DataReader.from_buffer(buf)
    data = bytearray(size)
    reader.read_bytes(data)
    return bytes(data)


async def get_media_state():
    sessions = await MediaManager.request_async()
    session = sessions.get_current_session()
    if session is None:
        return None

    info = await session.try_get_media_properties_async()
    playback = session.get_playback_info()
    timeline = session.get_timeline_properties()

    thumb_bytes = None
    try:
        thumb_bytes = await _read_stream_to_bytes(info.thumbnail)
    except Exception:
        thumb_bytes = None

    status = playback.playback_status if playback else None
    is_playing = status == PlaybackStatus.PLAYING

    position = timeline.position.total_seconds() if timeline else 0
    end = timeline.end_time.total_seconds() if timeline else 0

    # SMTC only updates "position" when something actually happens (play,
    # pause, seek) - not continuously. So by the time we read it here, it
    # may already be a fraction of a second (or more) stale, which causes a
    # visible pop every time we resync to it. Correct for that using
    # last_updated_time so our value reflects "right now", not "whenever
    # Windows last bothered to record it".
    if timeline is not None and is_playing:
        try:
            last_updated = timeline.last_updated_time
            now = datetime.datetime.now(datetime.timezone.utc)
            drift = (now - last_updated).total_seconds()
            if 0 <= drift < 30:  # ignore clock skew / bogus values
                position += drift
        except Exception:
            pass
    position = min(position, end) if end else position

    return {
        "title": info.title or "Unknown title",
        "artist": info.artist or "",
        "thumb": thumb_bytes,
        "is_playing": is_playing,
        "position": max(0, position),
        "duration": max(0, end),
        "session": session,
    }


class MediaBridge:
    """Runs an asyncio loop on its own thread so tkinter's mainloop is free.

    IMPORTANT: Tkinter is not thread-safe. The background thread never
    touches the UI directly - it only drops results into a queue, and the
    main thread (via the widget's own after()-driven loop) drains it.
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._current_session = None  # keep a ref for control calls
        self.results = queue.Queue()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def request_state(self):
        """Kick off a fetch. Result shows up later in self.results."""
        fut = self._run(get_media_state())

        def done(f):
            try:
                result = f.result()
            except Exception:
                result = None
            if result is not None:
                self._current_session = result.pop("session", None)
            self.results.put(result)

        fut.add_done_callback(done)

    def _control(self, method_name):
        if self._current_session is None:
            return
        coro = getattr(self._current_session, method_name)()
        self._run(coro)

    def play_pause(self):
        if self._current_session is None:
            return
        pb = self._current_session.get_playback_info()
        if pb and pb.playback_status == PlaybackStatus.PLAYING:
            self._control("try_pause_async")
        else:
            self._control("try_play_async")

    def next_track(self):
        self._control("try_skip_next_async")

    def prev_track(self):
        self._control("try_skip_previous_async")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def format_time(seconds):
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def rounded_bg(w, h, radius, color):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=color)
    return img


def truncate_to_width(font_obj, text, max_width):
    """Shorten text with an ellipsis so it fits in max_width pixels,
    keeping it on a single line instead of letting Tk wrap it."""
    if font_obj.measure(text) <= max_width:
        return text
    ellipsis = "\u2026"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font_obj.measure(text[:mid] + ellipsis) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ellipsis) if lo > 0 else ellipsis


class NowPlayingWidget(tk.Tk):
    def __init__(self):
        super().__init__()
        self.overrideredirect(True)          # borderless
        self.attributes("-topmost", True)
        self.configure(bg=BG)
        self.geometry(f"{WIDTH}x{HEIGHT}+80+80")

        # transparency trick: use a solid color key as "transparent"
        try:
            self.attributes("-transparentcolor", BG)
        except tk.TclError:
            pass

        self.bridge = MediaBridge()
        self._art_photo = None
        self._drag = {"x": 0, "y": 0}
        self._img_refs = {}       # keep PhotoImage refs alive (avoid GC)
        self._box_colors = {}     # current fill color per animated box item
        self._anim_tokens = {}    # cancels stale in-flight animations

        # local clock used to smoothly advance the progress bar between polls
        self._known_position = 0.0
        self._known_duration = 0.0
        self._known_is_playing = False
        self._synced_at = time.monotonic()

        self._build_ui()
        self._make_draggable(self)
        self.after(100, self._poll)
        self.after(TICK_MS, self._tick)

    # -- small animation helpers ---------------------------------------------
    def _lerp_color(self, c1, c2, t):
        r1, g1, b1 = self.winfo_rgb(c1)
        r2, g2, b2 = self.winfo_rgb(c2)
        r = int(r1 + (r2 - r1) * t) >> 8
        g = int(g1 + (g2 - g1) * t) >> 8
        b = int(b1 + (b2 - b1) * t) >> 8
        return f"#{r:02x}{g:02x}{b:02x}"

    def _animate_box_color(self, box_item, size, radius, to_color,
                            steps=7, delay=12):
        from_color = self._box_colors.get(box_item, CARD)
        self._anim_tokens[box_item] = self._anim_tokens.get(box_item, 0) + 1
        token = self._anim_tokens[box_item]

        def step(i):
            if self._anim_tokens.get(box_item) != token:
                return  # a newer animation took over
            t = i / steps
            color = self._lerp_color(from_color, to_color, t)
            photo = ImageTk.PhotoImage(rounded_bg(size, size, radius, color))
            self._img_refs[box_item] = photo
            self.canvas.itemconfigure(box_item, image=photo)
            if i < steps:
                self.after(delay, lambda: step(i + 1))
            else:
                self._box_colors[box_item] = to_color

        step(0)

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        bg_img = rounded_bg(WIDTH, HEIGHT, 22, CARD)
        self._panel_photo = ImageTk.PhotoImage(bg_img)
        self.canvas = tk.Canvas(self, width=WIDTH, height=HEIGHT,
                                 bg=BG, highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self._panel_photo)

        self.title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.artist_font = tkfont.Font(family="Segoe UI", size=8)
        time_font = tkfont.Font(family="Segoe UI", size=7)

        # album art placeholder (rounded square)
        art_bg = rounded_bg(ART_SIZE, ART_SIZE, 7, "#2c2c2c")
        self._art_placeholder = ImageTk.PhotoImage(art_bg)
        self.art_id = self.canvas.create_image(16, 16, anchor="nw",
                                                image=self._art_placeholder)

        text_x = 16 + ART_SIZE + 12
        # single-line only (no "width" wrap arg) - long text gets truncated
        # with an ellipsis instead, so it can never wrap down onto the
        # artist line beneath it.
        self._text_max_width = WIDTH - text_x - 26
        self.title_id = self.canvas.create_text(
            text_x, 20, anchor="nw", text="Nothing playing",
            fill=FG, font=self.title_font)
        self.artist_id = self.canvas.create_text(
            text_x, 40, anchor="nw", text="",
            fill=SUBFG, font=self.artist_font)

        self._last_title = None
        self._last_artist = None
        self._title_truncated = False
        self._tooltip = None

        self.canvas.tag_bind(self.title_id, "<Enter>", self._on_title_enter)
        self.canvas.tag_bind(self.title_id, "<Leave>", self._on_title_leave)

        # progress bar
        bar_x0, bar_y0 = 16, HEIGHT - 50
        bar_x1 = WIDTH - 16
        bar_y1 = bar_y0 + 3
        self._bar_coords = (bar_x0, bar_y0, bar_x1, bar_y1)
        self.canvas.create_rectangle(bar_x0, bar_y0, bar_x1, bar_y1,
                                      fill=PROGRESS_BG, outline="")
        self.progress_id = self.canvas.create_rectangle(
            bar_x0, bar_y0, bar_x0, bar_y1, fill=PROGRESS_FG, outline="")

        self.pos_id = self.canvas.create_text(
            bar_x0, bar_y1 + 5, anchor="nw", text="0:00",
            fill=SUBFG, font=time_font)
        self.dur_id = self.canvas.create_text(
            bar_x1, bar_y1 + 5, anchor="ne", text="0:00",
            fill=SUBFG, font=time_font)

        # controls row: prev / play-pause / next
        ctrl_y = HEIGHT - 17
        cx = WIDTH / 2

        def make_button(cx_pos, cy_pos, char, size, tag, handler,
                         box_size=27, radius=8, toggle=False):
            box_img = rounded_bg(box_size, box_size, radius, CARD)
            box_photo = ImageTk.PhotoImage(box_img)
            box_item = self.canvas.create_image(
                cx_pos, cy_pos, image=box_photo, tags=(tag,))
            self._img_refs[box_item] = box_photo
            self._box_colors[box_item] = CARD

            glyph = self.canvas.create_text(
                cx_pos, cy_pos, text=char, fill=FG,
                font=("Segoe UI", size), tags=(tag,))

            state = {"hover": False, "active": False}

            def refresh():
                if state["active"]:
                    target = ACTIVE
                elif state["hover"]:
                    target = HOVER
                else:
                    target = CARD
                self._animate_box_color(box_item, box_size, radius, target)
                self.canvas.itemconfigure(
                    glyph, fill=ACCENT if (state["hover"] or state["active"])
                    else FG)

            def on_click(e):
                # quick bright press-flash, then settle back
                self._animate_box_color(box_item, box_size, radius, PRESS,
                                         steps=3, delay=9)
                handler()
                if toggle:
                    state["active"] = not state["active"]
                self.after(110, refresh)
                return "break"  # don't let this click also start a drag

            def on_enter(e):
                state["hover"] = True
                self.canvas.configure(cursor="hand2")
                refresh()

            def on_leave(e):
                state["hover"] = False
                self.canvas.configure(cursor="")
                refresh()

            self.canvas.tag_bind(tag, "<Button-1>", on_click)
            self.canvas.tag_bind(tag, "<Enter>", on_enter)
            self.canvas.tag_bind(tag, "<Leave>", on_leave)

            def set_active(v):
                state["active"] = v
                if not state["hover"]:
                    refresh()

            return {"glyph": glyph, "set_active": set_active}

        spacing = 37
        self.prev_btn = make_button(
            cx - spacing, ctrl_y, "\u23EE", 11, "btn_prev",
            self.bridge.prev_track)
        self.play_btn = make_button(
            cx, ctrl_y, "\u25B6", 13, "btn_play",
            self._on_play_pause_clicked, box_size=32, radius=10)
        self.next_btn = make_button(
            cx + spacing, ctrl_y, "\u23ED", 11, "btn_next",
            self.bridge.next_track)

        self.close_btn = make_button(
            WIDTH - 16, 14, "\u2715", 8, "btn_close", self.destroy,
            box_size=18, radius=5)

    def _make_draggable(self, widget):
        def start(e):
            self._drag["x"] = e.x
            self._drag["y"] = e.y
            self._hide_tooltip()

        def move(e):
            x = self.winfo_x() + e.x - self._drag["x"]
            y = self.winfo_y() + e.y - self._drag["y"]
            self.geometry(f"+{x}+{y}")
            self._hide_tooltip()

        self.canvas.bind("<Button-1>", start, add="+")
        self.canvas.bind("<B1-Motion>", move, add="+")

    # -- polling (real data) vs ticking (smooth visual motion) ---------------
    def _poll(self):
        self.bridge.request_state()
        self.after(POLL_MS, self._poll)

    def _tick(self):
        # Drain any results the background thread has produced. This runs
        # on the main thread (via after()), so it's safe to touch the UI here
        # - unlike calling back directly from the asyncio thread.
        try:
            while True:
                state = self.bridge.results.get_nowait()
                self._on_state(state)
        except queue.Empty:
            pass

        # Advance the progress bar smoothly between polls using a local
        # clock, instead of waiting for the next 1-second poll to move it.
        if self._known_is_playing and self._known_duration > 0:
            elapsed = time.monotonic() - self._synced_at
            position = min(self._known_position + elapsed, self._known_duration)
            self._render_progress(position, self._known_duration)

        self.after(TICK_MS, self._tick)

    def _on_state(self, state):
        if state is None:
            self._set_text(None, "")
            self._known_position = 0.0
            self._known_duration = 0.0
            self._known_is_playing = False
            self._synced_at = time.monotonic()
            self._render_progress(0, 0)
            self._set_art(None)
            self.canvas.itemconfigure(self.play_btn["glyph"], text="\u25B6")
            return

        self._set_text(state["title"], state["artist"])
        self._set_art(state["thumb"])

        # resync the local smoothing clock to the freshly-fetched truth
        self._known_position = state["position"]
        self._known_duration = state["duration"]
        self._known_is_playing = state["is_playing"]
        self._synced_at = time.monotonic()
        self._render_progress(state["position"], state["duration"])

        self.canvas.itemconfigure(
            self.play_btn["glyph"],
            text="\u23F8" if state["is_playing"] else "\u25B6")

    def _set_text(self, title=None, artist=""):
        # only fade in when the *track itself* changed - not on every poll
        changed = (title != self._last_title) or (artist != self._last_artist)
        self._last_title = title
        self._last_artist = artist

        full_title = title or "Nothing playing"
        shown_title = truncate_to_width(
            self.title_font, full_title, self._text_max_width)
        shown_artist = truncate_to_width(
            self.artist_font, artist or "", self._text_max_width)

        self._title_truncated = (shown_title != full_title)
        self._full_title_text = full_title
        if changed:
            self._hide_tooltip()  # don't leave a stale tooltip up on a new track

        self.canvas.itemconfigure(self.title_id, text=shown_title)
        self.canvas.itemconfigure(self.artist_id, text=shown_artist)

        if not changed:
            self.canvas.itemconfigure(self.title_id, fill=FG)
            self.canvas.itemconfigure(self.artist_id, fill=SUBFG)
            return

        # fade the new title/artist in from the panel color, rather than
        # just snapping to the new text every time the track changes
        self._fade_text_color(self.title_id, FG)
        self._fade_text_color(self.artist_id, SUBFG)

    def _on_title_enter(self, event):
        if self._title_truncated:
            self._show_tooltip(self._full_title_text)

    def _on_title_leave(self, event):
        self._hide_tooltip()

    def _show_tooltip(self, text):
        self._hide_tooltip()
        tw = tk.Toplevel(self)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        x = self.winfo_x() + 16
        y = self.winfo_y() + HEIGHT + 4
        tw.geometry(f"+{x}+{y}")
        tk.Label(tw, text=text, bg="#2a2a2a", fg=FG,
                 font=("Segoe UI", 9), padx=8, pady=4).pack()
        self._tooltip = tw

    def _hide_tooltip(self):
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None

    def _fade_text_color(self, item, target_color, steps=8, delay=18):
        self.canvas.itemconfigure(item, fill=CARD)

        def step(i):
            t = i / steps
            color = self._lerp_color(CARD, target_color, t)
            self.canvas.itemconfigure(item, fill=color)
            if i < steps:
                self.after(delay, lambda: step(i + 1))

        step(0)

    def _on_play_pause_clicked(self):
        # Flip the icon and local "is playing" state immediately, instead of
        # waiting up to a second for the next poll to confirm it - the real
        # command still goes out to Windows right away too.
        self._known_is_playing = not self._known_is_playing
        self._synced_at = time.monotonic()
        self.canvas.itemconfigure(
            self.play_btn["glyph"],
            text="\u23F8" if self._known_is_playing else "\u25B6")
        self.bridge.play_pause()

    def _render_progress(self, position, duration):
        x0, y0, x1, _ = self._bar_coords
        frac = (position / duration) if duration else 0
        frac = max(0, min(1, frac))
        new_x1 = x0 + (x1 - x0) * frac
        self.canvas.coords(self.progress_id, x0, y0, new_x1, y0 + 4)
        self.canvas.itemconfigure(self.pos_id, text=format_time(position))
        self.canvas.itemconfigure(self.dur_id, text=format_time(duration))

    def _set_art(self, thumb_bytes):
        try:
            if thumb_bytes:
                img = Image.open(io.BytesIO(thumb_bytes)).convert("RGB")
                img = img.resize((ART_SIZE, ART_SIZE), Image.LANCZOS)
            else:
                img = Image.new("RGB", (ART_SIZE, ART_SIZE), "#2c2c2c")
            mask = Image.new("L", (ART_SIZE, ART_SIZE), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, ART_SIZE - 1, ART_SIZE - 1], radius=8, fill=255)
            img.putalpha(mask)
            self._art_photo = ImageTk.PhotoImage(img)
            self.canvas.itemconfigure(self.art_id, image=self._art_photo)
        except Exception:
            pass


if __name__ == "__main__":
    app = NowPlayingWidget()
    app.mainloop()