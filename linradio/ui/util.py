"""Piezas comunes: trabajo en segundo plano, imágenes de red y etiquetas."""

import threading
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

from gi.repository import Gdk, GLib, Gtk, Pango

from .. import USER_AGENT

T = TypeVar("T")


def on_main(callback: Callable[..., Any], *args: Any) -> None:
    def once() -> bool:
        callback(*args)
        return False
    GLib.idle_add(once)


def background(work: Callable[[], T], done: Callable[[T], None] | None = None,
               failed: Callable[[BaseException], None] | None = None) -> None:
    def runner() -> None:
        try:
            result = work()
        except BaseException as error:  # noqa: BLE001
            if failed is not None:
                on_main(failed, error)
            return
        if done is not None:
            on_main(done, result)
    threading.Thread(target=runner, daemon=True).start()


class Images:
    """Logos y carátulas bajados una vez y guardados en memoria."""

    LIMIT = 200

    def __init__(self) -> None:
        self._cache: OrderedDict[str, Gdk.Texture | None] = OrderedDict()
        self._waiting: dict[str, list[Callable[[Gdk.Texture | None], None]]] = {}
        self._lock = threading.Lock()

    def load(self, url: str | None, callback: Callable[[Gdk.Texture | None], None]) -> None:
        if not url:
            callback(None)
            return
        with self._lock:
            if url in self._cache:
                texture = self._cache[url]
                self._cache.move_to_end(url)
                hit = True
            else:
                hit = False
                if url in self._waiting:
                    self._waiting[url].append(callback)
                    return
                self._waiting[url] = [callback]
        if hit:
            callback(texture)
            return

        def fetch() -> bytes:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                data: bytes = response.read(8 * 1024 * 1024)
                return data

        def finish(texture: Gdk.Texture | None) -> None:
            with self._lock:
                self._cache[url] = texture
                while len(self._cache) > self.LIMIT:
                    self._cache.popitem(last=False)
                callbacks = self._waiting.pop(url, [])
            for cb in callbacks:
                cb(texture)

        def ready(data: bytes) -> None:
            try:
                finish(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
            except GLib.Error:
                finish(None)     # formato que GTK no abre (algún .webp, un .ico raro)

        background(fetch, ready, lambda _e: finish(None))


IMAGES = Images()


def label(text: str = "", css: tuple[str, ...] = (), xalign: float = 0.0,
          wrap: bool = False, ellipsize: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign)
    for name in css:
        widget.add_css_class(name)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    return widget


def icon_button(icon: str, tooltip: str, css: tuple[str, ...] = ("flat",)) -> Gtk.Button:
    button = Gtk.Button.new_from_icon_name(icon)
    button.set_tooltip_text(tooltip)
    button.set_valign(Gtk.Align.CENTER)
    for name in css:
        button.add_css_class(name)
    return button


def station_avatar(name: str, url: str | None, size: int) -> Gtk.Widget:
    """El logo de la emisora en un cuadrado redondeado o, mientras no llega (o si no hay),
    sus iniciales. Los logos no se recortan en círculo: muchos son apaisados."""
    stack = Gtk.Stack(width_request=size, height_request=size, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER)
    stack.add_css_class("logo")
    stack.set_overflow(Gtk.Overflow.HIDDEN)
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "?"
    text = Gtk.Label(label=initials)
    text.add_css_class("logo-initials")
    if size >= 96:
        text.add_css_class("title-1")
    stack.add_named(text, "initials")
    image = Gtk.Image(pixel_size=size)
    stack.add_named(image, "picture")
    if url:
        def show(texture: Gdk.Texture | None) -> None:
            if texture is not None:
                image.set_from_paintable(texture)
                stack.set_visible_child_name("picture")
        IMAGES.load(url, show)
    return stack
