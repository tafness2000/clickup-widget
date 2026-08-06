"""リストとメンバーの一覧を手元に控えておく。

登録先を選べるようにすると候補が要る。ところが ClickUp には「全リストを
一発で返す」口が無く、スペースとフォルダを辿って 30 回以上叩くことになる。
ホットキーを押すたびにそれをやっては窓が出るのが遅くなるので、
起動時に裏で取ってここへ保存し、以後は手元の控えから出す。
"""
import json
import os
import time

FILE_NAME   = 'directory.json'
MAX_AGE_SEC = 24 * 60 * 60      # 1 日経ったら取り直す


def _path(base: str) -> str:
    return os.path.join(base, FILE_NAME)


def load(base: str) -> dict:
    """控えを読む。無い・壊れているときは空として扱う（起動を止めない）。"""
    path = _path(base)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(base: str, data: dict) -> None:
    """一時ファイルに書いてから置き換える。

    直に上書きすると、書いている最中に読んだ側が途中までの JSON を掴む。
    取り直しは裏のスレッドが 1 日 1 回やるので、読み手（既定の入れ替えなど）と
    重なる瞬間が必ずある。
    """
    path      = _path(base)
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temporary, path)


def is_stale(data: dict, now: float | None = None) -> bool:
    """取り直すべきか。中身が空なら常に取り直す。"""
    if not data.get('lists') and not data.get('members'):
        return True
    fetched = data.get('fetched_at')
    if not isinstance(fetched, (int, float)):
        return True
    return (time.time() if now is None else now) - fetched > MAX_AGE_SEC


def default_list_entry(cfg: dict, data: dict) -> dict:
    """既定リストを、候補と同じ形（id / name / path）で返す。

    控えがまだ無いうちは名前が引けないので、config に控えた表示名か ID を出す。
    """
    list_id = str(cfg.get('list_id', ''))
    for item in data.get('lists', []):
        if str(item.get('id')) == list_id:
            return item
    return {'id': list_id, 'name': cfg.get('list_name') or list_id, 'path': ''}


def fill_names(cfg: dict, data: dict) -> dict:
    """一覧から引ける表示用の名前を config に補った新しい設定を返す。

    初回はワークスペース ID も既定リストの表示名も config に無い。
    設定画面の項目を増やさずに済ませるため、一覧が取れたついでにここで埋める。
    """
    filled = dict(cfg)
    if data.get('team_id'):
        filled['team_id'] = data['team_id']
    entry = default_list_entry(cfg, data)
    if entry.get('name'):
        filled['list_name'] = entry['name']
    if not filled.get('user_name'):
        for member in data.get('members', []):
            if str(member.get('id')) == str(cfg.get('user_id')):
                filled['user_name'] = member.get('name', '')
                break
    return filled


def build_payload(cfg: dict, data: dict) -> dict:
    """ui.html の setDirectory に渡す形に整える。"""
    import appconfig      # 呼ばれるのはここだけ。読み込み順の縛りを作らないよう中で import する

    return {
        'lists':        data.get('lists', []),
        'members':      data.get('members', []),
        'default_list': default_list_entry(cfg, data),
        'self': {
            'id':    cfg.get('user_id'),
            'name':  cfg.get('user_name') or '自分',
            'email': cfg.get('user_email', ''),
        },
        'recent':      [str(x) for x in cfg.get('recent_lists', [])],
        'favorites':   appconfig.favorites(cfg),
        'default_due': cfg.get('default_due_preset') or 'today',
        'excluded':    appconfig.excluded_lists(cfg),
    }
