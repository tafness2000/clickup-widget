"""更新を実行する係。常駐とは別のプロセスで動く。

常駐が自分自身のファイルを書き換えながら動くわけにいかないので、こちらへ渡す。
呼ばれ方:
    pythonw.exe updater.pyw

進め方は決まっている。各段階の前に update-status.json を書くので、
途中で止まっても「どこまで進んだか」が残る。
    queued 1% → start 5% → git-check 10% → backup-data 18%
    → git-fetch 28% → git-fast-forward 42% → build-or-check 76%
    → restart 94% → done 100%

やらないこと:
    ・reset --hard、強制の checkout、履歴の書き換え、force push
    ・管理者権限を要る操作
利用者が手を入れたファイルがあるときは、触らずに止める。
"""
import os
import shutil
import subprocess
import sys
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import appconfig
import gitupdate

CREATE_NO_WINDOW = 0x08000000

# 常駐が終わるのを待つ上限。これを過ぎたら諦める（掴んだままのファイルを
# 書き換えると壊れるので、待てないなら何もしない方がよい）。
WAIT_EXIT_SEC = 20


class Failed(Exception):
    """更新を続けられない。理由をそのまま利用者へ見せる。"""


class Log:
    """更新 1 回ぶんの記録。何をして何が返ったかを残す。"""

    def __init__(self) -> None:
        stamp = time.strftime('%Y%m%d-%H%M%S')
        self.dir  = os.path.join(appconfig.BASE, gitupdate.LOG_DIR)
        self.path = os.path.join(self.dir, f'update-{stamp}.log')
        os.makedirs(self.dir, exist_ok=True)
        self.write(f'=== 更新を開始します {time.strftime("%Y-%m-%d %H:%M:%S")} ===')

    def write(self, line: str) -> None:
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(line.rstrip() + '\n')
        except OSError:
            pass


def git(log: Log, *args: str) -> str:
    """git を動かして、結果をログに残す。失敗したら止める。"""
    log.write(f'$ git {" ".join(args)}')
    ok, out = gitupdate.run_git(*args)
    if out:
        log.write(out)
    if not ok:
        raise Failed(f'git {args[0]} に失敗しました: {out[:120]}')
    return out


# ── 各段階 ────────────────────────────────────────────────────

def step_git_check(log: Log) -> None:
    gitupdate.set_run_state('running', 'git-check', 10, '手元の状態を確かめています',
                            log.path)
    out = git(log, 'status', '--short')
    if out.strip():
        # 利用者が何か直している。上書きすると消えるので、ここで止める。
        raise Failed('手元に変更されたファイルがあるため、更新を中止しました。\n'
                     '変更を保存または元に戻してから、もう一度お試しください。')


def step_backup(log: Log) -> str:
    stamp  = time.strftime('%Y%m%d-%H%M%S')
    target = os.path.join(appconfig.BASE, gitupdate.BACKUP_DIR, f'backup-{stamp}')
    gitupdate.set_run_state('running', 'backup-data', 18, '設定と未送信分を控えています',
                            log.path, target)
    os.makedirs(target, exist_ok=True)
    saved = 0
    for name in gitupdate.PROTECTED:
        src = os.path.join(appconfig.BASE, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(target, name))
            saved += 1
    log.write(f'控えました: {saved} 件 → {target}')
    return target


def step_pull(log: Log, backup: str) -> str:
    gitupdate.set_run_state('running', 'git-fetch', 28, '新しい版を取りに行っています',
                            log.path, backup)
    git(log, 'fetch', '--prune')

    gitupdate.set_run_state('running', 'git-fast-forward', 42, '新しい版を取り込んでいます',
                            log.path, backup)
    # fast-forward だけ。マージのコミットを作らせない。
    git(log, 'pull', '--ff-only')
    return git(log, 'rev-parse', 'HEAD')


def step_check_code(log: Log, backup: str) -> None:
    """取り込んだコードが壊れていないか。動かす前に構文だけ見る。"""
    gitupdate.set_run_state('running', 'build-or-check', 76, '取り込んだ内容を確かめています',
                            log.path, backup)
    targets = [os.path.join(appconfig.BASE, n) for n in os.listdir(appconfig.BASE)
               if n.endswith(('.py', '.pyw'))]
    log.write(f'$ py_compile ({len(targets)} ファイル)')
    done = subprocess.run([sys.executable, '-m', 'py_compile', *targets],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', creationflags=CREATE_NO_WINDOW)
    if done.stdout:
        log.write(done.stdout)
    if done.returncode != 0:
        log.write(done.stderr or '')
        raise Failed('取り込んだコードに問題があります。\n'
                     f'控えは {backup} にあります。')


def step_restart(log: Log, backup: str) -> None:
    gitupdate.set_run_state('running', 'restart', 94, '起動し直しています', log.path, backup)
    script = os.path.join(appconfig.BASE, 'pause.pyw')
    pythonw = os.path.join(os.path.dirname(appconfig.BASE), 'runtime', 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = sys.executable            # 開発機ではいま動いているものを使う
    log.write(f'$ {pythonw} {script}')
    subprocess.Popen([pythonw, script], cwd=appconfig.BASE,
                     creationflags=CREATE_NO_WINDOW)


def wait_for_exit(log: Log) -> None:
    """常駐が終わるのを待つ。掴まれたままのファイルを書き換えないため。"""
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    for _ in range(WAIT_EXIT_SEC * 2):
        handle = kernel32.CreateMutexW(None, False, 'Local\\ClickUpPauseSingleton')
        already = ctypes.get_last_error() == 183      # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        if not already:
            return
        time.sleep(0.5)
    log.write('警告: 常駐が終わるのを待ちきれませんでした。そのまま続けます。')


def main() -> None:
    log = Log()
    backup = ''
    try:
        gitupdate.set_run_state('running', 'start', 5, '更新を始めます', log.path)
        wait_for_exit(log)

        step_git_check(log)
        backup = step_backup(log)
        head = step_pull(log, backup)
        step_check_code(log, backup)
        step_restart(log, backup)

        gitupdate.set_run_state('completed', 'done', 100,
                                f'新しい版になりました（{head[:7]}）', log.path, backup)
        log.write(f'=== 完了しました（{head[:7]}） ===')

    except Failed as e:
        log.write(f'=== 中止しました: {e} ===')
        gitupdate.set_run_state('failed', 'failed', 100, str(e), log.path, backup)
        _restart_after_failure(log)

    except Exception as e:                        # 想定外。状態を残して知らせる
        log.write('=== 想定外の失敗 ===')
        log.write(traceback.format_exc())
        gitupdate.set_run_state('failed', 'failed', 100,
                                f'更新の途中で想定外の失敗をしました（{e}）',
                                log.path, backup)
        _restart_after_failure(log)


def _restart_after_failure(log: Log) -> None:
    """失敗しても常駐は戻す。使えないまま放置しない。"""
    try:
        step_restart(log, '')
    except Exception as e:
        log.write(f'起動し直せませんでした: {e}')


if __name__ == '__main__':
    main()
