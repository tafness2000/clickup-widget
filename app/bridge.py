"""画面（HTML）から呼ばれる窓口。

HTML 側は bridge.xxx(...) の形でここだけを触る。ClickUp との通信や設定の読み書きは
すべてこの向こう側に隠す。
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import webbrowser
from datetime import datetime

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

import appconfig
import backdrop
import clickup_api
import directory
import feeds
import gitupdate
import ime
import layout
import outbox
import startup

# トークンを発行する画面。利用者に探させず、ここを直接開く。
TOKEN_PAGE_URL = 'https://app.clickup.com/settings/apps'

# 一覧の行から開いてよい先。ClickUp が返すタスク URL はこの形。
TASK_URL_PREFIX = 'https://app.clickup.com/'

# 同じ内容がこの秒数のうちに続けて届いたら、2 件目以降は送らない。
# Ctrl+Enter を連打されたとき、待っている間に呼び出しが積まれるため。
DUPLICATE_WINDOW_SEC = 5

# 黒い窓を出さずに別のプロセスを起こすための印。
CREATE_NO_WINDOW = 0x08000000

# updater が動き出したかを見届ける待ち方（0.25 秒 × 20 = 最大 5 秒）。
UPDATER_WAIT_SEC   = 0.25
UPDATER_WAIT_STEPS = 20


def _http_error(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f'ClickUp エラー: {e.code}'
    return str(e)


class Bridge(QObject):
    # 初回設定でリスト一覧が届いたことを画面へ伝える。
    # ワーカースレッドから emit しても、受け取りは GUI スレッド側になる。
    listsReady = pyqtSignal(str)
    # 広げた一覧のタスクが届いたとき。
    wideReady  = pyqtSignal(str)

    def __init__(self, window, view) -> None:
        super().__init__()
        self._window = window
        self._view   = view
        # 直前に送ったもの (name, memo, list_id, assignee_id, due, 時刻)。連打をここで弾く。
        self._last_submit = None
        self._wide = feeds.WideFeed()
        self._wide.loaded.connect(self.wideReady)

    # ── 登録 ──────────────────────────────────────────────────

    def _is_repeat(self, key: tuple) -> bool:
        """直前と同じ内容が続けて届いたか。

        submit は GUI スレッドで直列に走るので「送信中フラグ」では防げない。
        2 回目が動く頃には 1 回目が終わっているため、内容と時刻で見るしかない。
        """
        if self._last_submit is None:
            return False
        *previous, when = self._last_submit
        return tuple(previous) == key and (time.monotonic() - when) < DUPLICATE_WINDOW_SEC

    @pyqtSlot(str, str, str, str, str, result=str)
    def submit(self, name: str, memo: str, list_id: str, assignee_id: str, due: str) -> str:
        """登録の入り口。何が起きても JSON を返し切る。

        ここから例外が外へ出ると QWebChannel はコールバックを呼ばない。画面は
        送信中の表示のまま固まり、窓を閉じるまで打ち直せなくなる。
        """
        try:
            return self._submit(name, memo, list_id, assignee_id, due)
        except Exception as e:
            appconfig.log(f'警告: 登録の途中で想定外の失敗をしました ({e})')
            return json.dumps({'ok': False, 'error': _http_error(e)})

    def _submit(self, name: str, memo: str, list_id: str, assignee_id: str, due: str) -> str:
        cfg = appconfig.load_config()
        if not cfg.get('user_id'):
            user = clickup_api.fetch_user(cfg['api_token'])
            cfg  = appconfig.update_config(
                lambda latest: {**latest, 'user_id': user['id'], 'user_name': user['name']})
        target  = str(list_id or cfg['list_id'])
        payload = clickup_api.build_task_payload(cfg, name, memo, datetime.now(),
                                                 assignee_id, due)

        # メモも鍵に入れる。同じ題で中身だけ書き換えて 2 件目を入れるのは、
        # 事故ではなくよくある使い方なので弾いてはいけない。
        key = (name, memo, target, str(assignee_id or ''), str(due or ''))
        if self._is_repeat(key):
            appconfig.log('同じ内容が続けて届いたため、2 件目は送りませんでした')
            return json.dumps({'ok': True, 'queued': False, 'duplicate': True})

        try:
            clickup_api.post_task(cfg, payload, target)
        except Exception as e:
            return self._on_post_failed(e, cfg, target, payload, key)

        self._remember(cfg, target, key)
        feeds.flush_outbox_async(cfg)   # 送れたなら接続は戻っている。溜まっている分も片付ける
        return json.dumps({'ok': True, 'queued': False})

    def _remember(self, cfg: dict, target: str, key: tuple) -> None:
        """送れた（または預かった）ことを覚える。

        設定の保存に失敗しても登録そのものは済んでいるので、ここで失敗を持ち上げない。
        持ち上げると「登録できていないように見えて、もう一度押される」ことになる。
        """
        self._last_submit = (*key, time.monotonic())
        try:
            # 読み直してから直す。送っている間に★が押されていても巻き戻さない。
            appconfig.update_config(lambda latest: appconfig.remember_list(latest, target))
        except OSError as e:
            appconfig.log(f'警告: 設定を保存できませんでした ({e})')

    def _on_post_failed(self, e: Exception, cfg: dict, target: str,
                        payload: dict, key: tuple) -> str:
        if not clickup_api.is_retryable(e):
            return json.dumps({'ok': False, 'error': _http_error(e)})
        # 登録先も一緒に預ける。後日つながったとき同じリストへ送るため。
        # ここで失敗したら預かれていないので、外の except に処理させる。
        count = outbox.enqueue(appconfig.BASE, target, payload)
        appconfig.log(f'接続できないため退避しました（未送信 {count} 件）')
        self._remember(cfg, target, key)
        return json.dumps({'ok': True, 'queued': True})

    # ── 一覧 ──────────────────────────────────────────────────

    @pyqtSlot(str, str, result=str)
    def completeTask(self, task_id: str, list_id: str) -> str:
        """完了にする。リストごとにステータス名が違うので、どのリストの分かも受け取る。"""
        try:
            clickup_api.complete_task(appconfig.load_config(), task_id, list_id or None)
        except Exception as e:
            return json.dumps({'ok': False, 'error': _http_error(e)})
        return json.dumps({'ok': True})

    @pyqtSlot(str, str, result=str)
    def rescheduleTask(self, task_id: str, preset: str) -> str:
        """一覧の 1 件だけ期限を送り直す。

        既定の期限（setDefaultDue）とは別物。こちらは「そのタスクを明日へ送る」であって、
        次から登録するものの期限は動かさない。
        """
        preset = str(preset or '').strip()
        if preset not in appconfig.DUE_PRESETS:
            return json.dumps({'ok': False, 'error': 'その期限は選べません'})
        try:
            due = clickup_api.reschedule_task(appconfig.load_config(), task_id, preset)
        except Exception as e:
            return json.dumps({'ok': False, 'error': _http_error(e)})
        return json.dumps({'ok': True, 'due': due})

    @pyqtSlot(str, bool, result=str)
    def setListExcluded(self, list_id: str, excluded: bool) -> str:
        """一覧に出さないリストの出し入れ。

        これまでは config.json の excluded_lists を手で書くしかなく、リスト ID を
        ClickUp の URL から拾ってくる必要があった。控えに実在するものだけを通す。
        """
        list_id = str(list_id or '').strip()
        data  = directory.load(appconfig.BASE)
        known = {str(item.get('id')) for item in data.get('lists', [])}
        if not list_id or list_id not in known:
            return json.dumps({'ok': False, 'error': 'そのリストは見つかりませんでした'})
        try:
            # 読み直してから直す。手で書いた分や、他の経路の変更を巻き戻さない。
            updated = appconfig.update_config(
                lambda cfg: appconfig.set_list_excluded(cfg, list_id, excluded))
        except Exception as e:
            appconfig.log(f'警告: 出さないリストを保存できませんでした ({e})')
            return json.dumps({'ok': False, 'error': '保存できませんでした'})
        appconfig.log(f"リストを一覧から{'外しました' if excluded else '戻しました'}（{list_id}）")
        return json.dumps({'ok': True, 'excluded': appconfig.excluded_lists(updated)})

    # ── 広げた一覧 ────────────────────────────────────────────

    @pyqtSlot()
    def loadWide(self) -> None:
        """一覧に出すぶんを裏で取ってくる。届いたら wideReady で画面へ。

        期限での絞り込みと並べ替えは画面側でやるので、ここでは丸ごと渡す。
        タブを押すたびに取り直さずに済む。
        """
        self._wide.refresh(appconfig.load_config())

    @pyqtSlot(str)
    def setViewMode(self, mode: str) -> None:
        """入力画面と、一覧を広げた画面を行き来する。"""
        w, h = layout.view_size(mode == 'wide')
        self._window.setFixedSize(w, h)
        layout.position_window(self._window, w, h)
        # 大きさが変われば背後に来るものも変わる。前の絵のままだと引き伸ばされてずれる。
        # 撮るのは移動し終えたあと。先に撮ると前の場所の景色になる。
        backdrop.push(self._window, self._view, w, h, hide_self=True)

    # ── 更新 ──────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def startUpdate(self) -> str:
        """更新を始める。実際の作業は別のプロセス（updater.pyw）に任せる。

        自分自身のファイルを書き換えながら動くわけにいかないので、
        updater を起こしてから、こちらは窓を閉じて終わる。
        """
        try:
            return self._start_update()
        except Exception as e:
            appconfig.log(f'警告: 更新を始められませんでした ({e})')
            return json.dumps({'ok': False, 'error': str(e)})

    def _start_update(self) -> str:
        status = gitupdate.check_status(fetch=False)
        # blocked（手を入れたファイルがある）も断る。断る理由は message に入っているので、
        # 取り込める available 以外は同じ返し方でよい。
        if status['state'] != 'available':
            return json.dumps({'ok': False, 'error': status['message']})

        script = os.path.join(appconfig.BASE, 'updater.pyw')
        if not os.path.exists(script):
            return json.dumps({'ok': False, 'error': '更新の仕組みが見つかりません'})

        # 起こす前に印を書いておく。updater がここから先へ進めたかどうかで、
        # 本当に動き出したかを見分ける（起動できただけでは動いたと言えない）。
        gitupdate.set_run_state('queued', 'queued', 1, '更新の準備をしています')

        # 更新するフォルダを明に渡す。updater は別のプロセスなので、
        # こちらで差し替えた置き場所は伝わらない。
        subprocess.Popen([self._updater_python(), script, appconfig.BASE],
                         cwd=appconfig.BASE, creationflags=CREATE_NO_WINDOW)

        # 走り出したことを見届けてから終わる。見届けずに終わると、
        # updater がこけていた場合に何も起きないまま常駐だけ消える。
        if not self._wait_until_started():
            appconfig.log('警告: 更新が始まりませんでした。常駐は続けます')
            return json.dumps({'ok': False, 'error': '更新を始められませんでした'})

        appconfig.log('更新を始めました。いったん終了します')
        QTimer.singleShot(400, QApplication.quit)
        return json.dumps({'ok': True})

    @staticmethod
    def _updater_python() -> str:
        """updater を動かす Python。配布版は同梱のもの。"""
        bundled = os.path.join(os.path.dirname(appconfig.BASE), 'runtime', 'pythonw.exe')
        return bundled if os.path.exists(bundled) else sys.executable

    @staticmethod
    def _wait_until_started(limit: int = UPDATER_WAIT_STEPS) -> bool:
        for _ in range(limit):
            time.sleep(UPDATER_WAIT_SEC)
            run = gitupdate.load_status().get('lastRun') or {}
            if run.get('state') and run['state'] != 'queued':
                return True
        return False

    @pyqtSlot(str, str)
    def toggleFavorite(self, kind: str, item_id: str) -> None:
        """よく使うものへ入れる／外す。押した時点で覚える。

        画面側は押した瞬間に並べ替えている。ここが失敗しても操作は止めない
        （次に窓を出したとき、保存できた内容で並び直る）。
        """
        try:
            appconfig.update_config(lambda cfg: appconfig.toggle_favorite(cfg, kind, item_id))
        except Exception as e:
            appconfig.log(f'警告: よく使うものを保存できませんでした ({e})')

    @pyqtSlot(str, result=str)
    def setDefaultList(self, list_id: str) -> str:
        """既定の登録先を入れ替える。初回設定でしか決められなかったものを、後からでも変えられるように。"""
        list_id = str(list_id or '').strip()
        data  = directory.load(appconfig.BASE)
        known = {str(item.get('id')) for item in data.get('lists', [])}
        # 控えが空のときも断る。「候補が出ないから押されないはず」は画面側の都合であって、
        # ここで守れることではない。控えに実在するものだけを通す。
        if not list_id or list_id not in known:
            return json.dumps({'ok': False, 'error': 'そのリストは見つかりませんでした'})
        try:
            updated = appconfig.update_config(
                lambda cfg: directory.fill_names(appconfig.set_default_list(cfg, list_id), data))
        except Exception as e:
            appconfig.log(f'警告: 既定の登録先を保存できませんでした ({e})')
            return json.dumps({'ok': False, 'error': '保存できませんでした'})
        appconfig.log(f"既定の登録先を変えました（{updated.get('list_name') or list_id}）")
        return json.dumps({'ok': True, 'default_list': directory.default_list_entry(updated, data)},
                          ensure_ascii=True)

    @pyqtSlot(str, result=str)
    def setDefaultDue(self, preset: str) -> str:
        """既定の期限を入れ替える。決まった 6 つ以外は受け付けない。"""
        preset = str(preset or '').strip()
        if preset not in appconfig.DUE_PRESETS:
            return json.dumps({'ok': False, 'error': 'その期限は選べません'})
        try:
            appconfig.update_config(lambda cfg: appconfig.set_default_due(cfg, preset))
        except Exception as e:
            appconfig.log(f'警告: 既定の期限を保存できませんでした ({e})')
            return json.dumps({'ok': False, 'error': '保存できませんでした'})
        appconfig.log(f'既定の期限を変えました（{preset}）')
        return json.dumps({'ok': True, 'default_due': preset})

    @pyqtSlot(str)
    def openTask(self, url: str) -> None:
        """一覧の行から ClickUp を開く。

        ここへ来る URL は ClickUp API が返したものだけだが、既定のブラウザに
        何でも渡せる口を画面側に開けておく理由はないので、行き先を絞る。
        """
        if url.startswith(TASK_URL_PREFIX):
            webbrowser.open(url)
            return
        appconfig.log(f'警告: ClickUp のものではない URL だったので開きませんでした ({url[:60]})')

    @pyqtSlot()
    def imeAlphanumeric(self) -> None:
        """候補を開いたら半角英数へ。

        Chromium が要素に合わせて入力モードを触るのが先なので、少し置いてから当てる。
        """
        QTimer.singleShot(30, lambda: ime.to_alphanumeric(int(self._window.winId())))

    # ── 初回設定 ──────────────────────────────────────────────

    @pyqtSlot()
    def openTokenPage(self) -> None:
        """トークンを発行する画面をそのまま開く。利用者に探させない。"""
        webbrowser.open(TOKEN_PAGE_URL)

    @pyqtSlot(str, result=str)
    def checkToken(self, token: str) -> str:
        """トークンが通るか確かめ、誰として繋がったかを返す。"""
        token = token.strip()
        if not token:
            return json.dumps({'ok': False, 'error': 'トークンを貼り付けてください'})
        try:
            user = clickup_api.fetch_user(token)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return json.dumps({'ok': False, 'error': 'このトークンでは接続できませんでした。'
                                                        'コピーし直してもう一度お試しください'})
            return json.dumps({'ok': False, 'error': f'ClickUp エラー: {e.code}'})
        except Exception:
            return json.dumps({'ok': False, 'error': 'ClickUp につながりませんでした。'
                                                    'ネットワークを確認してください'})
        return json.dumps({'ok': True, 'name': user['name'], 'id': user['id']})

    @pyqtSlot(str, str)
    def loadLists(self, token: str, user_name: str) -> None:
        """リストの一覧を裏で取ってくる。30 回以上の通信になるので画面は止めない。

        つないだ人の名前も受け取る。置き場所の見当を付けて、初回設定で
        200 件の中から探させずに済ませるため。
        """
        def work() -> None:
            try:
                data = clickup_api.fetch_directory(
                    {'api_token': token.strip()},
                    on_warn=lambda m: appconfig.log(f'警告: {m}'))
            except Exception as e:
                appconfig.log(f'警告: 初回設定でリスト一覧を取得できませんでした ({e})')
                self.listsReady.emit(json.dumps({'ok': False}))
                return
            try:
                directory.save(appconfig.BASE, data)   # 本編でもそのまま使えるよう控えておく
            except OSError as e:
                appconfig.log(f'警告: リストの控えを保存できませんでした ({e})')

            lists     = data.get('lists', [])
            suggested = clickup_api.guess_personal_list(lists, user_name)
            if suggested:
                appconfig.log(f"置き場所の見当を付けました（{suggested['name']}）")
            self.listsReady.emit(json.dumps(
                {'ok': True, 'lists': lists, 'suggested': suggested}, ensure_ascii=True))

        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot(str, str, bool, result=str)
    def finishSetup(self, token: str, list_id: str, autostart: bool) -> str:
        """設定を保存し、頼まれていれば自動起動も登録する。"""
        token, list_id = token.strip(), list_id.strip()
        if not token or not list_id:
            return json.dumps({'ok': False, 'error': 'リストを選んでください'})
        try:
            user = clickup_api.fetch_user(token)
        except Exception as e:
            # 例外の文言をそのまま画面へ出さない。他の入り口と同じ整え方に揃える。
            return json.dumps({'ok': False, 'error': _http_error(e)})

        cfg = {
            'api_token': token, 'list_id': list_id,
            'user_id': user['id'], 'user_name': user['name'], 'user_email': user['email'],
            'recent_lists': [],
        }
        try:
            appconfig.save_config(directory.fill_names(cfg, directory.load(appconfig.BASE)))
        except OSError as e:
            # ここで保存できないと設定そのものが残らない。先へ進ませずに伝える。
            appconfig.log(f'警告: 初回設定を保存できませんでした ({e})')
            return json.dumps({'ok': False, 'error': f'設定を保存できませんでした（{e}）'})

        if not autostart:
            return json.dumps({'ok': True, 'autostart': False})

        started, note = startup.enable_all()
        return json.dumps({'ok': True, 'autostart': started, 'note': note})

    @pyqtSlot(result=str)
    def appFolder(self) -> str:
        """いま動いているフォルダの場所。初回設定の最初に見せる。"""
        return gitupdate.repo_root()

    @pyqtSlot()
    def openAppFolder(self) -> None:
        """そのフォルダをエクスプローラーで開く。場所を自分で探させない。"""
        try:
            os.startfile(gitupdate.repo_root())      # 開く先は自分の居場所だけ
        except OSError as e:
            appconfig.log(f'警告: フォルダを開けませんでした ({e})')

    @pyqtSlot()
    def quitApp(self) -> None:
        """常駐ごと終わらせる。フォルダを動かせるようにするための出口。

        設定を終えたあとは終わらせない。その時点で見張り役が登録済みなので、
        終わったつもりでフォルダを動かしている最中に立ち上がってしまう。
        「終わったのに動かせない」より「引っ込むだけ」の方が筋が通る。
        """
        if appconfig.is_setup_complete(appconfig.load_config()):
            appconfig.log('設定が済んでいるので、終了せずに引っ込めます')
            self.startApp()
            return
        appconfig.log('初回設定の画面から終了しました')
        QTimer.singleShot(0, QApplication.quit)

    @pyqtSlot()
    def startApp(self) -> None:
        """初回設定を終えて本編へ移る。"""
        self._view.load(QUrl.fromLocalFile(appconfig.bundled('ui.html')))
        self._window.setFixedSize(layout.WIN_W, layout.WIN_H)
        layout.position_window(self._window, layout.WIN_W, layout.WIN_H)
        self._window.hide()
        appconfig.log('初回設定が終わりました')

    @pyqtSlot()
    def closeWindow(self) -> None:
        self._window.close()
