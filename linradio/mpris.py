"""MPRIS por D-Bus (`org.mpris.MediaPlayer2.linradio`): GNOME pone los controles y la
carátula en el menú del sistema y la pantalla de bloqueo, y lleva las teclas multimedia."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gi.repository import Gio, GLib

BUS_NAME = "org.mpris.MediaPlayer2.linradio"
PATH = "/org/mpris/MediaPlayer2"

XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/><arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


def _soon(callback: Callable[[], None]) -> None:
    """En el hilo principal, cuando la llamada de D-Bus ya ha contestado."""
    def once() -> bool:
        callback()
        return False
    GLib.idle_add(once)


@dataclass
class Controls:
    play: Callable[[], None]
    pause: Callable[[], None]
    toggle: Callable[[], None]
    next: Callable[[], None]
    previous: Callable[[], None]
    raise_window: Callable[[], None]
    quit: Callable[[], None]
    set_volume: Callable[[float], None]


class Mpris:
    def __init__(self, controls: Controls, desktop_entry: str) -> None:
        self._controls = controls
        self._desktop = desktop_entry
        self._connection: Gio.DBusConnection | None = None
        self._ids: list[int] = []
        self._status = "Stopped"
        self._metadata: dict[str, GLib.Variant] = {}
        self._volume = 1.0
        self._owner = Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME,
                                       Gio.BusNameOwnerFlags.NONE,
                                       self._on_bus, None, None)

    def _on_bus(self, connection: Gio.DBusConnection, _name: str) -> None:
        self._connection = connection
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        for interface in info.interfaces:
            self._ids.append(connection.register_object(
                PATH, interface, self._on_call, self._on_get, self._on_set))

    def close(self) -> None:
        if self._connection is not None:
            for registration in self._ids:
                self._connection.unregister_object(registration)
        Gio.bus_unown_name(self._owner)

    # --- Lo que cambia la app ----------------------------------------------------------

    def update(self, playing: bool, stopped: bool, title: str | None, artist: str | None,
               album: str | None, art_url: str | None, track_id: str) -> None:
        self._status = "Stopped" if stopped else ("Playing" if playing else "Paused")
        metadata: dict[str, GLib.Variant] = {
            "mpris:trackid": GLib.Variant("o", f"/io/github/baltamir1978/LinRadio/{track_id}"),
        }
        if title:
            metadata["xesam:title"] = GLib.Variant("s", title)
        if artist:
            metadata["xesam:artist"] = GLib.Variant("as", [artist])
        if album:
            metadata["xesam:album"] = GLib.Variant("s", album)
        if art_url:
            metadata["mpris:artUrl"] = GLib.Variant("s", art_url)
        self._metadata = metadata
        self._changed({"PlaybackStatus": GLib.Variant("s", self._status),
                       "Metadata": GLib.Variant("a{sv}", self._metadata)})

    def set_volume(self, value: float) -> None:
        self._volume = value
        self._changed({"Volume": GLib.Variant("d", value)})

    def _changed(self, values: dict[str, GLib.Variant]) -> None:
        if self._connection is None:
            return
        self._connection.emit_signal(
            None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
            GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", values, [])))

    # --- D-Bus -------------------------------------------------------------------------

    def _on_call(self, _conn: Gio.DBusConnection, _sender: str, _path: str, _iface: str,
                 method: str, _params: GLib.Variant,
                 invocation: Gio.DBusMethodInvocation) -> None:
        c = self._controls
        actions: dict[str, Callable[[], None]] = {
            "Raise": c.raise_window, "Quit": c.quit, "Next": c.next, "Previous": c.previous,
            "Pause": c.pause, "Stop": c.pause, "PlayPause": c.toggle, "Play": c.play,
        }
        action = actions.get(method)
        invocation.return_value(None)
        if os.environ.get("LINRADIO_DEBUG"):
            print(f"MPRIS {method} desde {_sender}", flush=True)
        if action is not None:
            _soon(action)

    def _on_get(self, _conn: Gio.DBusConnection, _sender: str, _path: str, _iface: str,
                name: str) -> GLib.Variant | None:
        values: dict[str, Any] = {
            "CanQuit": ("b", True), "CanRaise": ("b", True), "HasTrackList": ("b", False),
            "Identity": ("s", "LinRadio"), "DesktopEntry": ("s", self._desktop),
            "SupportedUriSchemes": ("as", []), "SupportedMimeTypes": ("as", []),
            "PlaybackStatus": ("s", self._status), "Rate": ("d", 1.0),
            "Metadata": ("a{sv}", self._metadata), "Volume": ("d", self._volume),
            "Position": ("x", 0), "MinimumRate": ("d", 1.0), "MaximumRate": ("d", 1.0),
            "CanGoNext": ("b", True), "CanGoPrevious": ("b", True), "CanPlay": ("b", True),
            "CanPause": ("b", True), "CanSeek": ("b", False), "CanControl": ("b", True),
        }
        found = values.get(name)
        return GLib.Variant(*found) if found else None

    def _on_set(self, _conn: Gio.DBusConnection, _sender: str, _path: str, _iface: str,
                name: str, value: GLib.Variant) -> bool:
        if name == "Volume":
            volume = max(0.0, min(1.0, value.get_double()))
            _soon(lambda: self._controls.set_volume(volume))
            return True
        return name == "Rate"
