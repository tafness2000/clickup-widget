"""担当者を複数選べるようにしたぶんを、通信せずに確かめる。

    py tests\\check_assignees.py

主に見ているのは連打よけの鍵で、選んだ順によって崩れないか。
ここが崩れると 2 通りの壊れ方をする。

  ・同じ顔ぶれを違う順で選ぶと別物と見なされ、連打の 2 件目がそのまま入る
  ・入れ直したつもりのものが「さっきと同じ」と見なされ、打った中断メモが
    登録できたように見えて消える（こちらの方が痛い）
"""
import pathlib
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'app'))
import bridge          # noqa: E402  置き場所を通してから読み込む
import clickup_api     # noqa: E402
import outbox          # noqa: E402

failed = 0


def check(label: str, got, want) -> None:
    global failed
    ok = got == want
    if not ok:
        failed += 1
    print(f'{"OK " if ok else "NG "} {label}')
    if not ok:
        print(f'      得た: {got}\n      期待: {want}')


# ── 均し方 ────────────────────────────────────────────────────

p = clickup_api.parse_assignees
check('カンマ区切りを数にして昇順に並べる', p('3,1,2'), [1, 2, 3])
check('重なりは落とす',                     p('1,1,2'), [1, 2])
check('空の区切りは落とす',                 p('1,,2'),  [1, 2])
check('前後の空白は気にしない',             p(' 1 , 2 '), [1, 2])
check('数にならないものは落とす',           p('abc,1'), [1])
check('ぜんぶ数でなければ空',               p('abc'),   [])
check('空文字は空',                         p(''),      [])
check('None も空',                          p(None),    [])
# 画面を通らない経路（退避ぶんの送り直しなど）のために、数と配列も受ける。
check('数ひとつでも受ける',                 p(5),       [5])
check('配列でも受ける',                     p([2, 1]),  [1, 2])

# ── 組み立て ──────────────────────────────────────────────────

CFG  = {'user_id': 7, 'list_id': '1'}
WHEN = datetime(2026, 8, 26, 15, 0, 0)


def payload(assignees) -> dict:
    return clickup_api.build_task_payload(CFG, 'n', 'd', WHEN, assignees, 'today')


check('選んだぶんが入る', payload('3,1')['assignees'], [1, 3])
# 担当のいないタスクは、作った当人しか在り処を知らないまま ClickUp のどこかに残る。
# 画面の側でも最後のひとりは外せないようにしてあるが、そこを通らない経路もある。
check('誰も残らなければ自分',           payload('')['assignees'],    [7])
check('None でも自分',                  payload(None)['assignees'],  [7])
check('数でないものだけでも自分',       payload('abc')['assignees'], [7])

# ── 連打よけの鍵 ──────────────────────────────────────────────

k = bridge._submit_key
check('同じ顔ぶれなら、選んだ順が違っても同じ鍵',
      k('n', 'm', '1', p('2,1'), 'today') == k('n', 'm', '1', p('1,2'), 'today'), True)
check('顔ぶれが違えば別の鍵',
      k('n', 'm', '1', [1], 'today') == k('n', 'm', '1', [1, 2], 'today'), False)
check('メモが違えば別の鍵（同じ題で中身だけ変えて 2 件目を入れるのはよくある使い方）',
      k('n', 'm1', '1', [1], 'today') == k('n', 'm2', '1', [1], 'today'), False)
check('登録先が違えば別の鍵',
      k('n', 'm', '1', [1], 'today') == k('n', 'm', '2', [1], 'today'), False)
check('期限が違えば別の鍵',
      k('n', 'm', '1', [1], 'today') == k('n', 'm', '1', [1], 'tomorrow'), False)

# 実際に通る道で確かめる。鍵は画面から来た押し順ではなく、
# build_task_payload が組んだ並びから作っている。
check('押した順が逆でも、鍵は同じところへ落ちる',
      k('n', 'm', '1', payload('3,1')['assignees'], 'today')
      == k('n', 'm', '1', payload('1,3')['assignees'], 'today'), True)

# ── 退避ぶんの後方互換 ────────────────────────────────────────
#
# outbox.json には、ひとりしか選べなかった頃の payload が残っている。
# 送り直すときは中身を見ずにそのまま渡すので、形が変わっても通る。
# ここで新しい形へ直したくなるが、それをやると
# 「日付を組み立て直さない（3 日後に再送されても中断した日のまま）」が壊れる。
OLD   = {'name': 'むかしの中断メモ', 'assignees': [7], 'due_date': 1}
entry = outbox.normalize({'list_id': '5', 'payload': OLD}, '1')
check('古い形の退避ぶんは、中身をそのまま残す', entry['payload'], OLD)
check('古い形の退避ぶんは、控えた登録先へ送る', entry['list_id'], '5')

sent = {}


def fake(cfg, path, method='GET', body=None):
    sent['path'] = path
    sent['body'] = body
    return {}


clickup_api.api_request = fake
clickup_api.post_task({'api_token': 't', 'list_id': '1'}, OLD, entry['list_id'])
check('古い payload はそのまま ClickUp へ届く', sent['body'], OLD)
check('送り先も控えたリストのまま',             sent['path'], 'list/5/task')

print(f'\n{failed} 件しくじりました' if failed else '\nすべて通りました')
sys.exit(1 if failed else 0)
