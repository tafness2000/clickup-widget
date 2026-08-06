"""置き場所・ログ・設定ファイル。どのモジュールからも同じものを見るための土台。

ここは他の自作モジュールを import しない。全員がここを import する側になるため。
"""
import json
import os
import sys
import threading
import time
from datetime import datetime

import secretstore


def _app_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def bundled(name: str) -> str:
    """一緒に配ったファイル（HTML など）の場所。"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


BASE        = _app_dir()
CONFIG_PATH = os.path.join(BASE, 'config.json')
LOG_PATH    = os.path.join(BASE, 'pausetask.log')
LOG_MAX     = 512 * 1024

# 「最近使ったリスト」に覚えておく数。候補の先頭に出すぶんだけあればよい。
RECENT_MAX = 5

# 設定ファイルの読み書きの試し直し。他が開いている一瞬に当たったときだけ使う。
READ_RETRY     = 3
WRITE_RETRY    = 5
RETRY_WAIT_SEC = 0.05


# ── 外から来た文字を画面に出す前に ────────────────────────────

# 文字の並ぶ向きを変えてしまう制御文字。見えないまま表示だけ入れ替わるので、
# 「完了ボタンの隣に別のものが見えている」ような細工ができてしまう。
# タスク名も、取り込む更新の見出しも、書くのは自分ではないので落としておく。
_BIDI_CONTROLS = str.maketrans('', '', '‪‫‬‭‮'
                                       '⁦⁧⁨⁩‏‎')


def plain(text: str) -> str:
    return (text or '').translate(_BIDI_CONTROLS)


# ── ログ ──────────────────────────────────────────────────────

# 一覧の取得を並列にしたので、複数のスレッドから同時に書かれる。
# ロック無しだと行が混ざったり、入れ替え中のファイルに書き込んだりする。
_log_lock = threading.Lock()


def log(message: str) -> None:
    """pythonw は stderr が捨てられるため、障害解析用にファイルへ残す。"""
    try:
        with _log_lock:
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX:
                os.replace(LOG_PATH, LOG_PATH + '.1')
            stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(f'{stamp}  {message}\n')
    except Exception:
        pass


# ── 設定 ──────────────────────────────────────────────────────

# ディスク上はこちら（暗号文）。読み込んだ後、メモリ上では api_token（平文）になる。
TOKEN_KEY     = 'api_token'
TOKEN_ENC_KEY = 'api_token_enc'


def _empty_config() -> dict:
    return {'api_token': '', 'list_id': '', 'user_id': None}


def _unseal(data: dict) -> dict:
    """保存された形（暗号文）から、使う形（平文）へ。

    復号できないのは、フォルダごと別のパソコン・別のユーザーへ渡ったとき。
    その場合はトークンを空にして、初回設定からやり直してもらう。
    """
    encoded = data.get(TOKEN_ENC_KEY)
    if not encoded:
        return data                      # まだ平文の世代。次に保存するとき暗号化される
    rest = {k: v for k, v in data.items() if k != TOKEN_ENC_KEY}
    try:
        return {**rest, TOKEN_KEY: secretstore.decrypt(encoded)}
    except Exception as e:
        log(f'警告: 保存された接続情報を読めませんでした（{e}）。設定をやり直してください')
        return {**rest, TOKEN_KEY: ''}


def _seal(cfg: dict) -> dict:
    """使う形（平文）から、保存する形（暗号文）へ。"""
    token = cfg.get(TOKEN_KEY, '')
    rest  = {k: v for k, v in cfg.items() if k != TOKEN_KEY}
    if not token:
        return rest
    try:
        return {**rest, TOKEN_ENC_KEY: secretstore.encrypt(token)}
    except Exception as e:
        # 暗号化できないパソコンでも使えなくならないように、平文で残す道は塞がない。
        log(f'警告: 接続情報を暗号化できなかったため、そのまま保存します ({e})')
        return cfg


def _quarantine_broken(path: str) -> None:
    """壊れた設定を脇へ退ける。

    コピーではなく移動する。残したままだと、設定を読むたび（登録のたび・窓を出すたび）に
    同じ退避とログを繰り返すことになる。中身は .broken の方で後から見られる。
    """
    try:
        os.replace(path, path + '.broken')
        log(f'警告: 設定ファイルを読めなかったため {os.path.basename(path)}.broken へ移しました。'
            '初回設定からやり直してください')
    except OSError as e:
        log(f'警告: 壊れた設定ファイルを退避できませんでした ({e})')


# 設定を読み書きする経路が増えた（★の出し入れ・直近リスト・一覧の取得ついでの補完）。
# 素通しだと「読む → 相手が書く → 上書きする」で片方の変更が消えるうえ、
# 同時に書くとファイルそのものが壊れて .broken 送りになる。
# update_config から load/save を呼べるように再入可能なロックにしてある。
_config_lock = threading.RLock()


def load_config() -> dict:
    """設定を読む。壊れていたら退避して初回設定へ落とす（起動そのものは止めない）。

    outbox・directory と違って空を返せば済む話ではない（トークンを入れ直す羽目になる）。
    だからこそ、何が起きたかをログと .broken ファイルの両方に残す。
    """
    with _config_lock:
        if not os.path.exists(CONFIG_PATH):
            return _empty_config()

        data = None
        for _ in range(READ_RETRY):
            try:
                with open(CONFIG_PATH, encoding='utf-8') as f:
                    data = json.load(f)
                break
            except (PermissionError, FileNotFoundError):
                # 置き換えている一瞬に当たっただけ。壊れてはいないので退避しない。
                # ここで .broken へ送ってしまうと、無事な設定ごとトークンを失う。
                time.sleep(RETRY_WAIT_SEC)
            except (OSError, ValueError):
                _quarantine_broken(CONFIG_PATH)
                return _empty_config()

        if data is None:
            log('警告: 設定ファイルを読めませんでした（他が書き込み中かもしれません）')
            return _empty_config()
        if not isinstance(data, dict):
            _quarantine_broken(CONFIG_PATH)
            return _empty_config()
        return _unseal(data)


def save_config(cfg: dict) -> None:
    """設定を書く。書き込みの途中で落ちても、前の内容を壊さない。

    いったん隣に書いてから置き換える。直接上書きすると、途中で電源が落ちたときに
    半端な JSON が残り、次の起動で .broken へ退避されてトークンごと消える。
    """
    with _config_lock:
        temporary = CONFIG_PATH + '.writing'
        with open(temporary, 'w', encoding='utf-8') as f:
            json.dump(_seal(cfg), f, indent=2, ensure_ascii=False)

        # Windows は、誰かがそのファイルを開いている間は置き換えさせてくれない。
        # 覗かれているだけ（メモ帳で開いている等）のことが多いので、少し待って試し直す。
        for _ in range(WRITE_RETRY):
            try:
                os.replace(temporary, CONFIG_PATH)
                return
            except PermissionError:
                time.sleep(RETRY_WAIT_SEC)

        # 置き換えられなかった。書きかけを片付ける。元のファイルは無傷のまま残る。
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise OSError('設定ファイルを置き換えられませんでした'
                      f'（{os.path.basename(CONFIG_PATH)} を開いているものがあります）')


def update_config(change) -> dict:
    """読む → 直す → 書く をひとまとまりで行い、書いた内容を返す。

    この形にしないと、読んでから書くまでの間に別のスレッドが書いた変更を
    そのまま巻き戻してしまう（★を押した直後に一覧の取得が終わる、など）。
    change は設定を受け取って新しい設定を返す関数。
    """
    with _config_lock:
        updated = change(load_config())
        save_config(updated)
        return updated


def migrate_secrets() -> None:
    """平文のまま保存されている古い設定を、暗号化した形へ移す。起動時に一度だけ。

    利用者の操作は要らない。読んで保存し直すだけで、save_config が暗号化してくれる。
    """
    if not os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return                              # 壊れているぶんは load_config 側が退避する
    if not isinstance(raw, dict) or not raw.get(TOKEN_KEY):
        return                              # すでに暗号化済み、または未設定
    save_config(_unseal(raw))
    log('接続情報を、このパソコンでしか読めない形に変えて保存し直しました')


def is_setup_complete(cfg: dict) -> bool:
    return bool(cfg.get('api_token')) and bool(cfg.get('list_id'))


# 画面から来る種別と、設定ファイルの欄の対応。
FAVORITE_KEYS = {'list': 'favorite_lists', 'user': 'favorite_members'}

# 既定として保存できる期限。画面（ui.js の DUE_PRESETS）と同じ並び。
# 期限そのものの計算は clickup_api.due_at にある。ここは「保存してよい値か」を見るためだけ。
DUE_PRESETS = ('today', 'tomorrow', 'd3', 'week', 'd7', 'none')


def favorites(cfg: dict) -> dict:
    """画面へ渡す形（文字列の並び）でよく使うものを取り出す。"""
    return {
        'lists':   [str(x) for x in cfg.get('favorite_lists', [])],
        'members': [str(x) for x in cfg.get('favorite_members', [])],
    }


def toggle_favorite(cfg: dict, kind: str, item_id: str) -> dict:
    """よく使うものへ入れる／外した新しい設定を返す。

    押した順のまま並べておく。候補の先頭に出す順番がこれで決まる。
    """
    key = FAVORITE_KEYS.get(kind)
    if not key:
        return cfg
    item_id = str(item_id)
    kept    = [str(x) for x in cfg.get(key, [])]
    return {**cfg, key: [x for x in kept if x != item_id] if item_id in kept
                        else [*kept, item_id]}


def excluded_lists(cfg: dict) -> list[str]:
    """一覧に出さないリスト。画面へ渡す形（文字列の並び）で取り出す。

    どのタスクを一覧に載せるかを決めているのは clickup_api.is_memo の側。
    ここは出し入れのためだけにある。
    """
    return [str(x) for x in cfg.get('excluded_lists', [])]


def set_list_excluded(cfg: dict, list_id: str, excluded: bool) -> dict:
    """一覧に出す・出さないを決めた新しい設定を返す。

    入れ替え（トグル）ではなく「こうする」を受け取る。画面が持っている状態と
    設定がずれていても同じ結果に落ち着かせるため。トグルだと、ずれたまま
    反対側へ倒れて、押すたびに食い違いが続く。
    """
    list_id = str(list_id or '')
    if not list_id:
        return cfg
    kept = [x for x in excluded_lists(cfg) if x != list_id]
    return {**cfg, 'excluded_lists': [*kept, list_id] if excluded else kept}


def remember_list(cfg: dict, list_id: str) -> dict:
    """直前に使った登録先を覚えた新しい設定を返す。

    既定リストは候補の先頭に別枠で出るので、覚えるのは既定以外だけ。
    """
    list_id = str(list_id or '')
    if not list_id or list_id == str(cfg.get('list_id', '')):
        return cfg
    kept = [x for x in cfg.get('recent_lists', []) if str(x) != list_id]
    return {**cfg, 'recent_lists': [list_id, *kept][:RECENT_MAX]}


def set_default_list(cfg: dict, list_id: str) -> dict:
    """既定の登録先を差し替えた新しい設定を返す。

    新しい既定は「最近使った」から外す。候補の先頭に別枠で出るので、
    残しておくと同じものが二度並ぶ（remember_list と裏表の関係）。
    """
    list_id = str(list_id or '')
    if not list_id:
        return cfg
    kept = [str(x) for x in cfg.get('recent_lists', []) if str(x) != list_id]
    return {**cfg, 'list_id': list_id, 'recent_lists': kept}


def set_default_due(cfg: dict, preset: str) -> dict:
    """既定の期限を差し替えた新しい設定を返す。決まった 6 つ以外は受け付けない。"""
    if preset not in DUE_PRESETS:
        return cfg
    return {**cfg, 'default_due_preset': preset}
