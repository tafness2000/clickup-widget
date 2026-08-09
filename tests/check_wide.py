"""一覧の取得まわりを、通信せずに確かめる。

    py tests\\check_wide.py

clickup_api.api_request を差し替えて、頁の返り方だけを作って渡す。
見ているのは 2 つ。

  ・取りに行ける頁を使い切ったとき、その事実（more）を返しているか
    ここを黙って捨てると、一覧に出ないタスクがあっても「もう無い」としか見えない
  ・一覧に載せるものの選別が、リストを跨ぐ経路と既定リストだけの経路で揃っているか
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'app'))
import clickup_api        # noqa: E402  置き場所を通してから読み込む


def page(n: int, last: bool = False) -> dict:
    return {
        'tasks': [{'id': str(i), 'name': f't{i}', 'description': '',
                   'status': {'type': 'open', 'status': 'to do'},
                   'list': {'id': '1', 'name': 'L'}, 'due_date': None} for i in range(n)],
        'last_page': last,
    }


CFG = {'team_id': '9', 'user_id': 1}
failed = 0


def check(label: str, got, want) -> None:
    global failed
    ok = got == want
    if not ok:
        failed += 1
    print(f'{"OK " if ok else "NG "} {label}')
    if not ok:
        print(f'      得た: {got}\n      期待: {want}')


def run(label: str, pages: list[dict], want_more: bool, want_calls: int) -> None:
    calls = []

    def fake(cfg, path, method='GET', body=None):
        calls.append(path)
        return pages[min(len(calls) - 1, len(pages) - 1)]

    clickup_api.api_request = fake
    _tasks, more = clickup_api.fetch_wide_tasks(CFG)
    check(label, (more, len(calls)), (want_more, want_calls))


run('毎頁 100 件で埋まる（上限で打ち切り）', [page(100)], True,  3)
run('1 頁で終わる',                        [page(30)],  False, 1)
run('3 頁目が半端＝ちょうど終わった',       [page(100), page(100), page(40)], False, 3)
run('last_page が立った',                  [page(100, last=True)], False, 1)

# 一覧に載せるものの選別。open 型で、出さないことにしたリストの外にあるものだけ。
MIXED = {
    'tasks': [
        {'id': 'a', 'name': 'a', 'status': {'type': 'open'}, 'list': {'id': '1'}},
        {'id': 'b', 'name': 'b', 'status': {'type': 'open'}, 'list': {'id': '9'}},   # 出さないリスト
        {'id': 'c', 'name': 'c', 'status': {'type': 'done'}, 'list': {'id': '1'}},   # 工程のタスク
    ],
    'last_page': True,
}
clickup_api.api_request = lambda cfg, p, method='GET', body=None: MIXED

tasks, _more = clickup_api.fetch_wide_tasks({**CFG, 'excluded_lists': ['9']})
check('跨いで集める経路: 出さないリストと工程を弾く', [t['id'] for t in tasks], ['a'])

tasks = clickup_api._fetch_from_default_list(
    {'user_id': 1, 'list_id': '1', 'excluded_lists': ['9']}, 5)
check('既定リストだけの経路（team_id が無いとき）も同じ選別',
      [t['id'] for t in tasks], ['a'])

print(f'\n{failed} 件しくじりました' if failed else '\nすべて通りました')
sys.exit(1 if failed else 0)
