"""自動起動とウォッチドッグの登録。

初回設定の最後にまとめて有効にする。利用者に .bat を探して実行してもらうと、
そこで止まってしまうため。解除だけは「設定を解除するとき」フォルダの
.bat からもできるようにしてある。
"""
import os
import subprocess
import sys

import appconfig

CREATE_NO_WINDOW = 0x08000000      # 実行中に黒い窓を出さない
TASK_NAME        = 'PauseTask Watchdog'
SHORTCUT_NAME    = 'PauseTask.lnk'
TIMEOUT_SEC      = 90


def _powershell_path() -> str:
    """PowerShell の場所。

    'powershell' と名前だけで渡すと、Windows は PATH より先に「いまの作業フォルダ」を
    探す。配布物を展開した場所に powershell.exe という名前のファイルを置ける相手がいれば、
    そちらが動いてしまう。同梱 git を絶対パスで呼んでいるのと同じ理由で、ここも場所を決め打つ。
    """
    root = os.environ.get('SystemRoot') or r'C:\Windows'
    full = os.path.join(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    return full if os.path.exists(full) else 'powershell'


POWERSHELL = _powershell_path()


def _powershell(args: list[str], extra_env: dict | None = None) -> tuple[bool, str]:
    """PowerShell を黙って走らせる。(成功したか, 出力) を返す。"""
    cmd = [POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', *args]
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

# 何が登録されているかを読む。区切りに | を使うのは、Windows のパスに入らない文字だから。
_READ_SHORTCUT = (
    "$path = [Environment]::GetFolderPath('Startup') + '\\' + $env:PT_SHORTCUT; "
    "if (-not (Test-Path $path)) { exit 0 }; "
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path); "
    "Write-Output ($s.TargetPath + '|' + $s.Arguments)"
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


def autostart_link() -> tuple[str, str]:
    """いま登録されている自動起動の (実行するファイル, 引数)。登録が無ければ ('', '')。"""
    ok, output = _powershell(['-Command', _READ_SHORTCUT], {'PT_SHORTCUT': SHORTCUT_NAME})
    if not ok or '|' not in output:
        return '', ''
    target, _, args = output.strip().partition('|')
    return target.strip(), args.strip()


def autostart_spec() -> tuple[str, str, str]:
    """サインイン時に起動するもの。(実行するファイル, 引数, 作業フォルダ)。

    配布版は app/ の隣に runtime/ がある。そこの pythonw.exe を直に指すことで、
    サインインのたびに黒い窓が一瞬出るのを避ける。
    """
    base   = appconfig.BASE
    script = f'"{os.path.join(base, "pause.pyw")}"'

    bundled_py = os.path.join(os.path.dirname(base), 'runtime', 'pythonw.exe')
    if os.path.exists(bundled_py):
        return bundled_py, script, base

    # 同梱の runtime が無い＝開発中に直接動かしているとき。
    # いま自分を動かしている Python を指す。launch.bat は配布物には無いので、
    # それを指したままにすると「存在しないものを起動する」登録ができてしまう。
    here = os.path.dirname(sys.executable)
    for name in ('pythonw.exe', 'python.exe'):
        candidate = os.path.join(here, name)
        if os.path.exists(candidate):
            return candidate, script, base

    return os.path.join(base, 'launch.bat'), '', base


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


def watchdog_command() -> str:
    """いま登録されている見張り役が呼んでいる .vbs のパス。登録が無ければ ''。"""
    ok, output = _powershell(
        ['-Command',
         "$t = Get-ScheduledTask -TaskName $env:PT_TASK -ErrorAction SilentlyContinue; "
         "if ($t) { Write-Output $t.Actions[0].Arguments }"],
        {'PT_TASK': TASK_NAME})
    return output.strip().strip('"') if ok else ''


# ── まとめて有効にする ───────────────────────────────────────

def enable_all() -> tuple[bool, str]:
    """自動起動とウォッチドッグをまとめて有効にする。

    自動起動が入れば「次から勝手に立ち上がる」は満たせるので、
    見張り役だけ失敗しても全体は成功として扱い、理由だけ残す。
    """
    target, args, workdir = autostart_spec()
    ok, out = enable_autostart(target, workdir, args)
    if not ok:
        appconfig.log(f'警告: 自動起動を登録できませんでした ({out})')
        return False, out

    watch_ok, watch_out = enable_watchdog(appconfig.bundled('register-watchdog.ps1'))
    if not watch_ok:
        appconfig.log(f'警告: ウォッチドッグを登録できませんでした ({watch_out})')
        return True, '見張り役の登録だけできませんでした（自動起動は有効です）'
    appconfig.log('自動起動とウォッチドッグを登録しました')
    return True, ''


# ── 引っ越しへの追従 ─────────────────────────────────────────

def _elsewhere(registered: str, base: str) -> bool:
    """登録されている中身が、いまいるフォルダを指していないか。

    区切り文字まで含めて見る。そうしないと `...\\app` が `...\\app2` にも当たる。
    登録の中身は必ず `<base>\\pause.pyw` や `<base>\\watchdog.vbs` の形なので、
    区切りが続くことを当てにしてよい。
    """
    return os.path.normcase(base + os.sep) not in os.path.normcase(registered)


def realign() -> list[str]:
    """登録済みの自動起動と見張り役が、いまいる場所を指すように直す。

    直したものの名前を返す。フォルダごと移動されると、どちらも前の場所を
    指したまま残り、黙って起動しなくなる（見張り役はエラー窓を出し続ける）。

    登録が無いものは登録しない。利用者が自分で切ったものを勝手に戻さないため。
    """
    base  = appconfig.BASE
    fixed = []

    target, args = autostart_link()
    if target and _elsewhere(target + ' ' + args, base):
        spec_target, spec_args, workdir = autostart_spec()
        if not os.path.exists(spec_target):
            # 起動できないものを指す登録に差し替えては、直すどころか壊すことになる。
            appconfig.log(f'警告: 自動起動を直せません（{spec_target} が見つかりません）。'
                          '前の登録のままにします')
        else:
            ok, out = enable_autostart(spec_target, workdir, spec_args)
            if ok:
                fixed.append('自動起動')
            else:
                appconfig.log(f'警告: 自動起動を今の場所へ直せませんでした ({out})')

    vbs = watchdog_command()
    if vbs and _elsewhere(vbs, base):
        ok, out = enable_watchdog(appconfig.bundled('register-watchdog.ps1'))
        if ok:
            fixed.append('見張り役')
        else:
            appconfig.log(f'警告: 見張り役を今の場所へ直せませんでした ({out})')

    return fixed
