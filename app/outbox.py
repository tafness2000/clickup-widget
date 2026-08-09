"""送れなかったタスクを貯めておき、つながったときに送り直す。

中断メモは急いでいるときに打つものなので、ネットが切れていたからと言って
入力を捨てるわけにはいかない。ここに貯めて後から送る。
"""
import json
import os
import threading
import time

import appconfig
import clickup_api

FILE_NAME        = 'outbox.json'
# 何度送っても通らないと分かったものの置き場。順番待ちの列から外して、ここへ寄せる。
FAILED_FILE_NAME = 'outbox_failed.json'

# ファイルの読み書きを直列にする。退避（GUI スレッド）と再送（ワーカースレッド）は
# 同時に起こりうるので、素通しだと「読む → 相手が書く → 上書きする」で片方が消える。
# 送信そのものはこの中に入れない。10 秒のタイムアウトぶん退避を待たせないため。
_io_lock = threading.Lock()


def _path(base: str) -> str:
    return os.path.join(base, FILE_NAME)


def load(base: str) -> list[dict]:
    """貯まっている未送信分。壊れていたら空として扱う（起動を止めない）。"""
    path = _path(base)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            items = json.load(f)
    except (OSError, ValueError):
        return []
    return items if isinstance(items, list) else []


def save(base: str, items: list[dict]) -> None:
    with open(_path(base), 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def normalize(item: dict, default_list_id: str) -> dict:
    """1 件を {list_id, payload} の形に揃える。

    登録先を選べるようにする前は payload をそのまま並べていた。すでに貯まっている
    ぶんを捨てるわけにいかないので、その形も読めるようにして既定リスト宛てとして扱う。
    """
    if isinstance(item, dict) and 'payload' in item:
        return {'list_id': str(item.get('list_id') or default_list_id), 'payload': item['payload']}
    return {'list_id': str(default_list_id), 'payload': item}


def enqueue(base: str, list_id: str, payload: dict) -> int:
    """未送信の 1 件を足し、貯まっている件数を返す。

    登録先も一緒に控える。後日つながったときに、中断したときと同じリストへ送るため。
    """
    with _io_lock:
        items = [*load(base), {'list_id': str(list_id), 'payload': payload}]
        save(base, items)
        return len(items)


def _record_failure(base: str, entry: dict, reason: str) -> None:
    """もう送れないと分かった 1 件を、理由付きで別のファイルへ寄せる。

    黙って捨てない。利用者が打った中断メモなので、後から中身を見られるようにしておく。
    """
    path = os.path.join(base, FAILED_FILE_NAME)
    with _io_lock:
        try:
            with open(path, encoding='utf-8') as f:
                items = json.load(f)
            if not isinstance(items, list):
                items = []
        except (OSError, ValueError):
            items = []
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump([*items, {**entry, 'reason': reason, 'failed_at': time.time()}],
                          f, indent=2, ensure_ascii=False)
        except (OSError, ValueError) as e:
            # ここで例外を上げると flush が途中で抜け、送れた分を消し込めないまま
            # outbox.json が残る＝次の再送で同じものをもう一度送ることになる。
            appconfig.log(f'警告: 送れなかった分を {FAILED_FILE_NAME} へ書けませんでした ({e})')


def flush(cfg: dict, base: str) -> tuple[int, int, int]:
    """貯まっている分を古い順に送る。(送れた件数, 残った件数, 諦めた件数) を返す。

    失敗の扱いは 2 通りに分ける。

    ・つながらないだけ（接続断・5xx）… そこで打ち切って残す。まだ復旧していない
      可能性が高く、無駄にタイムアウトを待つ間ホットキーの反応が鈍るため
    ・何度送っても通らない（リストが消えた・権限が外れた等の 4xx）… 列から外す。
      先頭に居座られると、後ろに並んだ正常な分まで永久に出せなくなるため

    送っている間に新しく退避された分は、書き戻すときに読み直して拾う。
    こちらが持っている古い一覧で上書きすると、その 1 件が消えてしまう。
    """
    with _io_lock:
        items = load(base)
    if not items:
        return 0, 0, 0

    sent = dropped = 0
    left: list[dict] = []
    stalled = False                                 # つながらないと分かった以降は試さない
    for raw in items:
        entry = normalize(raw, cfg['list_id'])      # 残す場合も新しい形に直しておく
        if stalled:
            left.append(entry)
            continue
        try:
            clickup_api.post_task(cfg, entry['payload'], entry['list_id'])
            sent += 1
        except Exception as e:
            if clickup_api.is_retryable(e):
                stalled = True
                left.append(entry)
            else:
                _record_failure(base, entry, str(e))
                dropped += 1

    with _io_lock:
        # 送っている間に足された分（末尾に付く）を落とさないよう、読み直して繋ぐ。
        added = load(base)[len(items):]
        save(base, [*left, *added])
    return sent, len(left) + len(added), dropped


def flush_quiet(cfg: dict, base: str) -> None:
    """貯まっている分を送り直す。失敗しても黙って次の機会に回す。

    呼ばれるのは起動直後・登録の直後・5 分ごとの 3 か所。どれも利用者が
    待っている場面ではないので、うまくいかなければ何も言わずに引き下がる。
    """
    if not appconfig.is_setup_complete(cfg):
        return
    try:
        sent, left, dropped = flush(cfg, base)
    except Exception as e:
        appconfig.log(f'警告: 未送信分の再送に失敗しました ({e})')
        return
    if sent:
        appconfig.log(f'未送信だった {sent} 件を登録しました（残り {left} 件）')
    if dropped:
        appconfig.log(f'警告: 送り直しても通らない分が {dropped} 件ありました。'
                      f'{FAILED_FILE_NAME} に控えてあります')
