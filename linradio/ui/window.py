"""La ventana: emisoras a la izquierda; «Ahora» e «Historial» a la derecha."""

from typing import TYPE_CHECKING

from gi.repository import Adw, Gdk, Gio, Gtk

from ..catalog import Station
from ..player import PlayState
from ..session import NowPlaying
from .history_page import HistoryPage
from .now_playing import NowPlayingView
from .stations import StationSidebar

if TYPE_CHECKING:
    from .app import LinRadioApp

CSS = """
.artwork { border-radius: 12px; }
.logo { border-radius: 8px; background: alpha(@view_fg_color, 0.06); }
.logo-initials { font-weight: bold; opacity: 0.6; }
.thumb { border-radius: 6px; }
.play-button { min-width: 52px; min-height: 52px; }
.play-button image { -gtk-icon-size: 24px; }
.lyrics { background: transparent; }
.lyrics row { padding: 4px 12px; border-radius: 8px; }
.lyric-line { font-size: 1.15em; opacity: 0.55; transition: opacity 200ms; }
.lyric-line.current { opacity: 1; font-weight: bold; font-size: 1.3em; }
.favorite, togglebutton.circular:checked { color: #e01b24; }
"""


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: "LinRadioApp") -> None:
        super().__init__(application=app, title="LinRadio", default_width=1000,
                         default_height=720)
        self.set_size_request(360, 480)
        self.app = app

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.split = Adw.NavigationSplitView(min_sidebar_width=240, max_sidebar_width=320)
        self.toasts.set_child(self.split)

        # Barra lateral
        side_view = Adw.ToolbarView()
        side_header = Adw.HeaderBar()
        side_header.set_title_widget(Adw.WindowTitle(title="Emisoras"))
        add_menu = Gio.Menu()
        add_menu.append("Buscar en Radio Browser…", "app.add-search")
        add_menu.append("Añadir a mano…", "app.add-manual")
        add_menu.append("Importar de MacRadio…", "app.import")
        side_header.pack_start(Gtk.MenuButton(icon_name="list-add-symbolic", menu_model=add_menu,
                                              tooltip_text="Añadir emisoras"))
        side_view.add_top_bar(side_header)
        self.sidebar = StationSidebar(app.stations, self._play_station, app.stations_changed)
        side_view.set_content(self.sidebar)
        self.split.set_sidebar(Adw.NavigationPage(child=side_view, title="Emisoras"))

        # Contenido
        content_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        menu = Gio.Menu()
        menu.append("Seguir sonando al cerrar la ventana", "app.background")
        menu.append("Atajos de teclado", "win.show-help-overlay")
        menu.append("Acerca de LinRadio", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       primary=True, tooltip_text="Menú"))
        content_view.add_top_bar(header)
        self.now_view = NowPlayingView(app.session, app.toggle, app.step, app.set_volume)
        self.now_view.volume.set_value(app.settings.get("volume", 1.0))
        self.stack.add_titled_with_icon(self.now_view, "now", "Ahora",
                                        "media-playback-start-symbolic")
        self.history_page = HistoryPage(app.history, self._history_changed)
        self.stack.add_titled_with_icon(self.history_page, "history", "Historial",
                                        "document-open-recent-symbolic")
        self.stack.connect("notify::visible-child-name", lambda *_: self._page_changed())
        content_view.set_content(self.stack)
        bottom = Adw.ViewSwitcherBar(stack=self.stack)
        content_view.add_bottom_bar(bottom)
        self.content_page = Adw.NavigationPage(child=content_view, title="LinRadio")
        self.split.set_content(self.content_page)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        breakpoint.add_setter(self.split, "collapsed", True)
        breakpoint.add_setter(switcher, "policy", Adw.ViewSwitcherPolicy.NARROW)
        breakpoint.add_setter(bottom, "reveal", True)
        self.add_breakpoint(breakpoint)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_key(self, _c: Gtk.EventControllerKey, keyval: int, _code: int,
                state: Gdk.ModifierType) -> bool:
        focus = self.get_focus()
        if keyval == Gdk.KEY_space and not isinstance(focus, (Gtk.Editable, Gtk.Text)):
            self.app.toggle()
            return True
        return False

    def _play_station(self, station: Station) -> None:
        self.app.play(station)
        self.split.set_show_content(True)
        self.stack.set_visible_child_name("now")

    def _history_changed(self) -> None:
        self.app.session.now.favorite = bool(
            self.app.session.now.history_id and
            (song := self.app.history.get(self.app.session.now.history_id)) and song.favorite)
        self.now_view.show(self.app.session.now)

    def _page_changed(self) -> None:
        if self.stack.get_visible_child_name() == "history":
            self.history_page.refresh()

    # --- Avisos de la app ------------------------------------------------------------

    def show_now(self, now: NowPlaying) -> None:
        self.now_view.show(now)
        self.sidebar.mark_playing(now.station.id if now.station and
                                  self.app.player.state is not PlayState.STOPPED else None)
        title = now.title
        self.content_page.set_title(title.track if title else
                                    (now.station.name if now.station else "LinRadio"))
        if self.stack.get_visible_child_name() == "history":
            self.history_page.refresh()

    def show_state(self, state: PlayState, detail: str) -> None:
        self.now_view.set_player_state(state, detail)
        now = self.app.session.now
        self.sidebar.mark_playing(now.station.id if now.station and
                                  state is not PlayState.STOPPED else None)

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(text))
