"""取扱説明書に載せる画面を撮る。

本物の ui.html / setup.html を動かして撮るので、説明書と実物がずれない。
ClickUp にはつながない。出てくる名前はすべて架空のもの（説明書は配るため）。
"""
import json
import os
import sys

# 置き場所は自分の位置から辿る。フォルダ名を変えても壊れないようにするため。
#   manual/take_shots.py → リポジトリ直下 → app/
_MANUAL = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(os.path.dirname(_MANUAL), 'app')

# 撮ったものは shots/ に置く。build.py がここから拾って説明書へ埋め込む。
OUT_DIR = os.path.join(_MANUAL, 'shots')
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, APP_DIR)

os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS',
                      '--disable-gpu --disable-gpu-compositing --use-angle=swiftshader')
os.environ.setdefault('QT_OPENGL', 'software')

from PyQt6.QtCore import QUrl, QTimer, QObject, pyqtSlot, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

import layout

# ── 説明書に載せる架空のデータ ────────────────────────────────

LISTS = [
    {'id': 'p1', 'name': 'Yamada',            'path': 'Personal Work space'},
    {'id': 'p2', 'name': 'Suzuki',            'path': 'Personal Work space'},
    {'id': 'p3', 'name': 'Tanaka',            'path': 'Personal Work space'},
    {'id': 'h1', 'name': 'Grand Hotel Tokyo', 'path': 'Projects > HOTEL PROJECTS'},
    {'id': 'h2', 'name': 'Grand Hotel Kyoto', 'path': 'Projects > HOTEL PROJECTS'},
    {'id': 'h3', 'name': 'Grand Hotel Kyoto', 'path': 'Projects > Hotel Archive'},
    {'id': 'h4', 'name': 'Seaside Resort Okinawa', 'path': 'Projects > HOTEL PROJECTS'},
    {'id': 's1', 'name': 'Sales Activity',    'path': 'Sales'},
    {'id': 's2', 'name': 'Product Backlog',   'path': 'Development'},
]

MEMBERS = [
    {'id': 1, 'name': 'Yamada Taro',  'email': 'yamada@example.co.jp'},
    {'id': 2, 'name': 'Suzuki Hanako', 'email': 'suzuki@example.co.jp'},
    {'id': 3, 'name': 'Tanaka Ichiro', 'email': 'tanaka@example.co.jp'},
    {'id': 4, 'name': '佐藤　健',      'email': 'sato@example.co.jp'},
    {'id': 5, 'name': 'Chris Baker',   'email': 'chris@example.com'},
]

DIRECTORY = {
    'lists': LISTS, 'members': MEMBERS,
    'default_list': LISTS[0],
    'self': {'id': 1, 'name': 'Yamada Taro', 'email': 'yamada@example.co.jp'},
    'recent': ['h1', 's1'],
    'favorites': {'lists': ['h2'], 'members': ['2']},
    'default_due': 'today',
}

FEED = [
    {'id': 't1', 'name': '見積書のチェック待ち', 'url': '', 'list_id': 'p1',
     'list_name': 'Yamada', 'memo': '見積書_日本橋案件.xlsx - Excel'},
    {'id': 't2', 'name': '田中さんの返事待ち', 'url': '', 'list_id': 's1',
     'list_name': 'Sales Activity', 'memo': ''},
    {'id': 't3', 'name': '図面の差し替え分を確認', 'url': '', 'list_id': 'p1',
     'list_name': 'Yamada', 'memo': '第3版_20260804.pdf'},
]


def _due(days):
    """その日の 23:59:59。秒まで引かないと日付が 1 日ずれる。"""
    import time
    now  = time.localtime()
    base = time.time() - now.tm_hour * 3600 - now.tm_min * 60 - now.tm_sec
    return str(int((base + days * 86400 + 86399) * 1000))


WIDE = [
    {'id': 'w1', 'name': '見積書のチェック待ち', 'url': '', 'list_id': 'p1',
     'list_name': 'Yamada', 'memo': '見積書_日本橋案件.xlsx - Excel', 'status': 'to do', 'due': _due(0)},
    {'id': 'w2', 'name': '田中さんの返事待ち', 'url': '', 'list_id': 's1',
     'list_name': 'Sales Activity', 'memo': '', 'status': 'to do', 'due': _due(0)},
    {'id': 'w3', 'name': '図面の差し替え分を確認', 'url': '', 'list_id': 'p1',
     'list_name': 'Yamada', 'memo': '第3版_20260804.pdf', 'status': 'to do', 'due': _due(-1)},
    {'id': 'w4', 'name': '発注書の押印をもらう', 'url': '', 'list_id': 'h1',
     'list_name': 'Grand Hotel Tokyo', 'memo': '', 'status': 'to do', 'due': _due(-4)},
    {'id': 'w5', 'name': '現地調査の日程を決める', 'url': '', 'list_id': 'h2',
     'list_name': 'Grand Hotel Kyoto', 'memo': '先方の都合待ち', 'status': 'to do', 'due': _due(-8)},
    {'id': 'w6', 'name': '仕様書のレビュー', 'url': '', 'list_id': 's2',
     'list_name': 'Product Backlog', 'memo': '', 'status': 'to do', 'due': _due(2)},
    {'id': 'w7', 'name': '見積の再提出', 'url': '', 'list_id': 'h4',
     'list_name': 'Seaside Resort Okinawa', 'memo': '', 'status': 'to do', 'due': _due(5)},
]

SETUP_LISTS = {'ok': True, 'lists': LISTS, 'suggested': LISTS[0]}


class Stub(QObject):
    # 通信を伴うものは本物と同じで戻り値を持たない（返事はシグナルで届く形なので、
    # 写真を撮るぶんには受け取る必要がない）。
    @pyqtSlot(str, str, str, str, str)
    def submit(self, *a): pass

    @pyqtSlot(str, str)
    def toggleFavorite(self, *a): pass

    @pyqtSlot(str, str)
    def completeTask(self, *a): pass

    @pyqtSlot(str, str)
    def rescheduleTask(self, *a): pass

    @pyqtSlot(str, bool, result=str)
    def setListExcluded(self, *a): return json.dumps({'ok': True, 'excluded': []})

    @pyqtSlot(str)
    def openTask(self, url): pass

    @pyqtSlot()
    def imeAlphanumeric(self): pass

    @pyqtSlot()
    def closeWindow(self): pass

    @pyqtSlot()
    def loadWide(self): pass

    @pyqtSlot(str)
    def setViewMode(self, mode): pass

    @pyqtSlot()
    def openTokenPage(self): pass

    @pyqtSlot(str, result=str)
    def checkToken(self, token):
        return json.dumps({'ok': True, 'name': 'Yamada Taro', 'id': 1})

    @pyqtSlot(str, str)
    def loadLists(self, token, name): pass

    @pyqtSlot(str, str, bool, result=str)
    def finishSetup(self, *a): return json.dumps({'ok': True, 'autostart': True})

    @pyqtSlot()
    def startApp(self): pass

    @pyqtSlot(result=str)
    def appFolder(self): return r'C:\Tools\ClickUpWidget'   # 説明書に載せる架空のパス


app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

win = QMainWindow()
win.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
view = QWebEngineView()
view.page().setBackgroundColor(QColor('#141416'))
win.setCentralWidget(view)

stub    = Stub()
channel = QWebChannel()
channel.registerObject('bridge', stub)
view.page().setWebChannel(channel)

shots = []


def js(code, then=None):
    view.page().runJavaScript(code, (lambda v: then(v)) if then else (lambda v: None))


def grab(name, then, wait=700):
    def do():
        win.grab().save(os.path.join(OUT_DIR, f'{name}.png'))
        shots.append(name)
        print(f'  撮りました: {name}.png', flush=True)
        QTimer.singleShot(150, then)
    QTimer.singleShot(wait, do)


# ── 入力画面まわり ────────────────────────────────────────────

def start_main(_ok=None):
    view.loadFinished.disconnect(start_main)
    win.setFixedSize(layout.WIN_W, layout.WIN_H)
    win.show()
    js(f'setDirectory({json.dumps(DIRECTORY, ensure_ascii=True)});'
       'resetForm("見積書_日本橋案件.xlsx - Excel");'
       'taskInput.value = "";'
       f'setTasks({json.dumps({"ok": True, "tasks": FEED}, ensure_ascii=True)});')
    grab('main', shot_typed)


def shot_typed():
    js('taskInput.value = "見積書のチェック待ち";'
       'memoInput.value = "先方の回答が来たら差し替える";')
    grab('main-typed', shot_pick_list)


def shot_pick_list():
    js('resetForm("見積書_日本橋案件.xlsx - Excel"); openPicker("list");'
       'pickerList.children[0].classList.add("active");')
    grab('pick-list', shot_pick_list_search)


def shot_pick_list_search():
    js('pickerSearch.value = "grand kyoto"; renderPicker();')
    grab('pick-list-search', shot_pick_user)


def shot_pick_user():
    js('closePicker(false); openPicker("user");')
    grab('pick-user', shot_pick_due)


def shot_pick_due():
    js('closePicker(false); openPicker("due");')
    grab('pick-due', shot_chips_changed)


def shot_chips_changed():
    js('closePicker(false);'
       'pickedList = DIR.lists[3]; pickedUser = DIR.members[1];'
       'pickedDue = DUE_PRESETS[3]; renderTargets();')
    grab('chips-changed', shot_update_chip)


# ── 新しい版のお知らせ ────────────────────────────────────────

UPDATE = {
    'state': 'available', 'behind': 3,
    'localSha': 'a1b2c3d4e5f6', 'remoteSha': '9f8e7d6c5b4a',
    'changes': [
        '9f8e7d6 fix: 一覧の並び順がときどき入れ替わるのを直す',
        '3c1a55e feat: 期限に「来週」を足す',
        '7b20d91 docs: 説明書に更新のしかたを書く',
    ],
}


def shot_update_chip():
    js('resetForm("");'
       f'setUpdate({json.dumps(UPDATE, ensure_ascii=True)});')
    grab('update-chip', shot_update_panel)


def shot_update_panel():
    js('openUpdatePanel();')
    grab('update-panel', shot_wide)


# ── 広げた一覧 ────────────────────────────────────────────────

def shot_wide():
    js('closeUpdatePanel(); setUpdate(null);')     # 一覧の写真に混ざらないよう戻す
    w, h = layout.view_size(True)
    win.setFixedSize(w, h)
    js('resetForm(""); document.body.classList.add("wide");'
       'WIDE.open = true; WIDE.scope = "today"; WIDE.busy = false;'
       f'setWideTasks({json.dumps({"ok": True, "tasks": WIDE}, ensure_ascii=True)});')
    grab('wide-today', shot_wide_all)


def shot_wide_all():
    js('WIDE.scope = "all";'
       '[...wideTabs.children].forEach(el => el.classList.toggle("on", el.dataset.scope === "all"));'
       'renderWide();')
    grab('wide-all', shot_wide_overdue)


def shot_wide_overdue():
    js('WIDE.scope = "overdue";'
       '[...wideTabs.children].forEach(el => el.classList.toggle("on", el.dataset.scope === "overdue"));'
       'renderWide();')
    grab('wide-overdue', shot_wide_reschedule)


def shot_wide_reschedule():
    """行の期限を押して、6 つから選び直すところ。

    タブは「期限切れ」のまま撮る。切り替えた直後は、暗幕が乗ったときに前のタブが
    中途半端に目立って、どれが選ばれているのか読み取れない写真になる。
    期限切れのものを送り直す場面は、説明の流れにもそのまま合う。
    """
    js('openPicker("reschedule", {task: wideRows()[0],'
       ' el: document.querySelectorAll(".wide-due")[0]});')
    grab('wide-reschedule', shot_wide_search)


def shot_wide_search():
    """絞り込んだところ。タブは「すべて」にしておく（絞り込みはタブと別に効く）。"""
    js('closePicker(false);'
       'WIDE.scope = "all";'
       '[...wideTabs.children].forEach(el => el.classList.toggle("on", el.dataset.scope === "all"));'
       'wideSearch.value = "見積"; WIDE.query = "見積"; wideSearch.classList.add("on");'
       'renderWide();')
    grab('wide-search', shot_wide_exclude)


def shot_wide_exclude():
    """出さないリストのパネル。1 つ外してある状態にして、戻し方も見えるようにする。"""
    # 後ろの一覧からもそのリストのぶんを落とす。外してあるのに一覧に残っていると、
    # 写真の中で辻褄が合わなくなる。
    js('clearWideSearch();'
       'EXCLUDED = DIR.lists.length ? [String(DIR.lists[DIR.lists.length - 1].id)] : [];'
       'WIDE_TASKS = WIDE_TASKS.filter(t => !EXCLUDED.includes(String(t.list_id)));'
       'renderWide();'
       'openPicker("exclude");')
    grab('wide-exclude', close_and_load_setup)


def close_and_load_setup():
    """パネルを閉じてから初回設定へ移る。

    開いたまま移ると、次の画面の描画が間に合わず、前の画面が写ったままの写真になる
    （QWebEngineView は新しいページを描き終えるまで前の絵を持ち続ける）。
    """
    js('closePicker(false);')
    QTimer.singleShot(400, load_setup)


# ── 初回設定 ──────────────────────────────────────────────────

def load_setup():
    win.setFixedSize(layout.SETUP_W, layout.SETUP_H)
    view.loadFinished.connect(start_setup)
    view.load(QUrl.fromLocalFile(os.path.join(APP_DIR, 'setup.html')))


def start_setup(_ok):
    view.loadFinished.disconnect(start_setup)
    # 置き場所は Bridge が入れる。ここは繋いでいないので、架空のパスを流し込む。
    js(r'document.getElementById("pathBox").textContent = "C:\\Tools\\ClickUpWidget";')
    # 読み込み終わり（loadFinished）は描き終わりではない。GPU を使わない設定だと
    # 描画が遅れて、前の画面が写ったままの写真になる。ここだけ長めに待つ。
    grab('setup-0', shot_setup1, wait=1500)


def shot_setup1():
    js('document.getElementById("next0").click();')
    grab('setup-1', shot_setup2)


def shot_setup2():
    js('document.getElementById("tokenInput").value = "pk_00000000_XXXXXXXXXXXXXXXXXXXX";'
       'document.getElementById("next1").click();')
    QTimer.singleShot(600, lambda: js(
        f'setupLists({json.dumps(SETUP_LISTS, ensure_ascii=True)});',
        lambda v: grab('setup-2', shot_setup3)))


def shot_setup3():
    js('document.getElementById("next2").click();')
    grab('setup-3', shot_setup4)


def shot_setup4():
    js('goto(4);')
    grab('setup-4', done)


def done():
    print(f'\n{len(shots)} 枚を {OUT_DIR} に保存しました。', flush=True)
    app.exit(0)


view.loadFinished.connect(start_main)
view.load(QUrl.fromLocalFile(os.path.join(APP_DIR, 'ui.html')))
sys.exit(app.exec())
