"""すりガラスの下地。

ウィンドウ自体を透過させてすりガラスにはできない。QtWebEngine を GPU 合成なしで
動かしている（pause.pyw 冒頭の d3d11 クラッシュ回避）と描画面が常に不透明になり、
WA_TranslucentBackground も DWM のアクリルも効かないため。
そこで背後を撮り、ぼかして敷くことで同じ見た目を作る。ぼかし自体は CSS の filter に任せる。

pause.pyw と bridge.py の両方から呼ぶので、ここに分けてある。bridge.py から pause.pyw を
読み込むと、pause.pyw が Bridge を読み込んでいるぶんと circular import になる。
"""
import ctypes
import ctypes.wintypes
import json

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtWidgets import QApplication

from appconfig import log

# 背後キャプチャの縮小率。粗く縮めるほど軽く、CSS 側で引き伸ばす分だけぼけ方も滑らかになる。
SCALE = 10

# 自分の窓だけをキャプチャの対象から外す指定。画面に映っている絵は変わらないので、
# 利用者からは何も起きていないように見える。Windows 10 2004 より前には無い。
WDA_NONE               = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011

# 同じ警告を窓を出すたびに書かない。log が埋まって他の行が読めなくなる。
_warned = frozenset()


def _warn_once(key: str, message: str) -> None:
    global _warned
    if key in _warned:
        return
    _warned = _warned | {key}
    log(message)


def data_uri(x: int, y: int, w: int, h: int) -> str:
    """指定領域（論理座標）の画面を縮小した PNG の data URI にして返す。"""
    shot  = QApplication.primaryScreen().grabWindow(0, x, y, w, h)
    small = shot.toImage().scaled(
        max(w // SCALE, 1), max(h // SCALE, 1),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    small.save(buf, 'PNG')
    return 'data:image/png;base64,' + bytes(buf.data().toBase64()).decode('ascii')


def _set_affinity(hwnd: int, value: int) -> bool:
    try:
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(
            ctypes.wintypes.HWND(hwnd), ctypes.c_uint(value)))
    except Exception:
        return False


def _flush_dwm() -> bool:
    """DWM が次の合成を終えるまで待つ。

    これを挟まないと、対象から外したはずの自分がまだ写っている絵を撮ることがある。
    """
    try:
        return ctypes.WinDLL('dwmapi').DwmFlush() == 0
    except Exception:
        return False


def _restore_capture(hwnd: int) -> None:
    """外した指定を戻す。

    戻し損ねると、この窓は利用者自身のスクリーンショットにも、画面共有にも、
    録画にも写らないまま固定される。しかも画面に出ている絵は何も変わらないので、
    気づく手がかりが無い。失敗したら一度やり直し、それでも駄目なら log に残す。
    """
    if _set_affinity(hwnd, WDA_NONE):
        return
    if _set_affinity(hwnd, WDA_NONE):
        _warn_once('restore_retry', '警告: キャプチャの除外を戻すのに一度失敗しました（やり直して戻せました）')
        return
    _warn_once('restore', '警告: キャプチャの除外を戻せませんでした。'
                          'このウィジットが画面共有や録画に写らない状態になっているかもしれません。'
                          '一度終了して立ち上げ直すと直ります')


def _capture_excluding_self(hwnd: int, x: int, y: int, w: int, h: int) -> str:
    """出ている最中に、自分を写さずに背後を撮る。

    隠してから撮る手もあるが、hide → show を挟むと描画面の作り直しが間に合わず、
    中身が描かれないまま出ることがある。表示はそのままに、キャプチャからだけ外す。

    外している間は自分のキャプチャだけでなく、画面共有や録画からもこの窓が消える。
    撮り終えるまでの 1〜2 フレームだけなので相手には見えないはずだが、外す時間は
    短いほどよい。撮る直前に外し、撮り終えたらすぐ戻す。

    撮れる見込みが立たないときは空文字を返す。自分が写り込んだ絵を敷くより、
    前の絵をそのまま残す方がましなため。
    """
    if not _set_affinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
        _warn_once('affinity', '警告: 背景を撮り直せません'
                               '（この Windows では自分をキャプチャから外せません）。前の背景のままにします')
        return ''
    try:
        if not _flush_dwm():
            _warn_once('dwmflush', '警告: 背景を撮り直せません'
                                   '（DwmFlush が使えません）。前の背景のままにします')
            return ''
        return data_uri(x, y, w, h)
    finally:
        # 例外が出ても必ず戻す。戻せたかどうかまで見る。
        _restore_capture(hwnd)


def push(win, view, w: int, h: int, hide_self: bool = False) -> None:
    """表示位置の背後を撮って画面へ渡す。失敗しても表示は続行する。

    hide_self は「もう出ている状態で撮り直すとき」に立てる。引っ込んでいる間に撮るなら
    自分は写らないので要らない。
    """
    try:
        pos = win.pos()
        uri = (_capture_excluding_self(int(win.winId()), pos.x(), pos.y(), w, h)
               if hide_self else data_uri(pos.x(), pos.y(), w, h))
    except Exception as e:
        log(f'警告: 背景のキャプチャに失敗しました ({e})')
        return
    if not uri:
        return          # 撮れなかった。前の絵をそのまま使う
    view.page().runJavaScript(
        f'typeof setBackdrop==="function" && setBackdrop({json.dumps(uri)})')
