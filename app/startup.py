"""自動起動とウォッチドッグの登録。

初回設定の最後にまとめて有効にする。利用者に .bat を探して実行してもらうと、
そこで止まってしまうため。解除だけは「設定を解除するとき」フォルダの
.bat からもできるようにしてある。
"""
import os
import subprocess

CREATE_NO_WINDOW = 0x08000000      # 実行中に黒い窓を出さない
TASK_NAME        = 'PauseTask Watchdog'
SHORTCUT_NAME    = 'PauseTask.lnk'
TIMEOUT_SEC      = 90


def _powershell(args: list[str], extra_env: dict | None = None) -> tuple[bool, str]:
    """PowerShell を黙って走らせる。(成功したか, 出力) を返す。"""
    cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', *args]
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT_SEC,
            creationflags=CREATE_NO_WINDOW,
            env={**os.environ, **(extra_env or {})},
        )
    except Exception as e:
        return False, str(e)
    output = ((done.stdout or '') + (done.stderr or '')).strip()
    return done.returncode == 0, output


# ── 自動起動（スタートアップへのショートカット） ──────────────

# パスに ' や空白が混ざっても壊れないよう、値は環境変数で渡す。
_MAKE_SHORTCUT = (
    "$path = [Environment]::GetFolderPath('Startup') + '\\' + $env:PT_SHORTCUT; "
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path); "
    "$s.TargetPath = $env:PT_TARGET; "
    "$s.Arguments = $env:PT_ARGS; "
    "$s.WorkingDirectory = $env:PT_WORKDIR; "
    "$s.Save()"
)

_REMOVE_SHORTCUT = (
    "$path = [Environment]::GetFolderPath('Startup') + '\\' + $env:PT_SHORTCUT; "
    "if (Test-Path $path) { Remove-Item $path -Force }"
)


def enable_autostart(target: str, workdir: str, arguments: str = '') -> tuple[bool, str]:
    """サインイン時に target が起動するようにする。

    arguments を使うのは配布版。pythonw.exe に pause.pyw を渡す形にして、
    サインインのたびに黒い窓が一瞬出るのを避ける。
    """
    return _powershell(['-Command', _MAKE_SHORTCUT], {
        'PT_SHORTCUT': SHORTCUT_NAME, 'PT_TARGET': target,
        'PT_ARGS': arguments, 'PT_WORKDIR': workdir,
    })


def disable_autostart() -> tuple[bool, str]:
    return _powershell(['-Command', _REMOVE_SHORTCUT], {'PT_SHORTCUT': SHORTCUT_NAME})


# ── ウォッチドッグ（タスクスケジューラ） ──────────────────────

def enable_watchdog(register_script: str) -> tuple[bool, str]:
    """5 分ごとに常駐の生死を見る見張りを登録する。

    登録の中身は register-watchdog.ps1 に置いてある（XML 定義が長く、
    バッテリー稼働時の扱いなど PowerShell 側で完結させたいため）。
    """
    if not os.path.exists(register_script):
        return False, f'{os.path.basename(register_script)} が見つかりません'
    return _powershell(['-File', register_script])


def disable_watchdog() -> tuple[bool, str]:
    return _powershell(['-Command',
                        f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' "
                        "-Confirm:$false -ErrorAction Stop"])
