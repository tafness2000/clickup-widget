"""設定画面で変えられるもの（大きさ・位置・最初のタブ・ホットキー）を、画面なしで確かめる。

    py tests\\check_settings.py

Windows のホットキーには触らない。登録と解除を偽物に差し替えて、付け替えの順番だけを見る。
見ているのは主に 2 つ。

  ・おかしな値（手で書き換えた config.json など）が来ても、既定に戻して動くか
  ・ホットキーの付け替えで、どの瞬間にもキーが 1 つは生きているか
    （新しいほうが取れなかったら、古いほうを外していないか）
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'app'))
import hotkey             # noqa: E402  置き場所を通してから読み込む
import layout             # noqa: E402
import prefs              # noqa: E402

failed = 0


def check(label: str, got, want) -> None:
    global failed
    ok = got == want
    if not ok:
        failed += 1
    print(f'{"OK " if ok else "NG "} {label}')
    if not ok:
        print(f'      得た: {got}\n      期待: {want}')


# ── 見た目の好み ──────────────────────────────────────────────

check('大きさは段階にあるものだけ通す', prefs.set_zoom({}, '1.25'), {'zoom': 1.25})
check('段階に無い大きさは弾く', prefs.set_zoom({'zoom': 1.0}, '1.3'), {'zoom': 1.0})
check('数でないものも弾く', prefs.set_zoom({}, 'big'), {})
check('桁あふれも既定に戻す（手で壊された config.json）', prefs.zoom_of({'zoom': 10 ** 400}), prefs.DEFAULT_ZOOM)
check('壊れた大きさは既定に戻す', prefs.zoom_of({'zoom': 9}), prefs.DEFAULT_ZOOM)
check('1.0 は既定に化けない', prefs.zoom_of({'zoom': 1.0}), 1.0)
check('位置は 4 つだけ', prefs.set_corner({}, 'middle'), {})
check('壊れた位置は右下', prefs.corner_of({'corner': 'x'}), 'bottom-right')
check('最初のタブは 4 つだけ', prefs.set_wide_scope({}, 'month'), {})
check('最初のタブを変えられる', prefs.wide_scope_of(prefs.set_wide_scope({}, 'overdue')), 'overdue')
original = {'zoom': 1.0}
prefs.set_zoom(original, '1.5')
check('元の設定は書き換えない', original, {'zoom': 1.0})

# ── 窓の大きさと置き場所 ─────────────────────────────────────

AREA = (0, 0, 1000, 800)                     # 左・上・右・下
m = layout.MARGIN
check('右下', layout.corner_xy('bottom-right', 100, 50, AREA), (1000 - 100 - m, 800 - 50 - m))
check('右上', layout.corner_xy('top-right', 100, 50, AREA), (1000 - 100 - m, m))
check('左下', layout.corner_xy('bottom-left', 100, 50, AREA), (m, 800 - 50 - m))
check('左上', layout.corner_xy('top-left', 100, 50, AREA), (m, m))
check('画面がずれていても作業領域の中に置く',
      layout.corner_xy('top-left', 100, 50, (-1920, 40, 0, 1080)), (-1920 + m, 40 + m))

layout.set_zoom(1.5)
check('1.5 倍の窓', layout.win_size(), (585, 594))
layout.set_zoom(1.0)
check('等倍の窓', layout.win_size(), (layout.BASE_W, layout.BASE_H))
layout.set_corner('nowhere')
check('知らない隅は右下に戻す', layout.current_corner(), 'bottom-right')

# ── ホットキーの決まり ───────────────────────────────────────

S = hotkey.Spec
check('既定の名前', hotkey.label(hotkey.DEFAULT), 'Ctrl+Shift+Space')
check('並びは Ctrl・Alt・Shift', hotkey.label(S(frozenset({'shift', 'alt', 'ctrl'}), 0x4B)),
      'Ctrl+Alt+Shift+K')
check('F キーの名前', hotkey.label(S(frozenset({'alt'}), 0x71)), 'Alt+F2')
check('Shift だけは弾く', hotkey.make_spec(['shift'], 0x41), None)
check('修飾なしは弾く', hotkey.make_spec([], 0x41), None)
check('Enter は弾く', hotkey.make_spec(['ctrl'], 0x0D), None)
check('Win キーは弾く', hotkey.make_spec(['ctrl', 'win'], 0x41), None)
check('Alt+F4 は奪わない', hotkey.make_spec(['alt'], 0x73), None)
check('Ctrl+Alt+K は通す', hotkey.make_spec(['ctrl', 'alt'], 0x4B), S(frozenset({'ctrl', 'alt'}), 0x4B))
check('壊れた保存値は既定', hotkey.spec_of({'hotkey': {'mods': 'x', 'vk': 'y'}}), hotkey.DEFAULT)
check('vk が無限大でも既定', hotkey.spec_of({'hotkey': {'mods': ['ctrl'], 'vk': float('inf')}}), hotkey.DEFAULT)
check('保存の形を読み戻せる',
      hotkey.spec_of(hotkey.set_hotkey({}, S(frozenset({'alt'}), 0x51))), S(frozenset({'alt'}), 0x51))


# ── ホットキーの付け替え ─────────────────────────────────────

class FakeWin:
    """登録と解除を記録する。taken にあるキーは「他のアプリが使っている」。"""

    def __init__(self, taken=()):
        self.taken  = set(taken)
        self.live   = {}                      # id → Spec
        self.events = []

    def register(self, hotkey_id, spec):
        if spec in self.taken or spec in self.live.values():
            self.events.append(('ng', hotkey_id))
            return False, hotkey.ERROR_HOTKEY_ALREADY_REGISTERED
        self.live = {**self.live, hotkey_id: spec}
        self.events.append(('reg', hotkey_id))
        return True, 0

    def unregister(self, hotkey_id):
        self.live = {k: v for k, v in self.live.items() if k != hotkey_id}
        self.events.append(('unreg', hotkey_id))


ALT_K = S(frozenset({'alt'}), 0x4B)
CTRL_J = S(frozenset({'ctrl'}), 0x4A)

win = FakeWin()
man = hotkey.Manager(win.register, win.unregister)
man.start(hotkey.DEFAULT)
check('起動時に登録する', list(win.live.values()), [hotkey.DEFAULT])
ok, _ = man.rebind(ALT_K)
check('新しいほうを取ってから古いほうを外す', win.events, [('reg', 1), ('reg', 2), ('unreg', 1)])
check('付け替えたら新しい番号で受ける', (man.matches(2), man.matches(1)), (True, False))
win.events = []
check('同じキーを選び直しても何もしない', (man.rebind(ALT_K), win.events), ((True, 0), []))

win = FakeWin(taken={CTRL_J})
man = hotkey.Manager(win.register, win.unregister)
man.start(hotkey.DEFAULT)
ok, err = man.rebind(CTRL_J)
check('取られているキーは失敗を返す', (ok, err), (False, hotkey.ERROR_HOTKEY_ALREADY_REGISTERED))
check('失敗しても古いキーは生きている', (list(win.live.values()), man.current),
      ([hotkey.DEFAULT], hotkey.DEFAULT))

win = FakeWin(taken={CTRL_J})
man = hotkey.Manager(win.register, win.unregister)
ok, _ = man.start(CTRL_J)
check('保存したキーが取れなければ既定に戻す', (ok, man.current, man.fell_back),
      (False, hotkey.DEFAULT, True))

man.release()
check('終わるときは外す', win.live, {})

print(f'\n{failed} 件しくじりました' if failed else '\nすべて通りました')
sys.exit(1 if failed else 0)
