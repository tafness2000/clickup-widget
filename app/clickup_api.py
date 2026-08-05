"""ClickUp API。HTTP を触るのはこのモジュールだけに閉じる。"""
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

API_ROOT = 'https://api.clickup.com/api/v2'
TIMEOUT  = 10
FEED_LIMIT = 5

# スペースの数だけ問い合わせるので、何本か同時に投げる。
# 1 つずつ順に待つと、16 スペースで 30 回以上の往復になり、途中で 1 つでも
# タイムアウト（10 秒）すると、その分まるまる待たされる。
# 上限を欲張らないのは ClickUp 側の毎分の上限（100 回）に触れないため。
FETCH_WORKERS = 8

# ClickUp のステータスには open / custom / done / closed の 4 種類がある。
#
# 完了として送る候補はこの順で探す。closed が先なのが肝心。
# done 型は「片付いた」を意味するとは限らない。工程管理をしているリストでは
# 「設計」「施工」「検査」…といった進行中の段階が done 型で並んでいることがあり、
# その先頭を完了として送ると、進行中の工程へ差し戻したうえ、一覧を取り直すと
# また出てくる（ClickUp が閉じたと見なすのは closed 型だけ）。
COMPLETION_TYPES = ('closed', 'done')

# 一覧から外す型。上と同じ理由で closed だけ。done 型まで外すと工程中のタスクが消える。
CLOSED_TYPE = 'closed'

# 一覧に出すメモは 1 行目だけ、しかもこの長さまで。
MEMO_MAX = 80


def seg(value) -> str:
    """URL のパスに埋める 1 区切り。

    ここへ来る ID は ClickUp の応答か手元の設定から来るので、いまのところ
    おかしなものは混ざらない。それでも通しておくのは、画面側の入力経路が
    増えたときに、ここを直し忘れても壊れないようにするため。
    """
    return quote(str(value), safe='')


def api_request(cfg: dict, path: str, method: str = 'GET', body: dict | None = None) -> dict:
    """ClickUp を叩いて JSON を返す。全ての呼び出しがここを通る。"""
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req  = urllib.request.Request(
        f'{API_ROOT}/{path}',
        data=data,
        headers={'Authorization': cfg['api_token'], 'Content-Type': 'application/json'},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def is_retryable(error: Exception) -> bool:
    """後で送り直せば通る見込みのある失敗か。

    トークン誤りやリスト ID 誤り (4xx) は何度送っても通らないので、貯めずにその場で知らせる。
    HTTPError は URLError の派生なので、先に判定する順序を崩さないこと。
    """
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500
    return isinstance(error, (urllib.error.URLError, TimeoutError, OSError))


def fetch_user(token: str) -> dict:
    user = api_request({'api_token': token}, 'user')['user']
    return {
        'id':    user['id'],
        'name':  user.get('username') or '',
        'email': user.get('email') or '',
    }


def fetch_user_id(token: str) -> int:
    return fetch_user(token)['id']


# ── リストとメンバーの一覧 ────────────────────────────────────

def _pick_team(teams: list[dict], preferred: str | None) -> dict | None:
    for team in teams:
        if preferred and str(team.get('id')) == str(preferred):
            return team
    return teams[0] if teams else None


def _list_entry(item: dict, path: str) -> dict:
    return {'id': str(item.get('id', '')), 'name': item.get('name', ''), 'path': path}


def _space_lists(cfg: dict, space: dict, on_warn=None) -> list[dict]:
    """1 スペースぶんのリスト。

    フォルダ取得の応答にはフォルダ内のリストが同梱されるので、
    フォルダごとに引き直す必要はない（1 スペースあたり 2 回で済む）。
    2 回は別々に守る。片方が落ちても、もう片方は候補に出せた方がましなため。
    """
    space_id   = space.get('id', '')
    space_name = space.get('name', '')

    def guard(what: str, path: str, key: str) -> list[dict]:
        try:
            return api_request(cfg, path).get(key, [])
        except Exception as e:
            if on_warn:
                on_warn(f'スペース「{space_name}」の{what}を取得できませんでした ({e})')
            return []

    out: list[dict] = []
    for folder in guard('フォルダ', f'space/{seg(space_id)}/folder?archived=false', 'folders'):
        path = f"{space_name} > {folder.get('name', '')}"
        out.extend(_list_entry(item, path) for item in folder.get('lists', []))
    for item in guard('リスト', f'space/{seg(space_id)}/list?archived=false', 'lists'):
        out.append(_list_entry(item, space_name))
    return out


def _with_default_list(cfg: dict, lists: list[dict], on_warn=None) -> list[dict]:
    """既定リストが候補に無ければ、そのリストが属するスペースごと足す。

    個人スペース（「〇〇's Space」）は team/{id}/space に出てこない。既定リストが
    そこにあると候補から漏れ、リスト名も出せず ID がそのまま並んでしまう。
    """
    list_id = str(cfg.get('list_id') or '')
    if not list_id or any(str(item['id']) == list_id for item in lists):
        return lists

    try:
        info = api_request(cfg, f'list/{seg(list_id)}')
    except Exception as e:
        if on_warn:
            on_warn(f'既定リストの情報を取得できませんでした ({e})')
        return lists

    space = info.get('space') or {}
    extra = _space_lists(cfg, space, on_warn) if space.get('id') else []
    known = {str(item['id']) for item in lists}
    merged = [*lists, *[item for item in extra if str(item['id']) not in known]]
    if any(str(item['id']) == list_id for item in merged) or not info.get('id'):
        return merged
    # スペースごと辿れなかったときも、既定リストだけは名前を出せるようにする。
    return [*merged, _list_entry(info, space.get('name', ''))]


def fetch_directory(cfg: dict, on_warn=None) -> dict:
    """ワークスペース全体のリストとメンバーを集める。

    スペースを 1 つ取り損ねても、残りは使えた方がましなので、
    そこだけ飛ばして続ける（呼び出し側へは on_warn で知らせる）。
    """
    teams = api_request(cfg, 'team').get('teams', [])
    team  = _pick_team(teams, cfg.get('team_id'))
    if team is None:
        return {'team_id': '', 'lists': [], 'members': [], 'fetched_at': time.time()}

    members = []
    for entry in team.get('members', []):
        user = entry.get('user') or {}
        if user.get('id') is not None:
            members.append({
                'id':    user['id'],
                'name':  user.get('username') or user.get('email') or '',
                'email': user.get('email') or '',
            })

    spaces = api_request(cfg, f"team/{seg(team['id'])}/space?archived=false").get('spaces', [])
    lists: list[dict] = []
    if spaces:
        # map は渡した順に結果を返すので、候補の並び順はスペースの順のまま。
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            for part in pool.map(lambda s: _space_lists(cfg, s, on_warn), spaces):
                lists.extend(part)

    return {
        'team_id':    str(team['id']),
        'lists':      _with_default_list(cfg, lists, on_warn),
        'members':    members,
        'fetched_at': time.time(),
    }


# 各人の置き場所を、このスペースの下に「名字のリスト」として並べている前提。
# 初回設定で 200 件の中から探させると「どれが自分のものか」で必ず止まるので、
# 表示名から当たりを付けて選んでおく。
# この並べ方をしていないワークスペースでは、単に見つからず従来どおり選ぶことになる。
PERSONAL_SPACE_NAME = 'Personal Work space'


def guess_personal_list(lists: list[dict], user_name: str) -> dict | None:
    """その人の置き場所を推測する。見当が付かなければ None（従来どおり選んでもらう）。

    ClickUp の表示名は「姓 名」と「名 姓」が混ざっているので、空白で割った断片の
    どれかがリスト名と一致すればその人のものと見なす。取り違えるより、選ばせる方に倒す。
    """
    parts = {p.lower() for p in re.split(r'[\s　]+', user_name or '') if p}
    if not parts:
        return None
    for item in lists:
        if not (item.get('path') or '').startswith(PERSONAL_SPACE_NAME):
            continue
        if (item.get('name') or '').strip().lower() in parts:
            return item
    return None


# ── タスクの作成 ──────────────────────────────────────────────

DEFAULT_DUE_PRESET = 'today'


def _this_friday(end: datetime) -> datetime:
    """今週の金曜。金曜当日ならその日、土日なら翌週の金曜。"""
    return end + timedelta(days=(4 - end.weekday()) % 7)     # 0=月 … 4=金


def due_at(start: datetime, preset: str) -> datetime | None:
    """期限の日時。その日の終わりに合わせる。'none' なら期限を付けない。

    始まりは常に中断した日。動かすのは終わりだけなので、
    後から見たときに「いつ中断したか」が消えない。
    """
    end = start.replace(hour=23, minute=59, second=59, microsecond=0)
    if preset == 'none':     return None
    if preset == 'tomorrow': return end + timedelta(days=1)
    if preset == 'd3':       return end + timedelta(days=3)
    if preset == 'd7':       return end + timedelta(days=7)
    if preset == 'week':     return _this_friday(end)
    return end                                                # today と、知らない指定


def build_task_payload(cfg: dict, name: str, description: str, when: datetime,
                       assignee_id: str | int | None = None,
                       due_preset: str | None = None) -> dict:
    """送信するタスク本体を組み立てる。

    送れずに退避した分も、この結果をそのまま保存して後で送る。日付を組み立て直さないので、
    3 日後に再送されても中断した日のままになる。
    assignee_id が無ければ自分に割り当てる。
    """
    start    = when.replace(hour=0, minute=0, second=0, microsecond=0)
    assignee = int(assignee_id) if assignee_id else int(cfg['user_id'])
    preset   = due_preset or cfg.get('default_due_preset') or DEFAULT_DUE_PRESET

    payload = {
        'name': name,
        'description': description,
        'assignees': [assignee],
        'priority': 3,
        'start_date': int(start.timestamp() * 1000),
        'start_date_time': False,
    }
    due = due_at(start, preset)
    if due is not None:
        payload['due_date'] = int(due.timestamp() * 1000)
        payload['due_date_time'] = False
    return payload


def post_task(cfg: dict, payload: dict, list_id: str | None = None) -> dict:
    """組み立て済みのタスクを送る。作成されたタスクが返る。

    list_id を渡さなければ既定のリストへ。退避ぶんの再送では、
    中断したときに選んでいたリストを渡す。
    """
    target = str(list_id or cfg['list_id'])
    return api_request(cfg, f'list/{seg(target)}/task', method='POST', body=payload)


# ── 中断中タスクの取得と完了 ──────────────────────────────────

def status_type(task: dict) -> str:
    return ((task.get('status') or {}).get('type') or '').lower()


# 文字の並ぶ向きを変えてしまう制御文字。見えないまま表示だけ入れ替わるので、
# タスク名で「完了ボタンの隣に別のものが見えている」ような細工ができてしまう。
# 一覧にはワークスペースの誰でも自分宛てのタスクを載せられるので、落としておく。
_BIDI_CONTROLS = str.maketrans('', '', '‪‫‬‭‮'
                                       '⁦⁧⁨⁩‏‎')


def _plain(text: str) -> str:
    return (text or '').translate(_BIDI_CONTROLS)


def _summarize(task: dict) -> dict:
    """一覧に出す分だけに削る。

    list_id も持たせる。完了にするときのステータス名はリストごとに違うので、
    どのリストの分かを画面から返してもらう必要があるため。
    """
    text  = (task.get('description') or '').strip()
    first = text.splitlines()[0].strip() if text else ''
    return {
        'id':      task.get('id', ''),
        'name':    _plain(task.get('name', '')),
        'url':     task.get('url', ''),
        'memo':    _plain(first)[:MEMO_MAX],
        'list_id': str((task.get('list') or {}).get('id') or ''),
    }


def _fetch_from_default_list(cfg: dict, limit: int) -> list[dict]:
    """ワークスペース ID がまだ分からないとき用。既定リストだけを見る。"""
    query = urlencode({
        'archived': 'false',
        'subtasks': 'false',
        'order_by': 'created',
        'assignees[]': cfg['user_id'],
    })
    data  = api_request(cfg, f"list/{seg(cfg['list_id'])}/task?{query}")
    tasks = [t for t in data.get('tasks', []) if status_type(t) != CLOSED_TYPE]
    return [_summarize_wide(t) for t in tasks[:limit]]


def fetch_open_tasks(cfg: dict, limit: int = FEED_LIMIT) -> list[dict]:
    """最近登録した中断メモを新しい順に返す。

    既定リストだけでなく、リストを跨いで集める。その場で別のリストへ入れた分が
    翌日には見えなくなると、「どこへ入れたか」を思い出せなくなるため。
    工程のタスクと、除外したリストのぶんは混ぜない（広げた一覧と同じ扱い）。

    共有リストでも他人の分を拾わないよう assignees で自分に限定する。
    order_by=created は既定で新しい順。reverse を付けると古い順に変わるので付けない。
    """
    team = str(cfg.get('team_id') or '')
    if not team:
        return _fetch_from_default_list(cfg, limit)

    query = urlencode({
        'assignees[]':    cfg['user_id'],
        'subtasks':       'false',
        'include_closed': 'false',
        'order_by':       'created',
        'page':           0,
    })
    data     = api_request(cfg, f'team/{seg(team)}/task?{query}')
    excluded = {str(x) for x in cfg.get('excluded_lists', [])}
    tasks    = [t for t in data.get('tasks', []) if is_memo(t, excluded)]
    return [_summarize_wide(t) for t in tasks[:limit]]


_status_cache: dict[str, str] = {}


# 広げた一覧のために、リストを跨いで取ってくるときの上限。
# 1 ページ 100 件。これ以上ある人は、そもそも一覧で見るものではない。
WIDE_MAX_PAGES = 3
WIDE_PAGE_SIZE = 100


def is_memo(task: dict, excluded: set) -> bool:
    """中断メモとして一覧に出すか。

    作られたときのまま open 型（to do）に居るものだけを通す。
    工程を done 型や custom 型で表しているワークスペースでは、
    「本工事」「Mockup」「Maintenance」のような進行中の工程タスクが
    自分の担当として大量に返ってくるため。
    """
    if str((task.get('list') or {}).get('id') or '') in excluded:
        return False
    return status_type(task) == 'open'


def _summarize_wide(task: dict) -> dict:
    """広げた一覧に出す分。通常の一覧より、どこの何かが分かるだけ足す。"""
    listing = task.get('list') or {}
    return {
        **_summarize(task),
        'list_name': _plain(listing.get('name') or ''),
        'due':       task.get('due_date'),
        'status':    _plain((task.get('status') or {}).get('status') or ''),
    }


def fetch_wide_tasks(cfg: dict) -> list[dict]:
    """自分の担当で未完了のものを、リストを跨いで集める。

    期限での絞り込みと並べ替えは画面側でやる。一度取っておけばタブを切り替えても
    通信し直さずに済み、押した瞬間に入れ替わる。
    """
    team = str(cfg.get('team_id') or '')
    if not team:
        return []
    excluded = {str(x) for x in cfg.get('excluded_lists', [])}

    out: list[dict] = []
    for page in range(WIDE_MAX_PAGES):
        query = urlencode({
            'assignees[]':    cfg['user_id'],
            'subtasks':       'false',
            'include_closed': 'false',
            'order_by':       'due_date',
            'page':           page,
        })
        data  = api_request(cfg, f'team/{seg(team)}/task?{query}')
        batch = data.get('tasks', [])
        out.extend(_summarize_wide(t) for t in batch if is_memo(t, excluded))
        if data.get('last_page') or len(batch) < WIDE_PAGE_SIZE:
            break
    return out


def closed_status_name(cfg: dict, list_id: str | None = None) -> str:
    """このリストで「完了」を表すステータス名。

    ステータスはワークスペースごとに違うので決め打ちにせず、リストの定義から引く。
    closed 型を先に探すのが肝心。done 型にも「完了」らしい名前が付いていることがあるが、
    そちらへ移しても一覧を取り直すとまだ返ってくる（ClickUp が「閉じた」と見なすのは
    closed 型だけ）ので、押しても消えないタスクができてしまう。
    引いた結果はプロセスが生きている間だけ覚えておく（config.json には書かない）。
    """
    global _status_cache
    key = str(list_id or cfg['list_id'])
    if key in _status_cache:
        return _status_cache[key]

    statuses = api_request(cfg, f'list/{seg(key)}').get('statuses', [])
    name = ''
    for wanted in COMPLETION_TYPES:
        for status in statuses:
            if status.get('type') == wanted:
                name = status.get('status', '')
                break
        if name:
            break

    name = name or 'complete'
    _status_cache = {**_status_cache, key: name}
    return name


def complete_task(cfg: dict, task_id: str, list_id: str | None = None) -> None:
    """完了にする。変わったことを応答で確かめてから返る。

    画面が行を消すのは、ここが例外を投げなかったときだけ。「消えたのに ClickUp 側は
    変わっていない」が起きると、利用者は片付けたつもりで溜め続けることになる。
    """
    target = closed_status_name(cfg, list_id)
    task   = api_request(cfg, f'task/{seg(task_id)}', method='PUT', body={'status': target})

    got = ((task.get('status') or {}).get('status') or '').strip()
    if not got:
        return          # 応答の形が想定と違う。送れてはいるので、ここでは止めない
    if got.lower() != target.strip().lower():
        raise RuntimeError(f'完了になりませんでした'
                           f'（「{target}」を送りましたが「{got}」のままです）')
