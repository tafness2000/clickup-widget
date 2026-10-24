"""窓の大きさと置き場所。

高さはメモ付き 3 件が収まるところで固定する。中身に合わせて動かすと、
一覧が届いた拍子に窓が伸び縮みして、開いてすぐ打ち始める邪魔になるため。
"""
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QMainWindow

import prefs

# 画面の文字の大きさ。設定画面で段階から選ぶ（prefs.ZOOM_STEPS）。
#
# CSS は等倍（px の直書き）のままにして、表示するときに丸ごと引き伸ばす。
# ui.css の font-size は 40 か所あり、そこだけ大きくすると、高さを固定してある
# ところ（入力欄 34px・チップ 30px・候補パネル 328px・一覧 124px）との辻褄が合わず
# 必ずどこかが溢れる。倍率でまとめて動かせば、文字も余白も枠もチェックの升目も
# 同じ比率で大きくなるので、組み方を一切触らずに済む。
#
# 窓の寸法もこの率で膨らませる。倍率と隅は動かしている間に変わるので定数にせず、
# 起動時と設定を変えたときに set_zoom / set_corner で入れ替える。
# ここでは config.json を読まない。take_shots.py が設定ファイル無しで使うため。
_zoom   = prefs.DEFAULT_ZOOM
_corner = prefs.DEFAULT_CORNER

# 素の寸法（倍率が 1.0 のときの大きさ）。
# 396 = 従来の 359 + 登録先の行 30px + 余白 7px。
BASE_W, BASE_H = 390, 396

# 初回設定は手順を載せるぶん大きく取り、画面の中央に出す。
# 隅に小さく出ると、初めての人が見落とすため。
BASE_SETUP_W, BASE_SETUP_H = 430, 486


def set_zoom(zoom: float) -> None:
    global _zoom
    _zoom = zoom


def current_zoom() -> float:
    return _zoom


def set_corner(corner: str) -> None:
    global _corner
    _corner = corner if corner in prefs.CORNERS else prefs.DEFAULT_CORNER


def current_corner() -> str:
    return _corner


def scaled(value: int, zoom: float | None = None) -> int:
    """素の寸法を、文字の大きさに合わせた画素数にする。"""
    return round(value * (_zoom if zoom is None else zoom))


def win_size() -> tuple[int, int]:
    """入力画面の大きさ。"""
    return scaled(BASE_W), scaled(BASE_H)


def setup_size() -> tuple[int, int]:
    """初回設定の大きさ。"""
    return scaled(BASE_SETUP_W), scaled(BASE_SETUP_H)


# 画面の隅からの距離。窓の外の話なので、文字の大きさには連れない。
MARGIN = 12


def work_area_logical() -> tuple[int, int, int, int]:
    """タスクバーを除いた作業領域を、Qt と同じ論理座標で返す。

    見るのはマウスのある画面。画面が複数あるとき、いつも決まった画面の隅に出ると、
    別の画面で作業している間は視界の外に出てしまう。中断メモは、いま見ている
    ところに出てほしい。

    SystemParametersInfo（主画面ぶんの物理座標）を自前で割り戻すのはやめた。
    Qt の availableGeometry は最初から論理座標なので、DPI の違う画面が混ざっていても
    こちらで計算し直す必要がない。

    返すのは右端・下端を含まない座標。QRect の right()/bottom() は最後のピクセルを
    指すので 1 だけ足す。
    """
    screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
    area   = screen.availableGeometry()
    return area.left(), area.top(), area.right() + 1, area.bottom() + 1


def view_size(wide: bool) -> tuple[int, int]:
    """入力画面のときと、一覧を広げたときの大きさ。

    広げたときは作業領域の上下いっぱいまで伸ばす。一度に見えるタスクの数を
    できるだけ多くしたいので、上限は設けない。
    """
    w, h = win_size()
    if not wide:
        return w, h
    _wl, wt, _wr, wb = work_area_logical()
    return w, (wb - wt) - MARGIN * 2


def corner_xy(corner: str, w: int, h: int,
              area: tuple[int, int, int, int]) -> tuple[int, int]:
    """作業領域 area（左・上・右・下）の隅に、w x h の窓を置くときの左上の座標。"""
    left, top, right, bottom = area
    x = left + MARGIN if corner.endswith('left') else right - w - MARGIN
    y = top + MARGIN if corner.startswith('top') else bottom - h - MARGIN
    return x, y


def position_window(win: QMainWindow, w: int, h: int, center: bool = False) -> None:
    area = work_area_logical()
    if center:
        wl, wt, wr, wb = area
        win.move(wl + (wr - wl - w) // 2, wt + (wb - wt - h) // 2)
        return
    win.move(*corner_xy(_corner, w, h, area))
