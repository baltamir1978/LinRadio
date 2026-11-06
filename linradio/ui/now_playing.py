"""«Ahora»: carátula, canción, controles y la letra sincronizada."""

from collections.abc import Callable

from gi.repository import Adw, Gdk, Gtk

from ..lyrics import Status
from ..player import PlayState
from ..session import NowPlaying, Session, Source
from . import util

ART_SIZE = 220


class LyricsView(Gtk.Box):
    """Las líneas de la letra; la que suena, resaltada y centrada. Clic en una línea: la
    letra sigue desde ahí."""

    def __init__(self, session: Session) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._session = session
        self._key: object = None
        self._current: int | None = None
        self._rows: list[Gtk.Label] = []

        header = Gtk.Box(spacing=4)
        self.append(header)
        header.append(util.label("Letra", css=("heading",)))
        self.note = util.label(css=("caption", "dim-label"), ellipsize=True)
        self.note.set_hexpand(True)
        self.note.set_margin_start(8)
        header.append(self.note)
        self.adjust = Gtk.Box(spacing=2)
        header.append(self.adjust)
        minus = util.icon_button("list-remove-symbolic", "Letra antes (−0,5 s)")
        minus.connect("clicked", lambda *_: self._nudge(-0.5))
        self.offset = Gtk.Button(label="±0,0 s", valign=Gtk.Align.CENTER)
        self.offset.add_css_class("flat")
        self.offset.add_css_class("numeric")
        self.offset.set_tooltip_text("Ajuste de la letra en esta emisora. Pulsa para ponerlo a cero")
        self.offset.connect("clicked", lambda *_: self._reset())
        plus = util.icon_button("list-add-symbolic", "Letra después (+0,5 s)")
        plus.connect("clicked", lambda *_: self._nudge(0.5))
        for w in (minus, self.offset, plus):
            self.adjust.append(w)

        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroller.add_css_class("card")
        self.append(self.scroller)
        self.stack = Gtk.Stack()
        self.scroller.set_child(self.stack)
        self.message = util.label(css=("dim-label",), xalign=0.5, wrap=True)
        self.message.set_margin_top(24)
        self.message.set_margin_bottom(24)
        self.message.set_margin_start(12)
        self.message.set_margin_end(12)
        self.message.set_valign(Gtk.Align.CENTER)
        self.stack.add_named(self.message, "message")
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("lyrics")
        self.list.connect("row-activated", self._clicked)
        self.stack.add_named(self.list, "lines")

    def _nudge(self, seconds: float) -> None:
        self._session.nudge_lyrics(seconds)

    def _reset(self) -> None:
        self._session.reset_lyrics_offset()

    def _clicked(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if self._session.now.lyrics and self._session.now.lyrics.synced:
            self._session.sync_to_line(row.get_index())
            util.on_main(self.tick)

    def show(self, now: NowPlaying) -> None:
        offset = now.clock.offset
        self.offset.set_label(f"{offset:+.1f} s".replace(".", ",").replace("+0,0", "±0,0"))
        lyrics = now.lyrics
        key = (now.history_id, id(lyrics))
        synced = bool(lyrics and lyrics.synced)
        self.adjust.set_visible(synced)
        if key == self._key:
            self._note(now)
            return
        self._key = key
        self._current = None
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        self._rows = []
        if not now.has_song:
            self._message("La letra aparece cuando la emisora dice qué suena." if
                          now.station else "Elige una emisora.")
        elif lyrics is None:
            self._message("Buscando la letra…" if now.lyrics_status is None else
                          "No se encontró la letra de esta canción." if
                          now.lyrics_status is Status.NOT_FOUND else
                          "No se pudo consultar LRCLIB. Se volverá a intentar con la próxima.")
        elif lyrics.instrumental:
            self._message("♪ Instrumental ♪")
        else:
            for text in lyrics.lines:
                line = util.label(text or "♪", xalign=0.5, wrap=True)
                line.add_css_class("lyric-line")
                row = Gtk.ListBoxRow(child=line, activatable=synced)
                self.list.append(row)
                self._rows.append(line)
            self.stack.set_visible_child_name("lines")
        self._note(now)
        self.tick()

    def _note(self, now: NowPlaying) -> None:
        lyrics = now.lyrics
        if lyrics and lyrics.synced and not now.clock.exact:
            self.note.set_text("Sin saber por dónde va: pulsa la línea que suena")
        elif lyrics and not lyrics.synced and lyrics.plain:
            self.note.set_text("Sin marcas de tiempo: no puede seguir la canción")
        else:
            self.note.set_text("")

    def _message(self, text: str) -> None:
        self.message.set_text(text)
        self.stack.set_visible_child_name("message")

    def tick(self) -> None:
        now = self._session.now
        lyrics = now.lyrics
        if not lyrics or not lyrics.synced or not now.clock.exact or not self._rows:
            if self._current is not None and self._current < len(self._rows):
                self._rows[self._current].remove_css_class("current")
            self._current = None
            return
        elapsed = now.clock.elapsed()
        index = lyrics.line_index(elapsed) if elapsed is not None else None
        if index == self._current:
            return
        if self._current is not None and self._current < len(self._rows):
            self._rows[self._current].remove_css_class("current")
        self._current = index
        if index is None or index >= len(self._rows):
            return
        self._rows[index].add_css_class("current")
        row = self.list.get_row_at_index(index)
        if row is None:
            return
        ok, bounds = row.compute_bounds(self.list)
        if ok:
            adj = self.scroller.get_vadjustment()
            target = bounds.get_y() + bounds.get_height() / 2 - adj.get_page_size() / 2
            adj.set_value(max(0, min(target, adj.get_upper() - adj.get_page_size())))


class NowPlayingView(Gtk.Box):
    def __init__(self, session: Session, toggle: Callable[[], None],
                 step: Callable[[int], None], set_volume: Callable[[float], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                         margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self._session = session
        self._art_url: str | None = None
        self._art_key = "-"

        top = Gtk.Box(spacing=18)
        self.append(top)
        self.art = Gtk.Image(pixel_size=ART_SIZE)
        self.art.add_css_class("artwork")
        self.art.set_overflow(Gtk.Overflow.HIDDEN)
        self.art_frame = Gtk.Stack(width_request=ART_SIZE, height_request=ART_SIZE,
                                   valign=Gtk.Align.START)
        self.placeholder = Gtk.Box()
        self.art_frame.add_named(self.placeholder, "logo")
        self.art_frame.add_named(self.art, "art")
        top.append(self.art_frame)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True,
                       valign=Gtk.Align.CENTER)
        top.append(info)
        self.title = util.label(css=("title-1",), wrap=True)
        self.title.set_lines(3)
        info.append(self.title)
        self.artist = util.label(css=("title-3",), wrap=True)
        info.append(self.artist)
        self.station = util.label(css=("dim-label",), ellipsize=True)
        info.append(self.station)
        self.status = util.label(css=("caption", "dim-label"), wrap=True)
        info.append(self.status)

        controls = Gtk.Box(spacing=8, margin_top=10)
        info.append(controls)
        previous = util.icon_button("media-skip-backward-symbolic", "Emisora anterior",
                                    css=("circular", "flat"))
        previous.connect("clicked", lambda *_: step(-1))
        controls.append(previous)
        self.play = Gtk.Button(icon_name="media-playback-start-symbolic",
                               tooltip_text="Escuchar (espacio)", valign=Gtk.Align.CENTER)
        self.play.add_css_class("circular")
        self.play.add_css_class("suggested-action")
        self.play.add_css_class("play-button")
        self.play.connect("clicked", lambda *_: toggle())
        controls.append(self.play)
        following = util.icon_button("media-skip-forward-symbolic", "Emisora siguiente",
                                     css=("circular", "flat"))
        following.connect("clicked", lambda *_: step(1))
        controls.append(following)
        self.favorite = Gtk.ToggleButton(icon_name="emblem-favorite-symbolic",
                                         tooltip_text="Favorita", valign=Gtk.Align.CENTER)
        self.favorite.add_css_class("circular")
        self.favorite.add_css_class("flat")
        self._favorite_handler = self.favorite.connect(
            "toggled", lambda *_: session.toggle_favorite())
        controls.append(self.favorite)
        self.identify = util.icon_button("audio-input-microphone-symbolic",
                                         "Identificar con Shazam", css=("circular", "flat"))
        self.identify.connect("clicked", lambda *_: session.identify_now())
        controls.append(self.identify)
        self.spinner = Adw.Spinner(visible=False)
        controls.append(self.spinner)
        controls.append(Gtk.Box(hexpand=True))
        volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.05)
        volume.set_value(1.0)
        volume.set_draw_value(False)
        volume.set_size_request(110, -1)
        volume.set_valign(Gtk.Align.CENTER)
        volume.set_tooltip_text("Volumen")
        volume.connect("value-changed", lambda s: set_volume(s.get_value()))
        self.volume = volume
        controls.append(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
        controls.append(volume)

        self.lyrics = LyricsView(session)
        self.lyrics.set_vexpand(True)
        self.append(self.lyrics)

        self._state = PlayState.STOPPED
        self._detail = ""

    def set_player_state(self, state: PlayState, detail: str) -> None:
        self._state = state
        self._detail = detail
        playing = state is not PlayState.STOPPED
        self.play.set_icon_name("media-playback-stop-symbolic" if playing
                                else "media-playback-start-symbolic")
        self.play.set_tooltip_text("Parar (espacio)" if playing else "Escuchar (espacio)")
        self.show(self._session.now)

    def show(self, now: NowPlaying) -> None:
        station = now.station
        title = now.title
        if title is not None:
            self.title.set_text(title.track)
            self.artist.set_text(title.artist or "")
            self.artist.set_visible(bool(title.artist))
        else:
            self.title.set_text(station.name if station else "LinRadio")
            self.artist.set_text(station.detail if station else
                                 "Elige una emisora en la lista")
            self.artist.set_visible(True)
        self.station.set_text(station.name if station and title else "")
        self.station.set_visible(bool(station and title))

        parts = []
        if self._state is not PlayState.STOPPED:
            parts.append(self._state.value + (f" · {self._detail}" if self._detail else ""))
        if title is not None and now.source is Source.SHAZAM:
            parts.append("según Shazam")
        if now.identifying:
            parts.append("Escuchando con Shazam…")
        if now.message:
            parts.append(now.message)
        self.status.set_text("  ·  ".join(parts))
        self.spinner.set_visible(now.identifying)

        self.favorite.handler_block(self._favorite_handler)
        self.favorite.set_active(now.favorite)
        self.favorite.handler_unblock(self._favorite_handler)
        self.favorite.set_sensitive(now.history_id is not None)
        self.identify.set_sensitive(self._state is PlayState.PLAYING and not now.identifying)

        art = now.artwork_url if title else None
        key = f"{art}|{station.id if station else ''}"
        if key != self._art_key:
            self._art_key = key
            self._art_url = art
            if art:
                def loaded(texture: Gdk.Texture | None, url: str = art) -> None:
                    self._art_loaded(url, texture)
                util.IMAGES.load(art, loaded)
            else:
                self._show_logo(station.logoURL if station else None)
        self.lyrics.show(now)

    def _art_loaded(self, url: str, texture: Gdk.Texture | None) -> None:
        if url != self._art_url:
            return
        if texture is None:
            station = self._session.now.station
            self._show_logo(station.logoURL if station else None)
            return
        self.art.set_from_paintable(texture)
        self.art_frame.set_visible_child_name("art")

    def _show_logo(self, url: str | None) -> None:
        while (child := self.placeholder.get_first_child()) is not None:
            self.placeholder.remove(child)
        station = self._session.now.station
        self.placeholder.append(util.station_avatar(station.name if station else "LinRadio",
                                                    url, ART_SIZE))
        self.art_frame.set_visible_child_name("logo")

    def tick(self) -> None:
        self.lyrics.tick()
