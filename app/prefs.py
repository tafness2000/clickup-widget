"""設定画面で変えられる見た目の好み（文字の大きさ・窓を出す隅・一覧の最初のタブ）。

config.json に入れるものの決まりと検証だけを持つ。読み書きは appconfig、
画面への当て方は layout と bridge の仕事。ここは他の自作モジュールを import しない
（layout も take_shots.py も、設定ファイル無しでここを読むため）。

どれも「決まった選択肢から選ぶ」形にしてある。手で config.json を書き換えて
おかしな値が入っていても、既定に戻して動く。
"""

# 文字の大きさ（表示倍率）。段階で選ぶ。
#
# 上限を 1.5 にしているのは窓の寸法のため。1.5 倍だと入力 585x594・初回設定
# 645x729 になり、高さ 768px の画面でぎりぎり収まる。
ZOOM_STEPS   = (1.0, 1.1, 1.25, 1.4, 1.5)
DEFAULT_ZOOM = 1.25

# 窓を出す隅。初回設定だけは見落とされないよう、これに関わらず画面の中央に出す。
CORNERS        = ('bottom-right', 'top-right', 'bottom-left', 'top-left')
DEFAULT_CORNER = 'bottom-right'

# 一覧を広げたときに最初に開くタブ。画面（wide.js の data-scope）と同じ名前。
WIDE_SCOPES        = ('overdue', 'today', 'week', 'all')
DEFAULT_WIDE_SCOPE = 'today'


def as_zoom(value) -> float | None:
    """段階のどれかに当たる倍率。当たらなければ None。

    画面からは文字列（"1.25"）で届くので、数に直してから比べる。
    浮動小数の誤差で 1.1 が 1.1000000001 になっても拾えるよう、近さで見る。
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):   # 1e400 のような桁あふれも弾く
        return None
    return next((step for step in ZOOM_STEPS if abs(step - number) < 1e-6), None)


def zoom_of(cfg: dict) -> float:
    return as_zoom(cfg.get('zoom')) or DEFAULT_ZOOM


def corner_of(cfg: dict) -> str:
    corner = cfg.get('corner')
    return corner if corner in CORNERS else DEFAULT_CORNER


def wide_scope_of(cfg: dict) -> str:
    scope = cfg.get('wide_scope')
    return scope if scope in WIDE_SCOPES else DEFAULT_WIDE_SCOPE


def set_zoom(cfg: dict, value) -> dict:
    """文字の大きさを差し替えた新しい設定を返す。段階に無いものは受け付けない。"""
    zoom = as_zoom(value)
    return cfg if zoom is None else {**cfg, 'zoom': zoom}


def set_corner(cfg: dict, corner: str) -> dict:
    """窓を出す隅を差し替えた新しい設定を返す。4 つ以外は受け付けない。"""
    return {**cfg, 'corner': corner} if corner in CORNERS else cfg


def set_wide_scope(cfg: dict, scope: str) -> dict:
    """最初に開くタブを差し替えた新しい設定を返す。4 つ以外は受け付けない。"""
    return {**cfg, 'wide_scope': scope} if scope in WIDE_SCOPES else cfg
