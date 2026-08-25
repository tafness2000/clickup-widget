// 担当者を何人か選ぶところを、画面なしで動かして確かめる。
//
//     node tests\check_multiuser.js
//
// ui.js と picker.js を続けて読み込む（選んである状態は ui.js、探し方と見せ方は
// picker.js にあり、両方揃わないと動かない）。見ているのは主に 3 つ。
//
//   ・選んでもパネルが閉じないこと。ひとりごとに閉じては何人も選べない
//   ・最後のひとりが外せないこと。担当のいないタスクは、作った当人しか
//     在り処を知らないまま ClickUp のどこかに残る
//   ・選んである人が、候補の切り捨て（60 件）より前に全員出ること。
//     ここを落とすと、61 人目より後ろに選んだ人が見えず、外せなくなる
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const uiPath     = path.join(__dirname, '..', 'app', 'ui.js');
const pickerPath = path.join(__dirname, '..', 'app', 'picker.js');

// 使うところだけの DOM。クラスの出し入れは本当に覚えておく
//（チップの知らせが出ているかを見るため）。
function makeEl() {
  const classes = new Set();
  return {
    className: '', textContent: '', type: '', title: '', value: '', placeholder: '',
    disabled: false, style: {}, children: [],
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c, on) => (on === undefined
        ? (classes.has(c) ? classes.delete(c) : classes.add(c))
        : (on ? classes.add(c) : classes.delete(c))),
    },
    appendChild(c) { this.children.push(c); return c; },
    append(...c) { this.children.push(...c); },
    replaceChildren(...c) { this.children = c; },
    addEventListener() {}, focus() {}, scrollIntoView() {}, remove() {},
  };
}

// 実際のワークスペースに近い人数（78 人）。切り捨ては 60 件なので外が出る。
const MEMBERS = Array.from({ length: 78 }, (_, i) => ({
  id: i + 1, name: 'member' + String(i).padStart(2, '0'), email: '',
}));

const DIRECTORY = {
  lists: [{ id: '1', name: 'list1', path: '' }],
  members: MEMBERS,
  default_list: { id: '1', name: 'list1', path: '' },
  self: MEMBERS[0],
  recent: [],
  favorites: { lists: [], members: [] },
  default_due: 'today',
  excluded: [],
};

function sandbox() {
  const els = {};
  const get = (k) => (els[k] || (els[k] = makeEl()));
  const keydown = [];
  const box = {
    console, setTimeout, clearTimeout, JSON,
    document: {
      getElementById: get, querySelector: get,
      addEventListener(type, fn) { if (type === 'keydown') keydown.push(fn); },
      createElement: makeEl, createDocumentFragment: makeEl,
      createTextNode: (t) => ({ textContent: t }),
    },
    qt: { webChannelTransport: {} },
    QWebChannel: function (t, cb) {
      cb({ objects: { bridge: {
        closeWindow() {}, imeAlphanumeric() {}, toggleFavorite() {}, submit() {},
      } } });
    },
    // wide.js / update.js が持っているぶん
    WIDE: { open: false, query: '' },
    WIDE_TASKS: [],
    toggleExcluded: () => {},
    dueLabel: () => ({ text: '3 日後', cls: '' }),
    applyReschedule: () => {},
    closeWide: () => {}, openWide: () => {}, clearWideSearch: () => {},
    renderWide: () => {}, loadWide: () => {}, closeUpdatePanel: () => {},
  };
  // キーは document 全体で拾っているので、こちらから叩いて確かめる。
  box.__press = (e) => {
    const ev = { preventDefault() {}, stopPropagation() {}, ...e };
    keydown.forEach((fn) => fn(ev));
  };
  return box;
}

const source = fs.readFileSync(uiPath, 'utf8') + '\n' + fs.readFileSync(pickerPath, 'utf8');

// 候補は Python から流し込まれるので、その経路をそのまま通す。
const setup = '\nsetDirectory(' + JSON.stringify(DIRECTORY) + ');\n';

function run(probe) {
  return vm.runInContext(source + setup + probe, vm.createContext(sandbox()),
                         { filename: 'check_multiuser' });
}

let failed = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log((ok ? 'OK  ' : 'NG  ') + label);
  if (!ok) {
    console.log('      得た: ' + JSON.stringify(got));
    console.log('      期待: ' + JSON.stringify(want));
  }
}

const NAMES = 'pickedUsers.map(u => u.name)';

// 1. 選んでもパネルは閉じない
let r = run(`openPicker('user'); choose(1);
             ({ kind: state.kind, names: ${NAMES} })`);
check('選んでもパネルは閉じない', r, { kind: 'user', names: ['member00', 'member01'] });

// 2. 続けて何人でも
r = run(`openPicker('user'); choose(1); choose(2); ({ names: ${NAMES} })`);
check('続けて何人でも選べる', r.names, ['member00', 'member01', 'member02']);

// 3. もう一度押すと外れる
r = run(`openPicker('user'); choose(1); choose(1); ({ names: ${NAMES} })`);
check('同じ人をもう一度押すと外れる', r.names, ['member00']);

// 4. 最後のひとりは外せない（担当のいないタスクを作らせない）
r = run(`openPicker('user'); choose(0);
         ({ names: ${NAMES}, note: !!pickerNote.textContent })`);
check('最後のひとりは外せない', r, { names: ['member00'], note: true });

// 5. 元の配列は書き換えない（握っている側の中身が黙って変わらない）
r = run(`openPicker('user'); const before = pickedUsers; choose(1);
         ({ was: before.length, now: pickedUsers.length, same: before === pickedUsers })`);
check('選んでも元の配列は書き換えない', r, { was: 1, now: 2, same: false });

// 6. 絞り込んで Enter → 入れて、次を探せるよう欄が空になる
r = run(`openPicker('user'); pickerSearch.value = 'member01'; renderPicker();
         __press({ key: 'Enter' });
         ({ kind: state.kind, search: pickerSearch.value, names: ${NAMES} })`);
check('絞り込んで Enter を押すと、入れて欄が空になる', r,
  { kind: 'user', search: '', names: ['member00', 'member01'] });

// 7. 絞り込みが空のときも、Enter は入り切り。ひとりごとに閉じては用を成さない
r = run(`openPicker('user'); setActive(1); __press({ key: 'Enter' });
         ({ kind: state.kind, names: ${NAMES} })`);
check('絞り込みが空でも Enter は入り切りで、閉じない', r,
  { kind: 'user', names: ['member00', 'member01'] });

// 7b. 閉じるのは Esc と Tab と、外を押したとき
r = run(`openPicker('user'); choose(1); __press({ key: 'Escape' });
         ({ kind: state.kind, count: pickedUsers.length })`);
check('Esc で決まって閉じる', r, { kind: null, count: 2 });

r = run(`openPicker('user'); choose(1); __press({ key: 'Tab' });
         ({ kind: state.kind, count: pickedUsers.length })`);
check('Tab でも決まって閉じる', r, { kind: null, count: 2 });

// 8. 矢印で合わせて Space
r = run(`openPicker('user'); setActive(2); __press({ key: ' ' }); ({ names: ${NAMES} })`);
check('絞り込みが空なら Space で入り切りできる', r.names, ['member00', 'member02']);

// 9. 打ちかけているときの Space は、名前の中の空白として通す
//    （「田中 太郎」のような 2 語の絞り込みを殺さないため）
r = run(`openPicker('user'); pickerSearch.value = 'member'; renderPicker();
         __press({ key: ' ' }); ({ count: pickedUsers.length })`);
check('絞り込みに打ってあるとき、Space は入り切りに使わない', r.count, 1);

// 10. 変換確定の Enter を決定と取り違えない
r = run(`openPicker('user'); pickerSearch.value = 'member01'; renderPicker();
         __press({ key: 'Enter', isComposing: true });
         ({ kind: state.kind, search: pickerSearch.value, count: pickedUsers.length })`);
check('変換中の Enter は決定と取り違えない', r,
  { kind: 'user', search: 'member01', count: 1 });

// 11. 選んである人は、切り捨て（60 件）より前に全員出る
r = run(`pickedUsers = [SELF, DIR.members[70], DIR.members[75]];
         openPicker('user');
         ({ head: state.rows.slice(0, 3).map(x => x.item.name), active: state.active })`);
check('選んである人は、切り捨てより前に全員出る', r,
  { head: ['member00', 'member70', 'member75'], active: 0 });

// 12. 60 人の外に居る人も、そこから外せる
r = run(`pickedUsers = [SELF, DIR.members[70]];
         openPicker('user'); choose(1); ({ names: ${NAMES} })`);
check('60 人の外に居る人も外せる', r.names, ['member00']);

// 13. 当たるものが無いときの Enter は、打った文字も消さない
r = run(`openPicker('user'); pickerSearch.value = 'zzzz'; renderPicker();
         __press({ key: 'Enter' });
         ({ kind: state.kind, search: pickerSearch.value, count: pickedUsers.length })`);
check('当たるものが無ければ、Enter で欄を消さない', r,
  { kind: 'user', search: 'zzzz', count: 1 });

// ── チップの見え方 ────────────────────────────────────────────

r = run(`pickedUsers = [SELF, DIR.members[1], DIR.members[2]]; renderTargets();
         ({ label: chipUserLabel.textContent, away: chipUser.classList.contains('away') })`);
check('チップは先頭ひとりと人数に畳む', r, { label: '自分 +2', away: false });

r = run(`pickedUsers = [DIR.members[1]]; renderTargets();
         ({ label: chipUserLabel.textContent, away: chipUser.classList.contains('away'),
            title: chipUser.title.includes('ここには出ません') })`);
check('自分が担当から外れていると、チップで知らせる', r,
  { label: 'member01', away: true, title: true });

r = run(`renderTargets(); ({ away: chipUser.classList.contains('away') })`);
check('自分が入っていれば知らせない', r, { away: false });

// 「既定と違う」と「自分が外れている」は別の話なので、両方立つ。
// CSS も背景（.chip.changed）と枠（.chip-user.away）で描き分けている。
r = run(`pickedUsers = [DIR.members[1], DIR.members[3]]; renderTargets();
         ({ changed: chipUser.classList.contains('changed'),
            away: chipUser.classList.contains('away') })`);
check('既定と違う印と、自分が外れている印は両方立つ', r, { changed: true, away: true });

// ── 送るときの形 ──────────────────────────────────────────────

// 押した順のまま送る。重なりと並びを均すのは Python 側（parse_assignees）。
r = run(`let sent = null;
         bridge = { submit: (...args) => { sent = args; } };
         pickedUsers = [DIR.members[2], SELF];
         taskInput.value = 'やりかけ';
         doSubmit();
         ({ assignees: sent[3] })`);
check('担当者はカンマで繋いで送る', r.assignees, '3,1');

// ── 登録し終わったときの文面 ──────────────────────────────────
//
// 折り返し任せにすると「担当の / ぶんだけを」のように語の途中で切れる。
// 文の切れ目で自分で改めているか（CSS 側は white-space: pre-line）。

r = run(`pickedUsers = [DIR.members[1], DIR.members[2]];
         onSubmitDone({ ok: true, away: true }); cancelLater();
         ({ lines: successText.textContent.split('\\n') })`);
check('自分が外れているときは、文の切れ目で改める', r.lines.length, 2);

r = run(`onSubmitDone({ ok: true }); cancelLater();
         ({ text: successText.textContent })`);
check('ふつうに登録したときは一言だけ', r, { text: '登録しました' });

r = run(`onSubmitDone({ ok: true, queued: true }); cancelLater();
         ({ lines: successText.textContent.split('\\n') })`);
check('預かったときも文の切れ目で改める', r.lines.length, 2);

console.log(failed ? ('\n' + failed + ' 件しくじりました') : '\nすべて通りました');
process.exit(failed ? 1 : 0);
