"""リスト・担当者の欄に入ったとき、IME を半角英数へ切り替える。

リスト名も担当者名もアルファベットで登録されているので、そこへ入った瞬間から
英字で打ち始めたい。

元のモードへ戻す処理は入れていない。閉じた後に戻そうとしても効かず
（フォーカスが web 側へ返るときに Chromium が入力モードを引き直すためと見られる）、
利用者と相談のうえ「戻さなくてよい」と決めたため。

CSS の ime-mode は Chromium が解釈しないので Win32 の IMM32 を直に叩く。
ウィンドウごと IME を切る (ImmAssociateContext(NULL)) 手もあるが、それだと
同じ描画面にあるタスク名・メモまで日本語が打てなくなるので使わない。
"""
import ctypes
import ctypes.wintypes as wt

_imm32  = ctypes.WinDLL('imm32', use_last_error=True)
_user32 = ctypes.WinDLL('user32', use_last_error=True)

_imm32.ImmGetContext.argtypes = [wt.HWND]
_imm32.ImmGetContext.restype  = wt.HANDLE
_imm32.ImmGetConversionStatus.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD)]
_imm32.ImmGetConversionStatus.restype  = wt.BOOL
_imm32.ImmSetConversionStatus.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD]
_imm32.ImmSetConversionStatus.restype  = wt.BOOL
_imm32.ImmReleaseContext.argtypes = [wt.HWND, wt.HANDLE]
_imm32.ImmReleaseContext.restype  = wt.BOOL

_user32.GetFocus.restype = wt.HWND

# 変換モードのビット。0 が「半角英数」。
IME_CMODE_ALPHANUMERIC = 0x0000


def _candidate_hwnds(fallback: int) -> tuple[int, ...]:
    """IME コンテキストを持っていそうなウィンドウを、近いものから並べる。

    QtWebEngine は描画面を子ウィンドウに持つので、最上位ではなく
    実際にキーボードフォーカスがある方を先に見る。

    GetFocus は呼び出したスレッドが持つウィンドウしか返さないので、
    ここに他のアプリのウィンドウが混じることはない。GetForegroundWindow は
    使わない（フォーカスが外れているときに、無関係なアプリの IME を
    切り替えてしまうため）。
    """
    found = (_user32.GetFocus(), fallback)
    seen: list[int] = []
    for hwnd in found:
        h = int(hwnd or 0)
        if h and h not in seen:
            seen.append(h)
    return tuple(seen)


def _open_context(fallback: int) -> tuple[int, int] | None:
    for hwnd in _candidate_hwnds(fallback):
        himc = _imm32.ImmGetContext(wt.HWND(hwnd))
        if himc:
            return hwnd, himc
    return None


def read_mode(fallback_hwnd: int) -> tuple[int, int] | None:
    """(変換モード, 文節モード) を返す。IME が無いときは None。"""
    ctx = _open_context(fallback_hwnd)
    if ctx is None:
        return None
    hwnd, himc = ctx
    conv, sentence = wt.DWORD(), wt.DWORD()
    ok = _imm32.ImmGetConversionStatus(himc, ctypes.byref(conv), ctypes.byref(sentence))
    _imm32.ImmReleaseContext(wt.HWND(hwnd), himc)
    return (conv.value, sentence.value) if ok else None


def apply_mode(fallback_hwnd: int, conversion: int, sentence: int) -> bool:
    ctx = _open_context(fallback_hwnd)
    if ctx is None:
        return False
    hwnd, himc = ctx
    ok = _imm32.ImmSetConversionStatus(himc, wt.DWORD(conversion), wt.DWORD(sentence))
    _imm32.ImmReleaseContext(wt.HWND(hwnd), himc)
    return bool(ok)


def to_alphanumeric(fallback_hwnd: int) -> bool:
    """半角英数へ切り替える。IME が無い環境では何もせず False を返す。"""
    current = read_mode(fallback_hwnd)
    if current is None:
        return False
    if current[0] == IME_CMODE_ALPHANUMERIC:
        return True                      # すでに英数。触らない
    return apply_mode(fallback_hwnd, IME_CMODE_ALPHANUMERIC, current[1])
