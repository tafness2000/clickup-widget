"""更新が本当に走り出したかの見分けを、update-status.json を差し替えて確かめる。

    py tests\\check_wait.py

updater は記録すら残せなかったとき、何もしないまま failed を書いて引き返す。
これを「走り出した」と読むと、更新は進まないのに常駐だけ終わる。見張り役が
拾えない置き方だと、そのまま戻ってこない。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'app'))
import gitupdate                # noqa: E402  置き場所を通してから読み込む
from bridge import Bridge       # noqa: E402

seq: list[str] = []


def fake_load_status() -> dict:
    """呼ばれるたびに、次の状態を 1 つずつ返す。尽きたら「まだ何も書かれていない」。"""
    return {'lastRun': {'state': seq.pop(0)}} if seq else {}


gitupdate.load_status = fake_load_status
failed = 0


def check(label: str, states: list[str], want: bool) -> None:
    global failed
    seq[:] = states
    got = Bridge._wait_until_started(limit=6)
    ok = got == want
    if not ok:
        failed += 1
    print(f'{"OK " if ok else "NG "} {label}: {got}（期待 {want}）')


check('queued のあと running になった＝走り出した', ['queued', 'queued', 'running'], True)
check('queued のまま動かない＝走り出していない',   ['queued'] * 6,                  False)
check('何も書かれない＝走り出していない',           [],                              False)
check('いきなり failed＝記録すら残せず引き返した',  ['queued', 'failed'],            False)
check('failed のあと running が来ても、先に見た failed で断る',
      ['failed', 'running'], False)
check('completed まで一気に進んだ', ['completed'], True)

print(f'\n{failed} 件しくじりました' if failed else '\nすべて通りました')
sys.exit(1 if failed else 0)
