"""配布物の組み立て。リポジトリの直下で実行する:
    python build.py
出力: dist/ClickUpWidget/ （zip 化して配布する）

リポジトリの形は、配布物の中身とそろえてある（app/ と manual/ がそのまま入る）。
利用者のフォルダで git pull できるようにするため。runtime/ と mingit/ だけは
重すぎるので Git に入れず、ここで用意する。

PyInstaller で 1 つの exe に固める作りをやめ、署名済みの pythonw.exe と Qt を
そのまま同梱する形にした。Windows 11 の Smart App Control は署名も実績も無い
実行ファイルを問答無用で弾くため、自前でビルドした exe はダブルクリックしても
起動しない（実測済み）。同梱する pythonw.exe は Python Software Foundation、
QtWebEngineProcess.exe は The Qt Company、git.exe は Git for Windows の署名が
あるので、そのまま通る。
"""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = 'ClickUpWidget'

HERE     = Path(__file__).parent
SRC_APP  = HERE / 'app'                     # コードの置き場所
DIST_DIR = HERE / 'dist' / APP_NAME
ZIP_OUT  = HERE / 'dist' / f'{APP_NAME}配布版.zip'

PY_ROOT  = Path(sys.executable).parent      # 元にする Python
APP_DIR  = DIST_DIR / 'app'
RT_DIR   = DIST_DIR / 'runtime'
GIT_DIR  = DIST_DIR / 'mingit'

LAUNCHER_NAME = f'{APP_NAME} を起動.bat'
MANUAL_NAME   = '取扱説明書.html'
MANUAL_DIR    = HERE / 'manual'
UNDO_DIR_NAME = '設定を解除するとき'
UNDO_FILES    = ['自動起動を解除する.bat', 'ウォッチドッグを解除する.bat']

# 常駐そのもの。__pycache__ は持っていかない。
APP_FILES = [
    'pause.pyw', 'updater.pyw',
    'appconfig.py', 'bridge.py', 'clickup_api.py', 'directory.py', 'feeds.py',
    'gitupdate.py', 'ime.py', 'layout.py', 'outbox.py', 'secretstore.py', 'startup.py',
    'ui.html', 'ui.css', 'ui.js', 'picker.js', 'wide.js', 'update.js', 'setup.html',
    'watchdog.ps1', 'watchdog.vbs', 'register-watchdog.ps1',
]

# 実行に要らないもの。入れても動くが、その分だけ配布物が重くなる。
STDLIB_SKIP = {'site-packages', 'test', 'tests', 'idlelib', 'tkinter',
               'lib2to3', 'ensurepip', 'turtledemo', '__pycache__'}
DLL_SKIP_PREFIX = ('_test', 'tcl', 'tk', '_tkinter')
QT_SKIP_DIRS = {'bindings', 'uic', 'lupdate', '__pycache__'}
QT6_SKIP_DIRS = {'qsci', 'lib'}
# 翻訳は日本語と英語だけ残す。全部入れると 50MB 以上になる。
KEEP_LOCALES = {'ja.pak', 'en-US.pak'}


def _ignore(skip_dirs: set, skip_prefix: tuple = ()):
    def ignore(src, names):
        out = []
        for name in names:
            full = Path(src) / name
            if full.is_dir() and name in skip_dirs:
                out.append(name)
            elif name.startswith(skip_prefix) or name.endswith(('.lib', '.prl', '.pdb')):
                out.append(name)
        return out
    return ignore


def copy_runtime() -> None:
    """署名済みの Python と Qt を runtime/ へ運ぶ。"""
    RT_DIR.mkdir(parents=True, exist_ok=True)

    for name in ['pythonw.exe', 'python.exe', 'python3.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll']:
        src = PY_ROOT / name
        if src.exists():
            shutil.copy(src, RT_DIR / name)
    for dll in PY_ROOT.glob('python3*.dll'):
        shutil.copy(dll, RT_DIR / dll.name)

    shutil.copytree(PY_ROOT / 'Lib', RT_DIR / 'Lib', ignore=_ignore(STDLIB_SKIP),
                    dirs_exist_ok=True)
    shutil.copytree(PY_ROOT / 'DLLs', RT_DIR / 'DLLs',
                    ignore=_ignore({'__pycache__'}, DLL_SKIP_PREFIX), dirs_exist_ok=True)

    site = RT_DIR / 'Lib' / 'site-packages'
    site.mkdir(parents=True, exist_ok=True)
    src_site = PY_ROOT / 'Lib' / 'site-packages'
    shutil.copytree(src_site / 'PyQt6', site / 'PyQt6',
                    ignore=_ignore(QT_SKIP_DIRS), dirs_exist_ok=True)
    for extra in src_site.glob('PyQt6_sip*'):
        if extra.is_file():
            shutil.copy(extra, site / extra.name)

    prune_qt(site / 'PyQt6' / 'Qt6')
    write_path_file()


def prune_qt(qt6: Path) -> None:
    for name in QT6_SKIP_DIRS:
        shutil.rmtree(qt6 / name, ignore_errors=True)

    locales = qt6 / 'translations' / 'qtwebengine_locales'
    for pak in locales.glob('*.pak'):
        if pak.name not in KEEP_LOCALES:
            pak.unlink()
    for qm in (qt6 / 'translations').glob('*.qm'):
        if '_ja' not in qm.name and '_en' not in qm.name:
            qm.unlink()


MINGIT_CACHE = HERE / '.cache'

# 同梱する Git。落としたものが本物かを、公式が公表している値と突き合わせて確かめる。
# 署名の確認は exe しか見ないので、DLL をすり替えられても気づけない。
# 上げるときは Git for Windows のリリースノートに載っている値をそのまま書き写す。
#   https://github.com/git-for-windows/git/releases
MINGIT_ZIP    = 'MinGit-2.55.0.3-64-bit.zip'
MINGIT_SHA256 = 'f48e2d2dc74a24454adc6d8fd0ac25bf9c2386f19cfb06202b9465aaad4f9f05'

# MinGit には署名の無い実行ファイルが 74 個入っている（Unix ツール群と補助のもの）。
# Smart App Control はそれを弾くので、同梱するわけにいかない。
# 使うのは HTTPS 経由の fetch / pull / status だけなので、下記を落としても動く
# （実際に clone → fetch → status → pull を通して確かめた。89.5MB → 60.8MB）。
MINGIT_DROP_DIRS  = ['usr']
MINGIT_DROP_FILES = [
    r'mingw64\bin\blocked-file-util.exe', r'mingw64\bin\brotli.exe',
    r'mingw64\bin\git-askpass.exe', r'mingw64\bin\git-askyesno.exe',
    r'mingw64\bin\git-credential-helper-selector.exe',
    r'mingw64\bin\printf_gettext.exe', r'mingw64\bin\printf_ngettext.exe',
    r'mingw64\bin\proxy-lookup.exe', r'mingw64\bin\psl.exe',
    r'mingw64\bin\scalar.exe',
    r'cmd\git-receive-pack.exe', r'cmd\git-upload-pack.exe',
]


def prune_mingit() -> None:
    """署名の無いものを落とす。残っていると check_signatures がビルドを止める。"""
    for name in MINGIT_DROP_DIRS:
        shutil.rmtree(GIT_DIR / name, ignore_errors=True)
    for name in MINGIT_DROP_FILES:
        (GIT_DIR / name).unlink(missing_ok=True)


def copy_mingit() -> None:
    """Git を同梱する。利用者に別途インストールさせないため。

    配布物は Git のリポジトリとして置かれ、そこから新しい版を取り込む。
    Git for Windows の MinGit は署名済みなので Smart App Control を通る。
    一度落としたものは .cache に取っておき、毎回のビルドで取り直さない。
    """
    if GIT_DIR.exists():
        print(f'  Git: すでにあります（{GIT_DIR.name}）')
        return

    MINGIT_CACHE.mkdir(exist_ok=True)
    cached = MINGIT_CACHE / MINGIT_ZIP
    if not cached.exists():
        raise SystemExit(
            f'{MINGIT_ZIP} が見つかりません。次で取得してから、もう一度ビルドしてください:\n'
            '  gh release download --repo git-for-windows/git --pattern "MinGit-*-64-bit.zip" '
            f'--dir "{MINGIT_CACHE}"')

    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    if digest != MINGIT_SHA256:
        raise SystemExit(
            f'{MINGIT_ZIP} の中身が、公式の値と一致しません。配布できません。\n'
            f'  手元    : {digest}\n'
            f'  あるべき: {MINGIT_SHA256}\n'
            '（落とし直すか、版を上げたなら build.py の値も直してください）')

    print(f'  Git: {cached.name} を展開します（SHA256 一致）')
    GIT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cached) as zf:
        zf.extractall(GIT_DIR)

    prune_mingit()

    git_exe = GIT_DIR / 'cmd' / 'git.exe'
    if not git_exe.exists():
        raise SystemExit(f'展開したのに git.exe がありません: {git_exe}')
    size = sum(p.stat().st_size for p in GIT_DIR.rglob('*') if p.is_file())
    print(f'  Git: 署名の無いものを外して {size / 1024 / 1024:.1f} MB')


def write_path_file() -> None:
    """Python を隔離モードにして、持ち運べるようにする。

    このファイルがあると、入れた先のパソコンに別の Python が入っていても
    そちらのライブラリを拾わない。
    """
    version = f'{sys.version_info.major}{sys.version_info.minor}'
    (RT_DIR / f'python{version}._pth').write_text(
        'Lib\nDLLs\nLib\\site-packages\n.\nimport site\n', encoding='utf-8')


def copy_app() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    for name in APP_FILES:
        shutil.copy(SRC_APP / name, APP_DIR / name)

    # 中身は初回設定の画面から書き込まれる。空の器だけ置いておく。
    (APP_DIR / 'config.json').write_text(
        '{\n  "api_token": "",\n  "list_id": "",\n  "user_id": null,\n'
        '  "recent_lists": []\n}\n', encoding='utf-8')


def build_manual() -> None:
    """説明書を 1 枚の HTML に組み立てる。

    画面写真は data URI で埋め込む。ファイルが 1 つで済むので、
    渡された人がどこへ置いても画像が切れない。
    """
    template = (MANUAL_DIR / 'template.html').read_text(encoding='utf-8')
    shots    = MANUAL_DIR / 'shots'

    used, missing = 0, []

    def embed(match: re.Match) -> str:
        nonlocal used
        name = match.group(1)
        path = shots / f'{name}.png'
        if not path.exists():
            missing.append(name)
            return ''
        used += 1
        return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')

    html = re.sub(r'\{\{IMG:([\w-]+)\}\}', embed, template)
    if missing:
        raise SystemExit('説明書に貼る画面写真が足りません: ' + ', '.join(missing)
                         + '\n（manual/take_shots.py で撮り直してください）')

    out = DIST_DIR / MANUAL_NAME
    out.write_text(html, encoding='utf-8')
    print(f'  説明書: 画面写真 {used} 枚を埋め込み（{out.stat().st_size / 1024:.0f} KB）')


def copy_extras() -> None:
    """解凍して最初に目に入るのが起動用の 1 つになるように整える。"""
    (DIST_DIR / LAUNCHER_NAME).write_text(
        '@echo off\r\n'
        'start "" "%~dp0runtime\\pythonw.exe" "%~dp0app\\pause.pyw"\r\n',
        encoding='utf-8')

    build_manual()

    undo = DIST_DIR / UNDO_DIR_NAME
    undo.mkdir(exist_ok=True)
    for name in UNDO_FILES:
        shutil.copy(HERE / name, undo / name)


def _force_rmtree(path: Path) -> None:
    """消せないファイルがあっても片付ける。

    Git のパックファイルは読み取り専用で作られる。ふつうに消そうとすると
    アクセス拒否になり、ignore_errors だと黙って残る（残ると次の clone が拒まれる）。
    """
    def on_error(func, name, _exc):
        os.chmod(name, 0o700)
        func(name)

    if path.exists():
        shutil.rmtree(path, onexc=on_error)


def make_repo() -> None:
    """配布物そのものを Git のリポジトリにする。

    利用者のフォルダで git pull できるようにするため、いまの HEAD を
    そのまま clone してくる。--depth 1 にするのは、履歴まで配ると
    zip が大きくなるうえ、利用者が過去へ戻る用事がないため。
    """
    ok, remote = _git('config', '--get', 'remote.origin.url')
    if not ok or not remote:
        raise SystemExit('取得先（origin）が設定されていません。'
                         '配布物から更新できないので、先に設定してください。')

    ok, head = _git('rev-parse', 'HEAD')
    ok2, dirty = _git('status', '--short')
    if dirty.strip():
        print('  ※ 手元に未コミットの変更があります。配布物には入りません:')
        for line in dirty.splitlines()[:5]:
            print(f'      {line}')

    # 前回こけたときの残骸があると clone が拒まれる。先に片付ける。
    work = DIST_DIR / '.gitwork'
    _force_rmtree(work)
    _force_rmtree(DIST_DIR / '.git')

    ok, out = _git('clone', '--depth', '1', '--branch', _current_branch(),
                   remote, str(work), cwd=str(HERE))
    if not ok:
        raise SystemExit(f'配布物をリポジトリにできませんでした: {out[:200]}')

    # clone した中身のうち .git だけを残し、ファイルは build が作ったものを使う。
    # move 先が残っていると「中へ入れる」動きになり、.git\.git という
    # 壊れた形ができる（Python の shutil.move の仕様）。上で消したので無いはず。
    if (DIST_DIR / '.git').exists():
        raise SystemExit('前回の .git を片付けられませんでした。'
                         'dist を手で消してからやり直してください。')
    shutil.move(str(work / '.git'), str(DIST_DIR / '.git'))
    _force_rmtree(work)

    _verify_repo(remote, head)


def _verify_repo(remote: str, head: str) -> None:
    """配布物が、それ自身のリポジトリとして成り立っているか。

    .git が壊れていると、git は黙って親のフォルダまで遡って別のリポジトリを
    答える。dist は開発リポジトリの中にあるので、壊れていても「動いているように」
    見えてしまう。どこを見ているかを直に確かめる。
    """
    ok, git_dir = _git('rev-parse', '--absolute-git-dir', cwd=str(DIST_DIR))
    expected = (DIST_DIR / '.git').resolve()
    if not ok or Path(git_dir).resolve() != expected:
        raise SystemExit('配布物のリポジトリが壊れています。\n'
                         f'  git が見ている先: {git_dir}\n'
                         f'  あるべき場所    : {expected}')

    ok, cloned_head = _git('rev-parse', 'HEAD', cwd=str(DIST_DIR))
    print(f'  リポジトリ: {remote}  HEAD={cloned_head[:7]}')
    if cloned_head[:7] != head[:7]:
        print(f'  ※ 手元（{head[:7]}）とちがいます。push し忘れていませんか')


def _git(*args: str, cwd: str | None = None) -> tuple[bool, str]:
    done = subprocess.run(['git', *args], cwd=cwd or str(HERE),
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    return done.returncode == 0, ((done.stdout or '') + (done.stderr or '')).strip()


def _current_branch() -> str:
    ok, name = _git('branch', '--show-current')
    return name if ok and name else 'main'


def check_manual() -> None:
    """説明書が配布物の実物と食い違っていないか。

    説明書だけ直してビルドし忘れると、古い手順のまま配ってしまう。
    存在しないファイル名が残っていたらここで止める。
    """
    text = (DIST_DIR / MANUAL_NAME).read_text(encoding='utf-8')
    stale = [word for word in ['PauseTask.exe', 'launch.bat', '_internal',
                               '自動起動を有効にする.bat', 'ウォッチドッグを有効にする.bat']
             if word in text]
    if stale:
        raise SystemExit(
            '取扱説明書に、配布物には無いものが書かれています: ' + ', '.join(stale)
            + '\n（説明書を直したあとビルドし忘れていませんか）')

    launcher = LAUNCHER_NAME.removesuffix('.bat')
    if launcher not in text:
        raise SystemExit(f'取扱説明書に起動方法（{launcher}）の案内がありません。')


def verify_layout() -> None:
    """配布物に足りないものが無いか、zip にする前に確かめる。"""
    version = f'{sys.version_info.major}{sys.version_info.minor}'
    required = [
        DIST_DIR / LAUNCHER_NAME,
        DIST_DIR / MANUAL_NAME,
        RT_DIR / 'pythonw.exe',
        RT_DIR / f'python{version}.dll',
        RT_DIR / f'python{version}._pth',
        RT_DIR / 'Lib' / 'site-packages' / 'PyQt6' / 'QtCore.pyd',
        RT_DIR / 'Lib' / 'site-packages' / 'PyQt6' / 'Qt6' / 'bin' / 'QtWebEngineProcess.exe',
        GIT_DIR / 'cmd' / 'git.exe',
        *[APP_DIR / name for name in APP_FILES],
        APP_DIR / 'config.json',
        *[DIST_DIR / UNDO_DIR_NAME / name for name in UNDO_FILES],
    ]
    missing = [str(p.relative_to(DIST_DIR)) for p in required if not p.exists()]
    if missing:
        raise SystemExit('配布物に足りないファイルがあります: ' + ', '.join(missing))

    check_manual()

    # 署名の無い exe が混ざっていないか。混ざっていると SAC に弾かれる。
    exes = sorted(p for p in DIST_DIR.rglob('*.exe'))
    print('同梱される実行ファイル:')
    for exe in exes:
        print(f'  {exe.relative_to(DIST_DIR)}')

    print('\n解凍したときに見えるもの:')
    for path in sorted(DIST_DIR.iterdir()):
        print(f'  {path.name}')

    total = sum(p.stat().st_size for p in DIST_DIR.rglob('*') if p.is_file())
    print(f'\n展開時のサイズ: {total / 1024 / 1024:.1f} MB')


def check_signatures() -> None:
    """同梱する exe が全部署名済みか確かめる。1 つでも欠けると SAC で止まる。"""
    exes = [str(p) for p in DIST_DIR.rglob('*.exe')]
    if not exes:
        return
    script = ('$ErrorActionPreference="SilentlyContinue"; '
              '$input | ForEach-Object { $s = Get-AuthenticodeSignature $_; '
              '"$($s.Status)`t$_" }')
    done = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                          input='\n'.join(exes), capture_output=True, text=True)
    bad = [line for line in done.stdout.splitlines() if line and not line.startswith('Valid')]
    print('\n実行ファイルの署名:')
    for line in done.stdout.splitlines():
        if line.strip():
            status, path = line.split('\t', 1)
            print(f'  {status:12} {Path(path).name}')
    if bad:
        raise SystemExit('署名の無い実行ファイルが含まれています。'
                         'Smart App Control に弾かれるので配布できません。')


def make_zip() -> None:
    ZIP_OUT.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_OUT, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in DIST_DIR.rglob('*'):
            if path.is_file():
                # 解凍したときのフォルダ名。DIST_DIR から取って二重管理しない。
                zf.write(path, Path(DIST_DIR.name) / path.relative_to(DIST_DIR))
    print(f'\n配布パッケージ: {ZIP_OUT}')
    print(f'サイズ: {ZIP_OUT.stat().st_size / 1024 / 1024:.1f} MB')


if __name__ == '__main__':
    print('=== Step 1: 前回の出力を片付ける ===')
    _force_rmtree(DIST_DIR)          # .git のパックは読み取り専用なので力ずくで
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    print('=== Step 2: Python と Qt と Git を同梱 ===')
    copy_runtime()
    copy_mingit()

    print('=== Step 3: 常駐本体をコピー ===')
    copy_app()
    copy_extras()

    print('\n=== Step 4: 更新できるようリポジトリにする ===')
    make_repo()

    print('\n=== Step 5: 配布物の確認 ===')
    verify_layout()
    check_signatures()

    print('\n=== Step 6: zip 化 ===')
    make_zip()
    print(f'\n完了。{ZIP_OUT.relative_to(HERE).as_posix()} を配布してください。')
