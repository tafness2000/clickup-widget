"""窓の大きさと置き場所。

高さはメモ付き 3 件が収まるところで固定する。中身に合わせて動かすと、
一覧が届いた拍子に窓が伸び縮みして、開いてすぐ打ち始める邪魔になるため。
"""
import ctypes

from PyQt6.QtWidgets import QApplication, QMainWindow

# 396 = 従来の 359 + 登録先の行 30px + 余白 7px。
WIN_W, WIN_H = 390, 396

# 初回設定は手順を載せるぶん大きく取り、画面の中央に出す。
# 隅に小さく出ると、初めての人が見落とすため。
SETUP_W, SETUP_H = 430, 486

# 一覧を広げたときの高さ。画面が狭ければ作業領域に合わせて縮める。
WIDE_H_MAX = 660

SPI_GETWORKAREA = 0x0030
MARGIN = 12


class _RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                ('right', ctypes.c_long), ('bottom', ctypes.c_long)]


def work_area_logical() -> tuple[int, int, int, int]:
    """タスクバーを除いた作業領域を、Qt と同じ論理座標で返す。"""
    r = _RECT()
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    dpr = QApplication.primaryScreen().devicePixelRatio()
    return (round(r.left / dpr), round(r.top / dpr),
            round(r.right / dpr), round(r.bottom / dpr))


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
