import ctypes
import ctypes.wintypes
import json
import os
import re
import sys
import threading
import traceback

# GPU (Direct3D) 描画を回避してソフトウェアレンダリングに固定する。
# 2026-07-15 の Windows Update で d3d11.dll が 10.0.26100.8737 に更新されて以降、
# アクセス違反 (0xc0000005) を起こし常駐ごと落ちるようになったため。
# Chromium 側 (QTWEBENGINE_CHROMIUM_FLAGS) と Qt 本体側 (QT_OPENGL) の両方を
# 切り替えないと、Qt が ANGLE 経由で d3d11.dll を掴んでしまう。
# PyQt6 の import より前に設定しないと反映されない。
os.environ.setdefault(
    'QTWEBENGINE_CHROMIUM_FLAGS',
    '--disable-gpu --disable-gpu-compositing --use-angle=swiftshader',
)
os.environ.setdefault('QT_OPENGL', 'software')

from PyQt6.QtCore import (QUrl, QTimer, QAbstractNativeEventFilter, Qt,
                          QBuffer, QIODevice)
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtGui import QCloseEvent, QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

# 配布版は同梱の Python を隔離モード（python3xx._pth）で動かすため、
# 通常なら自動で入るスクリプト自身の場所が sys.path に入らない。自分で通す。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import appconfig
import directory
import feeds
import gitupdate
import layout
import startup
# BASE は appconfig.BASE として都度読む。from import で束縛すると、
# 置き場所を差し替えて動かすとき（テストなど）にここだけ古い値を掴んでしまう。
from appconfig import bundled, is_setup_complete, load_config, log
from bridge import Bridge
from layout import SETUP_H, SETUP_W, WIN_H, WIN_W

# 未送信分を送り直す間隔。
FLUSH_INTERVAL_MS = 5 * 60 * 1000

# 起動してから更新を見に行くまでの間。窓が出るのを待たせないために少し置く。
UPDATE_CHECK_DELAY_MS = 3000

# 置き場所が変わっていないかを見るまでの間。PowerShell を呼ぶので窓より後に回す。
REALIGN_DELAY_MS = 1500

HOTKEY_ID = 1
MOD_CTRL  = 0x0002
MOD_SHIFT = 0x0004
VK_SPACE  = 0x20
WM_HOTKEY = 0x0312


def _log_uncaught(exc_type, exc_value, exc_tb) -> None:
    log('FATAL ' + ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)).strip())
    sys.__excepthook__(exc_type, exc_value, exc_tb)


# ── シングルインスタンス保証 ──────────────────────────────────

ERROR_ALREADY_EXISTS = 183
_MUTEX_NAME = 'Local\\ClickUpPauseSingleton'
_kernel32   = ctypes.WinDLL('kernel32', use_last_error=True)


def _acquire_single_instance():
    handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return handle


def _release_single_instance(handle) -> None:
    if handle:
        _kernel32.CloseHandle(handle)


# ── Win32 ホットキー ──────────────────────────────────────────

_user32 = ctypes.WinDLL('user32', use_last_error=True)


def register_hotkey() -> tuple[bool, int]:
    """(登録できたか, 失敗時の Win32 エラーコード) を返す。"""
    ok = bool(_user32.RegisterHotKey(None, HOTKEY_ID, MOD_CTRL | MOD_SHIFT, VK_SPACE))
    return ok, (0 if ok else ctypes.get_last_error())


def unregister_hotkey() -> None:
    _user32.UnregisterHotKey(None, HOTKEY_ID)


# このアプリの名前。ウィンドウのタイトルに使う。
APP_TITLE = 'Click Up Widget'

# タイトルが取れても中断の手がかりにならないもの。
# 自分自身のタイトルをここに入れておかないと、メモ欄に自分の名前が入ってしまう。
# 名前を変えるときは APP_TITLE を直すだけで両方に効くよう、ここから参照する。
# 旧名も残す（古い版が同時に立っていたときに拾わないため）。
IGNORED_TITLES = frozenset({'Program Manager', 'Windows インプット エクスペリエンス',
                            APP_TITLE, 'Pause Task'})

CONTEXT_MAX = 60
TITLE_SEPARATOR_RE = re.compile(r'\s+[|\-–—]\s+')


def trim_context(title: str) -> str:
    """長すぎるタイトルを、区切りの手前までに詰める。

    Teams のように「画面名 | チーム名 | 組織名 | 自分のメールアドレス | アプリ名」と
    延々つなげるアプリがあるため、頭から入るところまでを残す。
    """
    if len(title) <= CONTEXT_MAX:
        return title
    head, *rest = TITLE_SEPARATOR_RE.split(title)
    for part in rest:
        if len(head) + len(part) + 3 > CONTEXT_MAX:
            break
        head = f'{head} | {part}'
    return head[:CONTEXT_MAX].rstrip()


def foreground_window_title(exclude_hwnd: int) -> str:
    """中断直前まで見ていたウィンドウのタイトル。手がかりにならないものは空文字。"""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd or hwnd == exclude_hwnd:
        return ''
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ''
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value.strip()
    return '' if title in IGNORED_TITLES else trim_context(title)


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_press):
        super().__init__()
        self._on_press = on_press

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_generic_MSG':
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._on_press()
        return False, 0


# ── ウィンドウの外観（角丸・すりガラス） ──────────────────────

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND                   = 2

# 背後キャプチャの縮小率。粗く縮めるほど軽く、CSS 側で引き伸ばす分だけぼけ方も滑らかになる。
BACKDROP_SCALE = 10


def apply_rounded_corners(win: QMainWindow) -> None:
    """フレームレスウィンドウの四隅を Windows 11 の角丸に切る。

    未対応の OS では DwmSetWindowAttribute が失敗するだけで、角が直角になるに留まる。
    """
    try:
        dwmapi = ctypes.WinDLL('dwmapi')
    except OSError as e:
        log(f'警告: dwmapi をロードできませんでした ({e})')
        return

    v  = ctypes.c_int(DWMWCP_ROUND)
    hr = dwmapi.DwmSetWindowAttribute(
        ctypes.wintypes.HWND(int(win.winId())),
        ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
        ctypes.byref(v), ctypes.sizeof(v),
    )
    if hr != 0:
        log(f'警告: 角丸の適用に失敗しました (HRESULT=0x{hr & 0xFFFFFFFF:08X})')


def backdrop_data_uri(x: int, y: int, w: int, h: int) -> str:
    """指定領域（論理座標）の画面を縮小した PNG の data URI にして返す。

    ウィンドウ自体を透過させてすりガラスにはできない。QtWebEngine を GPU 合成なしで
    動かしている（冒頭の d3d11 クラッシュ回避）と描画面が常に不透明になり、
    WA_TranslucentBackground も DWM のアクリルも効かないため。
    そこで表示直前に背後を撮り、ぼかして敷くことで同じ見た目を作る。
    ぼかし自体は CSS の filter に任せる。
    """
    shot  = QApplication.primaryScreen().grabWindow(0, x, y, w, h)
    small = shot.toImage().scaled(
        max(w // BACKDROP_SCALE, 1), max(h // BACKDROP_SCALE, 1),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    small.save(buf, 'PNG')
    return 'data:image/png;base64,' + bytes(buf.data().toBase64()).decode('ascii')


class HideOnCloseWindow(QMainWindow):
    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()


# ── 画面への流し込み ──────────────────────────────────────────

def _push_directory(view: QWebEngineView, cfg: dict) -> None:
    """手元の控えを画面へ流し込む。絞り込みは向こう側でやる。"""
    payload = directory.build_payload(cfg, directory.load(appconfig.BASE))
    view.page().runJavaScript(
        'typeof setDirectory==="function" && setDirectory('
        + json.dumps(payload, ensure_ascii=True) + ')')


def _push_quick(view: QWebEngineView, cfg: dict) -> None:
    """候補の並びを決めるものだけを渡し直す。

    候補ぜんぶ（数十 KB）は画面の読み込み時に一度渡している。使うたびに変わるのは
    「最近使ったリスト」と「よく使うもの」だけなので、窓を出すときはこちらだけ入れ替える。
    """
    recent = [str(x) for x in cfg.get('recent_lists', [])]
    fav    = appconfig.favorites(cfg)
    view.page().runJavaScript(
        f'typeof setRecent==="function" && setRecent({json.dumps(recent)});'
        f'typeof setFavorites==="function" && setFavorites({json.dumps(fav)})')


def _push_backdrop(win: HideOnCloseWindow, view: QWebEngineView, w: int, h: int) -> None:
    """表示位置の背後を撮って ui.html 側に渡す。失敗しても表示は続行する。

    呼ぶのは窓が引っ込んでいる間だけ。出ている最中に撮ると自分が写り込むうえ、
    避けるために hide → show を挟むと描画面の作り直しが間に合わず、
    中身が描かれないまま出ることがある。
    """
    try:
        pos = win.pos()
        uri = backdrop_data_uri(pos.x(), pos.y(), w, h)
    except Exception as e:
        log(f'警告: 背景のキャプチャに失敗しました ({e})')
        return
    view.page().runJavaScript(
        f'typeof setBackdrop==="function" && setBackdrop({json.dumps(uri)})')


def _refresh_visible(win: HideOnCloseWindow, view: QWebEngineView,
                     feed: feeds.TaskFeed, context: str) -> None:
    """出しっぱなしのまま呼ばれたとき。

    背景を撮り直すには一度隠す必要があり、その往復が描画面を壊す疑いがあるので、
    背景は据え置いて中身だけ入れ直す。
    """
    log('呼び出されました（表示中のため中身だけ入れ直す）')
    win.raise_()
    win.activateWindow()
    if context:      # 空で上書きしてメモを消さない
        view.page().runJavaScript(
            f'typeof refreshContext==="function" && refreshContext({json.dumps(context)})')
    cfg = load_config()
    if is_setup_complete(cfg):
        feed.refresh(cfg)      # 一覧も古くなっているので取り直す
        _push_quick(view, cfg)


def show_window(win: HideOnCloseWindow, view: QWebEngineView, feed: feeds.TaskFeed) -> None:
    # 前面に出る前に取る。出た後では自分が最前面になって、直前の作業先が分からなくなる。
    context = foreground_window_title(int(win.winId()))

    if win.isVisible():
        _refresh_visible(win, view, feed, context)
        return

    cfg   = load_config()
    ready = is_setup_complete(cfg)
    w = WIN_W if ready else SETUP_W
    h = WIN_H if ready else SETUP_H
    win.setFixedSize(w, h)
    layout.position_window(win, w, h, center=not ready)

    _push_backdrop(win, view, w, h)
    win.show()
    win.raise_()
    win.activateWindow()
    view.page().runJavaScript(
        f'typeof resetForm==="function" && resetForm({json.dumps(context)})')
    if ready:
        feed.refresh(cfg)
        _push_quick(view, cfg)
    log('呼び出されました')


def _install_hotkey(app: QApplication, win: HideOnCloseWindow,
                    view: QWebEngineView, feed: feeds.TaskFeed) -> HotkeyFilter:
    """ホットキーを登録する。戻り値は GC されないよう呼び出し側で保持すること。"""
    ok, err = register_hotkey()
    if ok:
        log('起動しました（ホットキー Ctrl+Shift+Space 登録済み）')
    else:
        log('警告: ホットキー Ctrl+Shift+Space の登録に失敗しました '
            f'(Win32 error={err} / 1409 は他のアプリが占有中)')

    filt = HotkeyFilter(lambda: show_window(win, view, feed))
    app.installNativeEventFilter(filt)
    return filt


# ── 組み立て ──────────────────────────────────────────────────

def _build_window() -> tuple[HideOnCloseWindow, QWebEngineView, bool]:
    initial_setup = not is_setup_complete(load_config())

    win = HideOnCloseWindow()
    win.setWindowTitle(APP_TITLE)
    win.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    win.setFixedSize(SETUP_W if initial_setup else WIN_W,
                     SETUP_H if initial_setup else WIN_H)

    view = QWebEngineView()
    # 読み込み中に白が一瞬見えないよう、下地を板の色に合わせておく。
    view.page().setBackgroundColor(QColor('#141416'))
    win.setCentralWidget(view)

    def _on_render_terminated(status, exit_code: int) -> None:
        """表示プロセスが落ちたら読み込み直す。放っておくと中身が空のまま残るため。"""
        log(f'警告: 表示プロセスが落ちました (status={status}, exit={exit_code})。読み込み直します')
        view.load(QUrl.fromLocalFile(bundled(
            'setup.html' if not is_setup_complete(load_config()) else 'ui.html')))

    view.page().renderProcessTerminated.connect(_on_render_terminated)
    return win, view, initial_setup


def _connect_bridge(win: HideOnCloseWindow, view: QWebEngineView) -> tuple[Bridge, QWebChannel]:
    """画面からの窓口をつなぐ。

    戻り値は両方とも呼び出し側で持ち続けること。Python 側の参照が切れると
    回収されて、画面から呼んだ瞬間に落ちる。
    """
    web_bridge = Bridge(win, view)
    web_bridge.listsReady.connect(lambda payload: view.page().runJavaScript(
        f'typeof setupLists==="function" && setupLists({payload})'))
    web_bridge.wideReady.connect(lambda payload: view.page().runJavaScript(
        f'typeof setWideTasks==="function" && setWideTasks({payload})'))
    channel = QWebChannel()
    channel.registerObject('bridge', web_bridge)
    view.page().setWebChannel(channel)
    return web_bridge, channel


def _connect_feeds(view: QWebEngineView):
    """裏で取ってきたものを画面へ流し込む線をつなぐ。

    戻り値は 3 つとも呼び出し側で持ち続けること（Python 側の参照が切れると回収される）。
    """
    feed = feeds.TaskFeed()
    feed.loaded.connect(lambda payload: view.page().runJavaScript(
        f'typeof setTasks==="function" && setTasks({payload})'))

    directory_feed = feeds.DirectoryFeed()
    directory_feed.loaded.connect(lambda payload: view.page().runJavaScript(
        f'typeof setDirectory==="function" && setDirectory({payload})'))

    update_feed = feeds.UpdateFeed()
    update_feed.loaded.connect(lambda payload: view.page().runJavaScript(
        f'typeof setUpdate==="function" && setUpdate({payload})'))
    return feed, directory_feed, update_feed


def _report_last_update(view: QWebEngineView) -> None:
    """前回の更新がどうなったかを一度だけ知らせる。

    updater が書いた印を読んで、読んだら消す。残しておくと窓を出すたびに
    「新しい版になりました」と言い続けることになる。
    """
    status = gitupdate.load_status()
    run    = status.get('lastRun')
    if not run or run.get('state') not in ('completed', 'failed'):
        return
    view.page().runJavaScript(
        'typeof setUpdateResult==="function" && setUpdateResult('
        + json.dumps(run, ensure_ascii=True) + ')')
    gitupdate.save_status({k: v for k, v in status.items() if k != 'lastRun'})


def _on_page_ready(view: QWebEngineView, directory_feed: feeds.DirectoryFeed) -> None:
    """画面が読み込まれたとき、候補を一度だけ渡す。

    窓を出すたびではなく、ここで渡す。表示プロセスが落ちて読み込み直したときも
    同じ道を通るので、候補が空のまま残らない。
    """
    latest = load_config()
    if not is_setup_complete(latest):
        return
    _push_directory(view, latest)
    _report_last_update(view)
    if directory.is_stale(directory.load(appconfig.BASE)):
        directory_feed.refresh(latest)


def _realign_async() -> None:
    """フォルダごと引っ越していたら、自動起動と見張り役の指す先を直す。

    起動のたびに 1 回だけ、ワーカースレッドから。設定を終える前は、そもそも
    どちらも登録されていないので何もしない。
    """
    if not is_setup_complete(load_config()):
        return

    def work() -> None:
        try:
            fixed = startup.realign()
        except Exception as e:
            log(f'警告: 置き場所の確認でつまずきました ({e})')
            return
        if fixed:
            log(f"置き場所が変わっていたので、{' と '.join(fixed)}を登録し直しました")

    threading.Thread(target=work, daemon=True).start()


def main() -> None:
    sys.excepthook = _log_uncaught

    mutex_handle = _acquire_single_instance()
    if mutex_handle is None:
        log('二重起動を検出したため終了しました')
        return

    appconfig.migrate_secrets()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    win, view, initial_setup = _build_window()
    web_bridge, channel = _connect_bridge(win, view)   # noqa: F841  GC 防止のため保持する

    view.load(QUrl.fromLocalFile(bundled('setup.html' if initial_setup else 'ui.html')))
    apply_rounded_corners(win)

    feed, directory_feed, update_feed = _connect_feeds(view)
    view.loadFinished.connect(
        lambda ok: _on_page_ready(view, directory_feed) if ok else None)

    filt = _install_hotkey(app, win, view, feed)       # noqa: F841  同上

    def _cleanup() -> None:
        log('終了します')
        unregister_hotkey()
        _release_single_instance(mutex_handle)

    app.aboutToQuit.connect(_cleanup)

    # 落ちていた間や、オフラインのときに貯まった分を送り直す。
    flush_timer = QTimer(app)
    flush_timer.timeout.connect(lambda: feeds.flush_outbox_async(load_config()))
    flush_timer.start(FLUSH_INTERVAL_MS)

    # HTML の読み込み前に出すと、背景を渡す setBackdrop がまだ存在せず初回だけ地の色になる。
    def _show_first(_ok: bool) -> None:
        view.loadFinished.disconnect(_show_first)
        QTimer.singleShot(0, lambda: show_window(win, view, feed))
        QTimer.singleShot(0, lambda: feeds.flush_outbox_async(load_config()))
        # 引っ越していないかも、起動したときに 1 回だけ見る。
        QTimer.singleShot(REALIGN_DELAY_MS, _realign_async)
        # 新しい版が出ていないかは、起動したときに 1 回だけ見る。
        # 少し遅らせるのは、窓が出るまでの間にネットワークを待たせないため。
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, update_feed.refresh)

    view.loadFinished.connect(_show_first)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
