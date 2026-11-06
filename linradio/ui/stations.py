"""La lista de emisoras (barra lateral) y los diálogos para añadir más."""

import json
from collections.abc import Callable

from gi.repository import Adw, Gio, GLib, Gtk

from .. import catalog
from ..catalog import Station, StationList
from . import util

COUNTRIES = [("ES", "España"), ("", "Todos los países"), ("PT", "Portugal"),
             ("FR", "Francia"), ("GB", "Reino Unido"), ("US", "Estados Unidos"),
             ("MX", "México"), ("AR", "Argentina"), ("DE", "Alemania"), ("IT", "Italia")]


class StationRow(Gtk.ListBoxRow):
    def __init__(self, station: Station, sidebar: "StationSidebar") -> None:
        super().__init__()
        self.station = station
        box = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6, margin_start=6, margin_end=4)
        self.set_child(box)
        box.append(util.station_avatar(station.name, station.logoURL, 36))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True,
                       valign=Gtk.Align.CENTER)
        box.append(text)
        text.append(util.label(station.name, css=("heading",), ellipsize=True))
        if station.detail:
            text.append(util.label(station.detail, css=("caption", "dim-label"),
                                   ellipsize=True))
        self.playing = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        self.playing.set_visible(False)
        box.append(self.playing)

        menu = Gio.Menu()
        menu.append("Subir", f"stations.up('{station.id}')")
        menu.append("Bajar", f"stations.down('{station.id}')")
        menu.append("Renombrar…", f"stations.rename('{station.id}')")
        danger = Gio.Menu()
        danger.append("Quitar de la lista", f"stations.remove('{station.id}')")
        menu.append_section(None, danger)
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                              valign=Gtk.Align.CENTER, tooltip_text="Más")
        more.add_css_class("flat")
        box.append(more)


class StationSidebar(Gtk.Box):
    def __init__(self, stations: StationList, on_play: Callable[[Station], None],
                 on_change: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.stations = stations
        self._on_play = on_play
        self._on_change = on_change
        self._current_id: str | None = None

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.append(scroller)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.list.connect("row-activated", self._activated)
        scroller.set_child(self.list)

        group = Gio.SimpleActionGroup()
        for name, handler in (("up", lambda s: self._move(s, -1)),
                              ("down", lambda s: self._move(s, 1)),
                              ("rename", self._rename), ("remove", self._remove)):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", lambda _a, v, h=handler: self._with(v, h))
            group.add_action(action)
        self.insert_action_group("stations", group)
        self.refresh()

    def refresh(self) -> None:
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        for station in self.stations.stations:
            row = StationRow(station, self)
            self.list.append(row)
        self.mark_playing(self._current_id)

    def mark_playing(self, station_id: str | None) -> None:
        self._current_id = station_id
        index = 0
        while (row := self.list.get_row_at_index(index)) is not None:
            assert isinstance(row, StationRow)
            current = row.station.id == station_id
            row.playing.set_visible(current)
            if current:
                self.list.select_row(row)
            index += 1
        if station_id is None:
            self.list.unselect_all()

    def _activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if isinstance(row, StationRow):
            self._on_play(row.station)

    def _with(self, value: GLib.Variant, handler: Callable[[Station], None]) -> None:
        wanted = value.get_string()
        station = next((s for s in self.stations.stations if s.id == wanted), None)
        if station is not None:
            handler(station)

    def _save(self) -> None:
        self.stations.save()
        self.refresh()
        self._on_change()

    def _move(self, station: Station, delta: int) -> None:
        items = self.stations.stations
        i = items.index(station)
        j = i + delta
        if 0 <= j < len(items):
            items[i], items[j] = items[j], items[i]
            self._save()

    def _remove(self, station: Station) -> None:
        dialog = Adw.AlertDialog(heading=f"¿Quitar {station.name}?",
                                 body="Se puede volver a añadir buscándola.")
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("remove", "Quitar")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def answered(_d: Adw.AlertDialog, response: str) -> None:
            if response == "remove":
                self.stations.stations.remove(station)
                self._save()
        dialog.connect("response", answered)
        dialog.present(self.get_root())

    def _rename(self, station: Station) -> None:
        dialog = Adw.AlertDialog(heading="Renombrar la emisora")
        entry = Gtk.Entry(text=station.name, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("ok", "Guardar")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")

        def answered(_d: Adw.AlertDialog, response: str) -> None:
            name = entry.get_text().strip()
            if response == "ok" and name:
                station.name = name
                self._save()
        dialog.connect("response", answered)
        dialog.present(self.get_root())

    # --- Añadir --------------------------------------------------------------------------

    def add_from_search(self) -> None:
        SearchDialog(self).present(self.get_root())

    def add_manually(self) -> None:
        dialog = Adw.AlertDialog(heading="Añadir una emisora",
                                 body="El nombre y la dirección del stream (MP3, AAC, M3U8…).")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name = Gtk.Entry(placeholder_text="Nombre")
        url = Gtk.Entry(placeholder_text="https://…", activates_default=True)
        box.append(name)
        box.append(url)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("add", "Añadir")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")
        dialog.set_close_response("cancel")

        def answered(_d: Adw.AlertDialog, response: str) -> None:
            n, u = name.get_text().strip(), url.get_text().strip()
            if response == "add" and n and u.startswith(("http://", "https://")):
                self.add(Station(name=n, streamURL=u))
        dialog.connect("response", answered)
        dialog.present(self.get_root())

    def add(self, station: Station) -> bool:
        added = self.stations.add(station)
        if added:
            self._save()
        return added

    def import_file(self) -> None:
        dialog = Gtk.FileDialog(title="Importar emisoras de MacRadio")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        json_filter = Gtk.FileFilter(name="Emisoras (JSON)")
        json_filter.add_pattern("*.json")
        filters.append(json_filter)
        dialog.set_filters(filters)

        def picked(_d: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                file = dialog.open_finish(result)
            except GLib.Error:
                return
            if file is None or file.get_path() is None:
                return
            try:
                with open(file.get_path(), encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError) as error:
                self._toast(f"No se pudo leer: {error}")
                return
            # La primera importación sustituye a la lista de partida (ver CLAUDE.md).
            first = not StationList.file().exists()
            added = self.stations.import_from(data, replace=first)
            self._save()
            self._toast(f"{added} emisoras importadas")

        dialog.open(self.get_root(), None, picked)

    def _toast(self, text: str) -> None:
        root = self.get_root()
        overlay = getattr(root, "toasts", None)
        if isinstance(overlay, Adw.ToastOverlay):
            overlay.add_toast(Adw.Toast.new(text))


class SearchDialog(Adw.Dialog):
    """Buscar en Radio Browser y añadir con un clic."""

    def __init__(self, sidebar: StationSidebar) -> None:
        super().__init__(title="Buscar emisoras", content_width=560, content_height=600)
        self._sidebar = sidebar
        self._generation = 0
        view = Adw.ToolbarView()
        self.set_child(view)
        view.add_top_bar(Adw.HeaderBar())
        bar = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        view.add_top_bar(bar)
        self.entry = Gtk.SearchEntry(hexpand=True, placeholder_text="Nombre de la emisora")
        self.entry.connect("activate", lambda *_: self._search())
        bar.append(self.entry)
        self.country = Gtk.DropDown.new_from_strings([n for _c, n in COUNTRIES])
        self.country.connect("notify::selected", lambda *_: self._search())
        bar.append(self.country)

        self.stack = Gtk.Stack()
        view.set_content(self.stack)
        self.stack.add_named(Adw.StatusPage(icon_name="system-search-symbolic",
                                            title="Radio Browser",
                                            description="Más de 40.000 emisoras de todo el "
                                                        "mundo. Escribe un nombre o deja el "
                                                        "campo vacío para ver las más votadas."),
                             "hint")
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          valign=Gtk.Align.CENTER)
        loading.append(Adw.Spinner(width_request=32, height_request=32))
        self.stack.add_named(loading, "loading")
        self.error = Adw.StatusPage(icon_name="dialog-warning-symbolic", title="Sin resultados")
        self.stack.add_named(self.error, "error")
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_top=6,
                                margin_bottom=12, margin_start=12, margin_end=12,
                                valign=Gtk.Align.START)
        self.list.add_css_class("boxed-list")
        scroller.set_child(self.list)
        self.stack.add_named(scroller, "list")
        self._search()

    def _search(self) -> None:
        self._generation += 1
        generation = self._generation
        name = self.entry.get_text().strip()
        country = COUNTRIES[self.country.get_selected()][0] or None
        self.stack.set_visible_child_name("loading")

        def work() -> list[Station]:
            if name:
                return catalog.search_stations(name, country)
            return catalog.top_stations(country)

        util.background(work, lambda r: self._show(generation, r),
                        lambda e: self._failed(generation, e))

    def _failed(self, generation: int, error: BaseException) -> None:
        if generation == self._generation:
            self.error.set_title("No se pudo buscar")
            self.error.set_description(str(error))
            self.stack.set_visible_child_name("error")

    def _show(self, generation: int, found: list[Station]) -> None:
        if generation != self._generation:
            return
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        if not found:
            self.error.set_title("Sin resultados")
            self.error.set_description("Prueba con otro nombre u otro país.")
            self.stack.set_visible_child_name("error")
            return
        for station in found:
            row = Adw.ActionRow(title=GLib.markup_escape_text(station.name),
                                subtitle=GLib.markup_escape_text(station.detail))
            row.add_prefix(util.station_avatar(station.name, station.logoURL, 32))
            already = self._sidebar.stations.contains(station)
            button = Gtk.Button(label="Añadida" if already else "Añadir",
                                valign=Gtk.Align.CENTER, sensitive=not already)
            if not already:
                button.add_css_class("suggested-action")

            def add(b: Gtk.Button, s: Station = station) -> None:
                self._sidebar.add(s)
                b.set_label("Añadida")
                b.set_sensitive(False)
                b.remove_css_class("suggested-action")
            button.connect("clicked", add)
            row.add_suffix(button)
            self.list.append(row)
        self.stack.set_visible_child_name("list")
