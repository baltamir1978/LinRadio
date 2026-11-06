"""«Historial»: lo que ha sonado, con favoritas, búsqueda y títulos ignorados."""

from collections.abc import Callable
from datetime import datetime

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..history import History, ListenedSong
from . import util

PAGE = 150


def _when(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    today = datetime.now().date()
    if moment.date() == today:
        return moment.strftime("%H:%M")
    if (today - moment.date()).days == 1:
        return "ayer, " + moment.strftime("%H:%M")
    return moment.strftime("%d/%m/%Y %H:%M")


class SongRow(Adw.ActionRow):
    def __init__(self, song: ListenedSong, page: "HistoryPage") -> None:
        super().__init__(title=GLib.markup_escape_text(song.title),
                         subtitle=GLib.markup_escape_text(
                             "  ·  ".join(p for p in (song.artist, song.station_name,
                                                      _when(song.listened_at)) if p)))
        self.song = song
        picture = Gtk.Image(pixel_size=44, icon_name="audio-x-generic-symbolic")
        picture.add_css_class("thumb")
        picture.set_overflow(Gtk.Overflow.HIDDEN)
        if song.artwork_url:
            def show(texture: Gdk.Texture | None) -> None:
                if texture is not None:
                    picture.set_from_paintable(texture)
            util.IMAGES.load(song.artwork_url, show)
        frame = Gtk.Box(valign=Gtk.Align.CENTER)
        frame.append(picture)
        self.add_prefix(frame)

        heart = Gtk.ToggleButton(icon_name="emblem-favorite-symbolic", active=song.favorite,
                                 valign=Gtk.Align.CENTER, tooltip_text="Favorita")
        heart.add_css_class("flat")
        heart.add_css_class("circular")
        if song.favorite:
            heart.add_css_class("favorite")
        heart.connect("toggled", lambda b: page.toggle_favorite(song, b))
        self.add_suffix(heart)

        menu = Gio.Menu()
        menu.append("Copiar «artista - título»", f"history.copy('{song.id}')")
        if song.page_url:
            menu.append("Abrir en Apple Music", f"history.open('{song.id}')")
        menu.append("Buscar en YouTube", f"history.youtube('{song.id}')")
        danger = Gio.Menu()
        danger.append("Borrar", f"history.delete('{song.id}')")
        danger.append("Borrar para siempre (no volver a apuntarlo)",
                      f"history.ignore('{song.id}')")
        menu.append_section(None, danger)
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                              valign=Gtk.Align.CENTER, tooltip_text="Más")
        more.add_css_class("flat")
        self.add_suffix(more)


class HistoryPage(Gtk.Box):
    def __init__(self, history: History, on_change: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.history = history
        self._on_change = on_change

        bar = Gtk.Box(spacing=8, margin_top=12, margin_bottom=8, margin_start=12, margin_end=12)
        self.append(bar)
        self.search = Gtk.SearchEntry(hexpand=True, placeholder_text="Buscar en el historial")
        self.search.connect("search-changed", lambda *_: self.refresh())
        bar.append(self.search)
        self.only_favorites = Gtk.ToggleButton(icon_name="emblem-favorite-symbolic",
                                               tooltip_text="Sólo favoritas")
        self.only_favorites.connect("toggled", lambda *_: self.refresh())
        bar.append(self.only_favorites)
        menu = Gio.Menu()
        menu.append("Títulos ignorados…", "history.ignored")
        menu.append("Vaciar el historial (deja las favoritas)", "history.clear")
        bar.append(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                                  tooltip_text="Más"))

        self.stack = Gtk.Stack(vexpand=True)
        self.append(self.stack)
        self.empty = Adw.StatusPage(icon_name="document-open-recent-symbolic",
                                    title="Todavía no ha sonado nada",
                                    description="Las canciones se apuntan solas mientras "
                                                "escuchas, también con la ventana cerrada.")
        self.stack.add_named(self.empty, "empty")
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.stack.add_named(scroller, "list")
        clamp = Adw.Clamp(maximum_size=760)
        scroller.set_child(clamp)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_top=4,
                                margin_bottom=18, margin_start=12, margin_end=12,
                                valign=Gtk.Align.START)
        self.list.add_css_class("boxed-list")
        clamp.set_child(self.list)

        group = Gio.SimpleActionGroup()
        for name, handler in (("copy", self._copy), ("open", self._open),
                              ("youtube", self._youtube), ("delete", self._delete),
                              ("ignore", self._ignore)):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", lambda _a, v, h=handler: self._with_song(v, h))
            group.add_action(action)
        for name, simple in (("ignored", self._show_ignored), ("clear", self._clear)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, h=simple: h())
            group.add_action(action)
        self.insert_action_group("history", group)
        self._signature: tuple[object, ...] = ()
        self.refresh()

    def refresh(self, force: bool = False) -> None:
        query = self.search.get_text().strip().casefold()
        favorites = self.only_favorites.get_active()
        songs = [s for s in self.history.songs
                 if (not favorites or s.favorite)
                 and (not query or query in f"{s.title} {s.artist or ''} {s.station_name}"
                      .casefold())][:PAGE]
        signature = tuple((s.id, s.title, s.artist, s.artwork_url, s.favorite) for s in songs)
        if signature == self._signature and not force:
            return
        self._signature = signature
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        for song in songs:
            self.list.append(SongRow(song, self))
        if songs:
            self.stack.set_visible_child_name("list")
        else:
            self.empty.set_title("Nada que coincida" if query or favorites else
                                 "Todavía no ha sonado nada")
            self.stack.set_visible_child_name("empty")

    def toggle_favorite(self, song: ListenedSong, button: Gtk.ToggleButton) -> None:
        if song.favorite != button.get_active():
            self.history.toggle_favorite(song.id)
            self.history.save()
            self._on_change()
        if button.get_active():
            button.add_css_class("favorite")
        else:
            button.remove_css_class("favorite")

    def _with_song(self, value: GLib.Variant, handler: Callable[[ListenedSong], None]) -> None:
        song = self.history.get(value.get_string())
        if song is not None:
            handler(song)

    def _copy(self, song: ListenedSong) -> None:
        text = f"{song.artist} - {song.title}" if song.artist else song.title
        self.get_display().get_clipboard().set(text)

    def _open(self, song: ListenedSong) -> None:
        if song.page_url:
            Gtk.UriLauncher.new(song.page_url).launch(self.get_root(), None, None, None)

    def _youtube(self, song: ListenedSong) -> None:
        query = GLib.uri_escape_string(f"{song.artist or ''} {song.title}".strip(), None, False)
        Gtk.UriLauncher.new(f"https://www.youtube.com/results?search_query={query}").launch(
            self.get_root(), None, None, None)

    def _delete(self, song: ListenedSong) -> None:
        self.history.delete({song.id})
        self.history.save()
        self.refresh()
        self._on_change()

    def _ignore(self, song: ListenedSong) -> None:
        self.history.ignore_and_purge(song)
        self.history.save()
        self.refresh()
        self._on_change()

    def _clear(self) -> None:
        dialog = Adw.AlertDialog(heading="¿Vaciar el historial?",
                                 body="Se borran todas las canciones menos las favoritas.")
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("clear", "Vaciar")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def answered(_d: Adw.AlertDialog, response: str) -> None:
            if response == "clear":
                self.history.clear_non_favorites()
                self.history.save()
                self.refresh()
                self._on_change()
        dialog.connect("response", answered)
        dialog.present(self.get_root())

    def _show_ignored(self) -> None:
        dialog = Adw.Dialog(title="Títulos ignorados", content_width=480, content_height=420)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        dialog.set_child(view)
        if not self.history.ignored:
            view.set_content(Adw.StatusPage(
                icon_name="action-unavailable-symbolic", title="Ninguno",
                description="«Borrar para siempre» en una canción del historial la añade "
                            "aquí: sirve para los eslóganes que algunas emisoras mandan "
                            "como si fueran canciones."))
        else:
            box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_top=12,
                              margin_bottom=12, margin_start=12, margin_end=12,
                              valign=Gtk.Align.START)
            box.add_css_class("boxed-list")
            for entry in list(self.history.ignored):
                row = Adw.ActionRow(title=GLib.markup_escape_text(entry.title),
                                    subtitle=GLib.markup_escape_text(entry.station_name))
                undo = Gtk.Button(label="Volver a apuntar", valign=Gtk.Align.CENTER)
                undo.add_css_class("flat")

                def restore(_b: Gtk.Button, e: object = entry, r: Adw.ActionRow = row) -> None:
                    self.history.unignore(e)        # type: ignore[arg-type]
                    self.history.save()
                    box.remove(r)
                undo.connect("clicked", restore)
                row.add_suffix(undo)
                box.append(row)
            view.set_content(Gtk.ScrolledWindow(child=box))
        dialog.present(self.get_root())
