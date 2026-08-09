"""裏で通信して、届いたものを画面へ流し込む係。

ホットキーを押してから窓が出るまで通信を待たされては中断メモの意味がないので、
時間のかかる取得はすべてワーカースレッドに回す。
"""
import json
import threading

from PyQt6.QtCore import QObject, pyqtSignal

import appconfig
import clickup_api
import directory
import gitupdate
import outbox


class TaskFeed(QObject):
    """中断中タスクの取得。取れたぶんを後から流し込む。"""
    loaded = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        # 何回目の依頼か。窓を出すたびに取り直すので、続けて呼び出されると
        # 2 本目が走る。ネットワークの返りは頼んだ順とは限らないので、
        # 遅れて届いた古い一覧で新しい一覧を上書きしないための目印。
        self._generation = 0

    def refresh(self, cfg: dict) -> None:
        self._generation += 1
        threading.Thread(target=self._fetch, args=(cfg, self._generation),
                         daemon=True).start()

    def _fetch(self, cfg: dict, generation: int) -> None:
        try:
            tasks = clickup_api.fetch_open_tasks(cfg)
        except Exception as e:
            appconfig.log(f'警告: 中断中タスクを取得できませんでした ({e})')
            if generation == self._generation:
                self.loaded.emit(json.dumps({'ok': False}))
            return
        if generation != self._generation:
            return                      # もっと新しい依頼が出ている。これは捨てる
        self.loaded.emit(json.dumps({'ok': True, 'tasks': tasks}, ensure_ascii=True))


class WideFeed(QObject):
    """広げた一覧に出すタスク。リストを跨ぐぶん時間がかかるので裏で取る。"""
    loaded = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        # 何回目の依頼か。⟳ を続けて押されたとき、遅れて届いた古い結果で
        # 新しい一覧を上書きしないための目印。
        self._generation = 0

    def refresh(self, cfg: dict) -> None:
        self._generation += 1
        threading.Thread(target=self._fetch, args=(cfg, self._generation),
                         daemon=True).start()

    def _fetch(self, cfg: dict, generation: int) -> None:
        try:
            tasks, more = clickup_api.fetch_wide_tasks(cfg)
        except Exception as e:
            appconfig.log(f'警告: 広げた一覧を取得できませんでした ({e})')
            if generation == self._generation:
                self.loaded.emit(json.dumps({'ok': False}))
            return
        if generation != self._generation:
            return                      # もっと新しい依頼が出ている。これは捨てる
        # 打ち切ったならログにも残す。画面の断り書きは見た人しか気づけないが、
        # ここに続けて出ていれば「上限が足りていない」と後から分かる。
        appconfig.log(f'広げた一覧: 中断中 {len(tasks)} 件'
                      + ('（見に行ける分を使い切りました。まだ先にあるかもしれません）'
                         if more else ''))
        self.loaded.emit(json.dumps({'ok': True, 'tasks': tasks, 'more': more},
                                    ensure_ascii=True))


class DirectoryFeed(QObject):
    """リストとメンバーの一覧を裏で取ってきて、手元の控えを更新する。

    30 回以上の通信になるので、窓を出す流れとは切り離す。取れたら控えに書いて
    画面へ流し込む。取れなくても、前回の控えがあればそれで選べる。
    """
    loaded = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._generation = 0        # TaskFeed と同じ理由。古い結果で新しいものを潰さない

    def refresh(self, cfg: dict) -> None:
        self._generation += 1
        threading.Thread(target=self._fetch, args=(cfg, self._generation),
                         daemon=True).start()

    def _fetch(self, cfg: dict, generation: int) -> None:
        try:
            data = clickup_api.fetch_directory(cfg, on_warn=lambda m: appconfig.log(f'警告: {m}'))
        except Exception as e:
            appconfig.log(f'警告: リスト・メンバーの一覧を取得できませんでした ({e})')
            return
        if generation != self._generation:
            return                  # もっと新しい依頼が出ている。控えも書き替えない
        try:
            directory.save(appconfig.BASE, data)
        except (OSError, ValueError) as e:
            appconfig.log(f'警告: リスト・メンバーの控えを保存できませんでした ({e})')

        # 読み直してから直す。取得している間に★が押されていても巻き戻さない。
        # 保存できなくても候補は画面へ渡す（名前が埋まらないだけで、選ぶのに支障はない）。
        try:
            filled = appconfig.update_config(lambda latest: directory.fill_names(latest, data))
        except (OSError, ValueError) as e:
            appconfig.log(f'警告: 設定に名前を補えませんでした ({e})')
            filled = appconfig.load_config()

        appconfig.log(f"リスト {len(data.get('lists', []))} 件 / "
                      f"メンバー {len(data.get('members', []))} 人を取得しました")
        self.loaded.emit(json.dumps(directory.build_payload(filled, data), ensure_ascii=True))


class UpdateFeed(QObject):
    """新しい版が出ていないかを見る。起動したときに 1 回だけ。

    git fetch はネットワークを待つので、窓を出す流れとは切り離す。
    取りに行けなくても静かに諦める（更新は「できたら嬉しい」もので、
    中断メモを書くのに要るものではない）。
    """
    loaded = pyqtSignal(str)

    def refresh(self) -> None:
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self) -> None:
        try:
            status = gitupdate.check_status()
            # 触るのは「新しい版があるか」だけ。updater が書いている lastRun は
            # こちらの都合で消さない（進み具合を見失うと、更新が始まったかが分からなくなる）。
            gitupdate.merge_status(status)
            if status['state'] == 'available':
                status['changes'] = gitupdate.changes_summary()
                appconfig.log(f"更新があります（{status['behind']} 件 / "
                              f"{status['localSha'][:7]} → {status['remoteSha'][:7]}）")
            elif status['state'] not in ('current', 'not_configured'):
                appconfig.log(f"更新の確認: {status['state']} — {status['message']}")
        except Exception as e:
            appconfig.log(f'警告: 更新を確認できませんでした ({e})')
            self.loaded.emit(json.dumps({'state': 'checking_failed'}))
            return
        self.loaded.emit(json.dumps(status, ensure_ascii=True))


# 再送は 3 か所（起動直後・登録の直後・5 分ごと）から呼ばれる。同じ outbox.json を
# 2 つのスレッドが同時に読み書きすると、送った分が復活したり消えたりする。
_flush_lock = threading.Lock()


def _flush_worker(cfg: dict) -> None:
    if not _flush_lock.acquire(blocking=False):
        return                      # 前の再送がまだ走っている。任せてよい
    try:
        outbox.flush_quiet(cfg, appconfig.BASE)
    finally:
        _flush_lock.release()


def flush_outbox_async(cfg: dict) -> None:
    """未送信分の再送をワーカースレッドで始める。

    HTTP のタイムアウトは 10 秒ある。GUI スレッドで走らせると、その間ホットキーを
    押しても窓が出ない。押してから出るまでの体感に直結するので必ずここを通す。
    """
    threading.Thread(target=_flush_worker, args=(cfg,), daemon=True).start()
