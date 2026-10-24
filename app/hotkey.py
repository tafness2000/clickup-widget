"""呼び出しのホットキー。何のキーにするかの決まりと、Windows への登録・付け替え。

キーは設定画面で変えられる。変えたい理由はたいてい「他のアプリと取り合っている」
なので、付け替えは必ず新しいキーを先に登録し、通ってから古いほうを外す。
逆の順だと、新しいキーが取れなかったときに呼び出す手立てが無くなる。

RegisterHotKey は呼んだスレッドにしか WM_HOTKEY を届けない。登録も付け替えも
GUI スレッド（Qt のメッセージループが回っているところ）でやること。
ワーカースレッドで登録すると、エラーにもならずに二度と反応しなくなる。
"""
import ctypes
import ctypes.wintypes
from typing import Callable, NamedTuple

from PyQt6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312

# Win32 の修飾キー。Windows キーは OS が先に取るので選ばせない。
MOD_BITS  = {'ctrl': 0x0002, 'alt': 0x0001, 'shift': 0x0004}
MOD_ORDER = ('ctrl', 'alt', 'shift')          # 表示と保存の並び
MOD_NAMES = {'ctrl': 'Ctrl', 'alt': 'Alt', 'shift': 'Shift'}

# 割り当ててよいキー。Enter・Tab・Esc・BackSpace は画面の中で使っているので外す。
VK_SPACE = 0x20
_SPECIAL = {0x20: 'Space', 0x21: 'PageUp', 0x22: 'PageDown', 0x23: 'End',
            0x24: 'Home', 0x2D: 'Insert', 0x2E: 'Delete'}
ALLOWED_VK = frozenset({*_SPECIAL,
                        *range(0x30, 0x3A),     # 0-9
                        *range(0x41, 0x5B),     # A-Z
                        *range(0x70, 0x7C)})    # F1-F12

# 他のアプリが同じ組み合わせを先に登録している。
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# 付け替えのとき、新旧を同時に持つために 2 つの番号を交互に使う。
HOTKEY_IDS = (1, 2)


class Spec(NamedTuple):
    mods: frozenset
    vk: int


DEFAULT = Spec(frozenset({'ctrl', 'shift'}), VK_SPACE)

# 登録できてしまうが、奪うと困る Windows の決まりごと（Alt+F4 で窓を閉じる）。
RESERVED = frozenset({Spec(frozenset({'alt'}), 0x73)})


def key_name(vk: int) -> str:
    if vk in _SPECIAL:
        return _SPECIAL[vk]
    if 0x70 <= vk <= 0x7B:
        return f'F{vk - 0x6F}'
    return chr(vk)


def label(spec: Spec) -> str:
    """'Ctrl+Shift+Space' の形。画面とログに出す。"""
    mods = [MOD_NAMES[m] for m in MOD_ORDER if m in spec.mods]
    return '+'.join([*mods, key_name(spec.vk)])


def is_valid(spec: Spec) -> bool:
    """割り当ててよい組み合わせか。

    Ctrl か Alt を必ず含める。Shift だけや修飾なしだと、ふつうに文字を打っただけで
    どのアプリにいても窓が飛び出し、その文字は打った先に届かなくなる。
    """
    return (spec.vk in ALLOWED_VK
            and spec.mods <= set(MOD_BITS)
            and bool(spec.mods & {'ctrl', 'alt'})
            and spec not in RESERVED)


def make_spec(mods, vk) -> Spec | None:
    """外から来た値（設定ファイルや画面）を組み立てる。組めない・使えないものは None。"""
    try:
        spec = Spec(frozenset(str(m).strip().lower() for m in mods if str(m).strip()), int(vk))
    except (TypeError, ValueError, OverflowError):   # json の 1e999 は inf になり int() で溢れる
        return None
    return spec if is_valid(spec) else None


def spec_of(cfg: dict) -> Spec:
    """保存してあるキー。無い・壊れているときは既定（Ctrl+Shift+Space）。"""
    saved = cfg.get('hotkey')
    if not isinstance(saved, dict):
        return DEFAULT
    return make_spec(saved.get('mods') or [], saved.get('vk')) or DEFAULT


def to_config(spec: Spec) -> dict:
    return {'mods': [m for m in MOD_ORDER if m in spec.mods], 'vk': spec.vk}


def set_hotkey(cfg: dict, spec: Spec) -> dict:
    """キーを差し替えた新しい設定を返す。"""
    return {**cfg, 'hotkey': to_config(spec)}


def error_text(err: int) -> str:
    if err == ERROR_HOTKEY_ALREADY_REGISTERED:
        return 'そのキーは他のアプリが使っています'
    return f'そのキーは登録できませんでした（Win32 error={err}）'


# ── Windows への登録 ─────────────────────────────────────────

_user32 = ctypes.WinDLL('user32', use_last_error=True)


def _win_register(hotkey_id: int, spec: Spec) -> tuple[bool, int]:
    bits = sum(MOD_BITS[m] for m in spec.mods)
    ok   = bool(_user32.RegisterHotKey(None, hotkey_id, bits, spec.vk))
    return ok, (0 if ok else ctypes.get_last_error())


def _win_unregister(hotkey_id: int) -> None:
    _user32.UnregisterHotKey(None, hotkey_id)


class Manager:
    """いま登録しているキーを 1 つだけ持つ。

    登録と解除の関数は差し替えられる（テストで Windows に触らずに確かめるため）。
    """

    def __init__(self, register: Callable = _win_register,
                 unregister: Callable = _win_unregister) -> None:
        self._register   = register
        self._unregister = unregister
        self._id: int | None = None
        self.current: Spec | None = None
        # 保存してあったキーが取れず、既定に戻して動いているか。設定画面で知らせる。
        self.fell_back = False

    def rebind(self, spec: Spec) -> tuple[bool, int]:
        """spec に付け替える。(できたか, 失敗時の Win32 エラーコード)。

        新しいほうを別の番号で先に取り、通ってから古いほうを外す。取れなければ
        古いキーはそのまま生きている。同じキーを選び直したときは何もしない
        （自分の登録とぶつかって 1409 になるため）。
        """
        if spec == self.current and self._id is not None:
            return True, 0
        new_id = HOTKEY_IDS[1] if self._id == HOTKEY_IDS[0] else HOTKEY_IDS[0]
        ok, err = self._register(new_id, spec)
        if not ok:
            return False, err
        if self._id is not None:
            self._unregister(self._id)
        self._id, self.current = new_id, spec
        return True, 0

    def start(self, saved: Spec) -> tuple[bool, int]:
        """起動時の登録。保存してあったキーが取れなければ既定に戻す。

        戻さないと、他のアプリに取られたキーを保存したままでは二度と呼び出せず、
        設定画面にもたどり着けない。
        """
        ok, err = self.rebind(saved)
        if ok or saved == DEFAULT:
            return ok, err
        fallback_ok, _ = self.rebind(DEFAULT)
        self.fell_back = fallback_ok
        return False, err

    def matches(self, hotkey_id: int) -> bool:
        return self._id is not None and hotkey_id == self._id

    def release(self) -> None:
        if self._id is not None:
            self._unregister(self._id)
        self._id = None


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: Manager, on_press: Callable[[], None]) -> None:
        super().__init__()
        self._manager  = manager
        self._on_press = on_press

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_generic_MSG':
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and self._manager.matches(msg.wParam):
                self._on_press()
        return False, 0
