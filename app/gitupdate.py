"""Git を触るのはこのモジュールだけに閉じる。

配布物は Git のリポジトリとして置かれる。新しい版が出ていないかを見て、
必要なら取り込む。更新そのものは updater.pyw が別プロセスで行う
（自分自身のファイルを書き換えながら動くわけにいかないため）。

安全のための決めごと:
  ・取り込みは fast-forward だけ。マージも履歴の書き換えもしない
  ・手元に直したファイルがあるときは触らない（dirty なら止める）
  ・reset --hard は使わない。利用者の変更を消す道を作らない
"""
import json
import os
import shutil
import subprocess
import time

import appconfig

# 更新の状態を書いておく場所。Git の管理外（.gitignore 済み）。
STATUS_NAME = 'update-status.json'
LOG_DIR     = 'update-log'
BACKUP_DIR  = 'backup'

# 更新のときに必ず控えておくもの。無くなると設定のやり直しになる。
PROTECTED = ['config.json', 'directory.json', 'outbox.json', 'outbox_failed.json']

TIMEOUT = 60
CREATE_NO_WINDOW = 0x08000000


def repo_root() -> str:
    """リポジトリの根。app/ の 1 つ上。"""
    return os.path.dirname(appconfig.BASE)


def status_path() -> str:
    return os.path.join(appconfig.BASE, STATUS_NAME)


def git_path() -> str:
    """使う git。同梱したものを優先し、無ければパスの通ったものを探す。

    配布物には MinGit を入れてあるので、利用者は何もインストールしなくてよい。
    開発機では入っている git を使う。
    """
    bundled = os.path.join(repo_root(), 'mingit', 'cmd', 'git.exe')
    if os.path.exists(bundled):
        return bundled
    return shutil.which('git') or ''


def run_git(*args: str, cwd: str | None = None, timeout: int = TIMEOUT):
    """git を 1 回動かす。(成功したか, 出力) を返す。

    黒い窓を出さない。常駐から呼ぶので、そのたびにコンソールが瞬くと目障りなため。
    """
    git = git_path()
    if not git:
        return False, 'git が見つかりません'
    try:
        done = subprocess.run(
            [git, *args],
            cwd=cwd or repo_root(),
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, f'git {args[0]} が {timeout} 秒で終わりませんでした'
    except OSError as e:
        return False, str(e)
    out = (done.stdout or '') + (done.stderr or '')
    return done.returncode == 0, out.strip()


def _empty_status(state: str, message: str) -> dict:
    return {
        'state': state, 'message': message,
        'branch': '', 'upstream': '',
        'localSha': '', 'remoteSha': '',
        'ahead': 0, 'behind': 0, 'dirty': False,
        'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }


def _short(sha: str) -> str:
    return (sha or '')[:7]


def check_status(fetch: bool = True) -> dict:
    """新しい版が出ていないかを見る。

    返す state は 5 つ。
      not_configured … Git の管理下でない、または取得先が決まっていない
      checking_failed … 取りに行けなかった（ネットが無い、git が無い等）
      blocked        … 手元に直したファイルがある。触らない
      available      … 新しい版がある
      current        … いまが最新
    """
    if not git_path():
        return _empty_status('not_configured', 'git が見つかりません')

    ok, _ = run_git('rev-parse', '--is-inside-work-tree')
    if not ok:
        return _empty_status('not_configured', 'このフォルダは Git で管理されていません')

    ok, branch = run_git('branch', '--show-current')
    if not ok or not branch:
        return _empty_status('not_configured', 'ブランチが決まっていません')

    ok, upstream = run_git('rev-parse', '--abbrev-ref', '@{u}')
    if not ok:
        got = _empty_status('not_configured', '取得先（upstream）が設定されていません')
        got['branch'] = branch
        return got

    if fetch:
        ok, out = run_git('fetch', '--prune')
        if not ok:
            got = _empty_status('checking_failed', f'取りに行けませんでした（{out[:80]}）')
            got['branch'], got['upstream'] = branch, upstream
            return got

    _, dirty_out = run_git('status', '--short')
    _, local_sha = run_git('rev-parse', 'HEAD')
    _, remote_sha = run_git('rev-parse', '@{u}')
    ok, counts = run_git('rev-list', '--left-right', '--count', 'HEAD...@{u}')

    ahead = behind = 0
    if ok and counts:
        parts = counts.split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    dirty = bool(dirty_out.strip())
    got = {
        'state': 'current', 'message': 'いまが最新です',
        'branch': branch, 'upstream': upstream,
        'localSha': local_sha, 'remoteSha': remote_sha,
        'ahead': ahead, 'behind': behind, 'dirty': dirty,
        'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }

    if behind and dirty:
        # 手を入れたファイルがあるまま取り込むと、その変更を巻き込む。触らない。
        got['state'] = 'blocked'
        got['message'] = ('新しい版がありますが、手元に変更されたファイルがあるため'
                          '取り込めません')
    elif behind:
        got['state'] = 'available'
        got['message'] = f'新しい版があります（{behind} 件の更新）'
    return got


def changes_summary(limit: int = 8) -> list[str]:
    """取り込むと何が変わるか。コミットの見出しを新しい順に。"""
    ok, out = run_git('log', '--oneline', f'-{limit}', 'HEAD..@{u}')
    if not ok or not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


# ── 状態の保存 ────────────────────────────────────────────────

def load_status() -> dict:
    """前回の結果。無い・壊れているときは空として扱う。"""
    try:
        with open(status_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_status(data: dict) -> None:
    """状態を書く。書けなくても更新そのものは進めたいので、失敗は握る。"""
    try:
        os.makedirs(appconfig.BASE, exist_ok=True)
        temporary = status_path() + '.writing'
        with open(temporary, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temporary, status_path())
    except OSError as e:
        appconfig.log(f'警告: 更新の状態を保存できませんでした ({e})')


def set_run_state(state: str, step: str, progress: int, message: str,
                  log_path: str = '', backup_path: str = '') -> None:
    """更新の進み具合を書き足す。各段階の前に呼ぶ。

    画面は 1〜3 秒ごとにこれを読む。ここが進まないまま止まっていたら、
    更新が始まっていないということ。
    """
    current = load_status()
    current['lastRun'] = {
        'state': state, 'currentStep': step, 'progress': progress,
        'message': message, 'logPath': log_path, 'backupPath': backup_path,
        'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    save_status(current)
