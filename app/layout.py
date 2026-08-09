"""窓の大きさと置き場所。

高さはメモ付き 3 件が収まるところで固定する。中身に合わせて動かすと、
一覧が届いた拍子に窓が伸び縮みして、開いてすぐ打ち始める邪魔になるため。
"""
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QMainWindow

# 396 = 従来の 359 + 登録先の行 30px + 余白 7px。
WIN_W, WIN_H = 390, 396

# 初回設定は手順を載せるぶん大きく取り、画面の中央に出す。
# 隅に小さく出ると、初めての人が見落とすため。
SETUP_W, SETUP_H = 430, 486

# 一覧を広げたときの高さ。画面が狭ければ作業領域に合わせて縮める。
WIDE_H_MAX = 660

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
    """入力画面のときと、一覧を広げたときの大きさ。"""
    if not wide:
        return WIN_W, WIN_H
    _wl, wt, _wr, wb = work_area_logical()
    return WIN_W, min(WIDE_H_MAX, (wb - wt) - MARGIN * 2)


def position_window(win: QMainWindow, w: int, h: int, center: bool = False) -> None:
    wl, wt, wr, wb = work_area_logical()
    if center:
        win.move(wl + (wr - wl - w) // 2, wt + (wb - wt - h) // 2)
        return
    win.move(wr - w - MARGIN, wb - h - MARGIN)
