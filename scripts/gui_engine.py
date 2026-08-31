#!/usr/bin/env python3
"""GTK integration for reviewed external compatibility-engine presets."""

from __future__ import annotations

import threading

import gui as base
from auth.engine_profiles import installed_engine_profile, read_custom_engine_metadata
from updates import (  # noqa: E402
    ENGINE_SELECTION_FILE,
    _apply_game_profile,
    _custom_engine_is_ready,
    fetch_custom_engine,
    install_custom_engine,
)

LUKAS_ENGINE_LABEL = "MCBE GDK v0.2.0-ex — Lukas in-game login"
LUKAS_ENGINE_URL = (
    "https://github.com/veedy-dev/mcbe-gdk-engine/releases/download/"
    "v0.2.0-ex/GDK-Proton10-32-Custom-4.tar.gz"
)
LUKAS_ENGINE_IDENTITY = "veedy-dev/mcbe-gdk-engine@v0.2.0-ex"


class Window(base.Window):
    """Add the reviewed Lukas preset without weakening the normal release UI."""

    def refresh_engine_row(self) -> None:
        installed = base.read_engine_version(base.ROOT) or "not installed"
        selection = self.engine_selection()
        if selection is None:
            subtitle = f"{installed} installed · selection unavailable"
        elif selection == "latest":
            subtitle = f"{installed} installed · tracking latest"
        elif selection == LUKAS_ENGINE_URL:
            subtitle = f"{installed} installed · v0.2.0-ex in-game login selected"
        elif selection.startswith("https://"):
            subtitle = f"{installed} installed · custom GitHub release selected"
        else:
            subtitle = f"{installed} installed · selected {selection}"
        if self.engine_tags_available is False:
            subtitle += " · release list unavailable"
        self.engine_row.set_subtitle(subtitle)

    def populate_engine_combo(self, selected: str) -> None:
        entries = ["Latest", LUKAS_ENGINE_LABEL]
        values = {
            "Latest": "latest",
            LUKAS_ENGINE_LABEL: LUKAS_ENGINE_URL,
        }
        for tag in self.engine_tags[: self.engine_visible_count]:
            entries.append(tag)
            values[tag] = tag

        selected_value = "latest" if selected == "Latest" else selected
        selected_label = next(
            (label for label, value in values.items() if value == selected_value),
            None,
        )
        if selected_label is None:
            selected_label = (
                "Custom GitHub engine"
                if selected_value.startswith("https://")
                else selected_value
            )
            if selected_label not in entries:
                entries.append(selected_label)
            values[selected_label] = selected_value

        if self.engine_visible_count < len(self.engine_tags):
            entries.append(base.ENGINE_LOAD_MORE)
            values[base.ENGINE_LOAD_MORE] = base.ENGINE_LOAD_MORE

        self._engine_entry_values = values
        self.engine_combo.set_model(base.Gtk.StringList.new(entries))
        self.engine_combo.set_selected(entries.index(selected_label))
        self.engine_pending_selection = selected_value

    def engine_combo_changed(self, combo: base.Gtk.DropDown, _param) -> None:
        item = combo.get_selected_item()
        if not item:
            return
        label = item.get_string()
        if label == base.ENGINE_LOAD_MORE:
            self.engine_visible_count += base.ENGINE_PAGE_SIZE
            base.GLib.idle_add(
                self.populate_engine_combo, self.engine_pending_selection
            )
            return
        self.engine_pending_selection = getattr(
            self, "_engine_entry_values", {}
        ).get(label, label)

    def refresh_account(self) -> None:
        try:
            profile = installed_engine_profile(base.ROOT)
            custom = read_custom_engine_metadata(base.ROOT)
        except Exception:
            profile = None
            custom = None

        if profile and profile.authentication == "remote-connect-json":
            self.account_row.set_title("Sign in inside Minecraft")
            self.account_row.set_subtitle(
                "Launch the game, choose Sign In, then complete the Microsoft "
                "device-code prompt."
            )
            self.account_icon.set_from_icon_name("dialog-information-symbolic")
            self.login_button.set_visible(False)
            self.logout_button.set_visible(False)
            return
        if custom:
            self.account_row.set_title("Account managed by custom engine")
            self.account_row.set_subtitle(
                "Use the account controls provided by the selected engine."
            )
            self.account_icon.set_from_icon_name("dialog-information-symbolic")
            self.login_button.set_visible(False)
            self.logout_button.set_visible(False)
            return
        super().refresh_account()

    def confirm_engine_switch(self, button: base.Gtk.Button) -> None:
        selected = self.engine_pending_selection
        if not selected.startswith("https://"):
            super().confirm_engine_switch(button)
            return
        if self.installing or self.updating:
            return
        if base.minecraft_launcher_pid(base.ROOT):
            self.error(
                "Close Minecraft before switching",
                "Engine files cannot be replaced while Minecraft is running.",
            )
            return

        dialog = base.Adw.AlertDialog(
            heading="Use MCBE GDK engine v0.2.0-ex?",
            body=(
                "This installs the project's exact SHA-256-pinned mirror of "
                "Lukas GDK-Proton 10-32-4. Microsoft sign-in happens from "
                "Minecraft's own Sign In button, not from the launcher or CLI. "
                "Parties and Realms are currently unsupported; worlds and "
                "installer account data are preserved."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("switch", "Use engine")
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance(
            "switch", base.Adw.ResponseAppearance.SUGGESTED
        )
        dialog.connect("response", self.engine_switch_response, selected)
        dialog.present(self)

    def engine_switch_response(
        self,
        dialog: base.Adw.AlertDialog,
        response: str,
        selected: str,
    ) -> None:
        if not selected.startswith("https://"):
            super().engine_switch_response(dialog, response, selected)
            return
        if response != "switch":
            return

        self.begin_update_ui(
            "Switching to MCBE GDK engine v0.2.0-ex…",
            "Resolving and verifying the exact mirrored release asset.",
        )

        def worker() -> None:
            try:
                def progress(
                    stage: str,
                    current: int | None,
                    total: int | None,
                ) -> None:
                    self.events.put(("update_progress", stage, current, total))

                with base.runtime_lock(base.ROOT):
                    asset = fetch_custom_engine(selected)
                    if not _custom_engine_is_ready(base.ROOT, asset):
                        install_custom_engine(asset, base.ROOT, progress)
                    base.ROOT.mkdir(parents=True, exist_ok=True)
                    _apply_game_profile(base.ROOT)
                    (base.ROOT / ENGINE_SELECTION_FILE).write_text(
                        selected + "\n", encoding="utf-8"
                    )
                self.events.put(("engine_switch_done", LUKAS_ENGINE_IDENTITY))
            except Exception as exc:
                self.events.put(("engine_switch_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    base.Window = Window
    base.main()
