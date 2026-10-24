"""設定画面（ui.html の中の settings.js）から呼ばれる窓口。

bridge.py とは別の名前（settings）で QWebChannel に載せる。bridge.py は登録・一覧・
更新・初回設定で手一杯なので、見た目と常駐の好みはこちらにまとめる。

どの口も、何が起きても JSON を返し切る。例外が外へ出ると QWebChannel は
コールバックを呼ばず、画面は押したまま固まって見える。
"""
import json
import threading

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

import appconfig
import backdrop
import hotkey
import layout
import prefs
import startup


def _ok(**fields) -> str:
    return json.dumps({'ok': True, **fields}, ensure_ascii=False)


def _ng(error: str) -> str:
    return json.dumps({'ok': False, 'error': error}, ensure_ascii=False)


class SettingsBridge(QObject):
    # 自動起動の状態。確かめるのに PowerShell で 1〜2 秒かかるので、裏で調べてここから返す。
    autostartState = pyqtSignal(str)

    def __init__(self, window, view, hotkeys: hotkey.Manager) -> None:
        super().__init__()
        self._window  = window
        self._view    = view
        self._hotkeys = hotkeys
        # 押し続けられても PowerShell を並べて走らせない。登録と解除が入れ違うと、
        # 画面の表示と実際の状態がずれる。
        self._autostart_lock = threading.Lock()

    # ── 読み出し ──────────────────────────────────────────────

    @pyqtSlot(result=str)
    def loadSettings(self) -> str:
        try:
            cfg     = appconfig.load_config()
            current = self._hotkeys.current or hotkey.DEFAULT
            return _ok(zoom=prefs.zoom_of(cfg), zoom_steps=list(prefs.ZOOM_STEPS),
                       corner=prefs.corner_of(cfg), wide_scope=prefs.wide_scope_of(cfg),
                       hotkey={**hotkey.to_config(current), 'label': hotkey.label(current),
                               'fell_back': self._hotkeys.fell_back})
        except Exception as e:
            appconfig.log(f'警告: 設定を読めませんでした ({e})')
            return _ng('設定を読めませんでした')

    # ── 見た目 ────────────────────────────────────────────────

    def _save(self, change, what: str) -> bool:
        """読み直してから直す。他の経路の変更（★やリストの出し入れ）を巻き戻さない。"""
        try:
            appconfig.update_config(change)
        except Exception as e:
            appconfig.log(f'警告: {what}を保存できませんでした ({e})')
            return False
        return True

    def _apply_geometry(self) -> None:
        """いまの倍率と隅で、窓を置き直す。設定画面は入力画面と同じ大きさで出す。

        ここで失敗しても設定は保存できているので、例外は持ち上げない（持ち上げると
        画面に返事が届かず、押したまま固まって見える）。次に窓を出すときに直る。
        """
        try:
            w, h = layout.view_size(False)
            self._window.setFixedSize(w, h)
            layout.position_window(self._window, w, h)
            # 大きさや場所が変われば背後に来るものも変わる。移動し終えてから撮る。
            backdrop.push(self._window, self._view, w, h, hide_self=True)
        except Exception as e:
            appconfig.log(f'警告: 窓を置き直せませんでした ({e})')

    @pyqtSlot(str, result=str)
    def setZoom(self, value: str) -> str:
        zoom = prefs.as_zoom(value)
        if zoom is None:
            return _ng('その大きさは選べません')
        if not self._save(lambda cfg: prefs.set_zoom(cfg, zoom), '文字の大きさ'):
            return _ng('保存できませんでした')
        layout.set_zoom(zoom)
        self._view.setZoomFactor(zoom)
        self._apply_geometry()
        appconfig.log(f'文字の大きさを変えました（{zoom} 倍）')
        return _ok(zoom=zoom)

    @pyqtSlot(str, result=str)
    def setCorner(self, corner: str) -> str:
        if corner not in prefs.CORNERS:
            return _ng('その位置は選べません')
        if not self._save(lambda cfg: prefs.set_corner(cfg, corner), '窓の位置'):
            return _ng('保存できませんでした')
        layout.set_corner(corner)
        self._apply_geometry()
        appconfig.log(f'窓を出す位置を変えました（{corner}）')
        return _ok(corner=corner)

    @pyqtSlot(str, result=str)
    def setWideScope(self, scope: str) -> str:
        if scope not in prefs.WIDE_SCOPES:
            return _ng('そのタブは選べません')
        if not self._save(lambda cfg: prefs.set_wide_scope(cfg, scope), '最初のタブ'):
            return _ng('保存できませんでした')
        appconfig.log(f'一覧の最初のタブを変えました（{scope}）')
        return _ok(wide_scope=scope)

    # ── ホットキー ────────────────────────────────────────────

    @pyqtSlot(str, int, result=str)
    def setHotkey(self, mods_csv: str, vk: int) -> str:
        """キーを付け替える。登録できたものだけを保存する。

        GUI スレッドのまま登録すること（hotkey.py の冒頭を参照）。ここをスレッドに
        逃がすと、新しいキーは何の知らせもなく二度と反応しなくなる。
        """
        spec = hotkey.make_spec(str(mods_csv or '').split(','), vk)
        if spec is None:
            return _ng('Ctrl か Alt と組み合わせた、英数字・F1〜F12・Space などにしてください')
        try:
            ok, err = self._hotkeys.rebind(spec)
        except Exception as e:
            appconfig.log(f'警告: ホットキーの付け替えでつまずきました ({e})')
            return _ng('そのキーは登録できませんでした')
        if not ok:
            appconfig.log(f'ホットキーを {hotkey.label(spec)} にできませんでした (Win32 error={err})')
            return _ng(hotkey.error_text(err))
        self._hotkeys.fell_back = False
        name = hotkey.label(spec)
        if not self._save(lambda cfg: hotkey.set_hotkey(cfg, spec), 'ホットキー'):
            return _ok(label=name, note='保存できなかったので、次に立ち上げたときは元のキーに戻ります')
        appconfig.log(f'ホットキーを {name} に変えました')
        return _ok(label=name, **hotkey.to_config(spec))

    # ── 自動起動 ──────────────────────────────────────────────

    @pyqtSlot()
    def loadAutostart(self) -> None:
        threading.Thread(target=self._autostart_worker, args=(None,), daemon=True).start()

    @pyqtSlot(bool)
    def setAutostart(self, enabled: bool) -> None:
        threading.Thread(target=self._autostart_worker, args=(bool(enabled),), daemon=True).start()

    def _autostart_worker(self, enabled: bool | None) -> None:
        """裏で切り替え（enabled が None なら調べるだけ）、結果を必ず画面へ返す。"""
        with self._autostart_lock:
            try:
                payload = self._autostart(enabled)
            except Exception as e:
                appconfig.log(f'警告: 自動起動の切り替えでつまずきました ({e})')
                payload = _ng('自動起動を確かめられませんでした')
        self.autostartState.emit(payload)

    @staticmethod
    def _autostart(enabled: bool | None) -> str:
        note = ''
        if enabled is True:
            ok, note = startup.enable_all()
            if not ok:
                return _ng(f'自動起動を登録できませんでした（{note}）')
        elif enabled is False:
            ok, note = startup.disable_all()
            if not ok:
                return _ng(note)
        return _ok(note=note, **startup.status())
