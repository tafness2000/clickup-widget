// 候補パネル（リスト・担当者・期限）を、画面なしで動かして確かめる。
//
//     node tests\check_picker.js
//     node tests\check_picker.js <別の picker.js>    ← 直す前との対比に使う
//
// 見ているのは「どの行が光るか」。候補は数百件あって 60 件で切っているので、
// 選んであるものが切った先にあると、光る位置と選ばれるものが食い違う。
// Enter ひとつで登録先が別のリストに変わる＝気づかないまま別の場所へ入る。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const target = process.argv[2] || path.join(__dirname, '..', 'app', 'picker.js');

// 使うところだけの DOM。組み立てた行を数えられればよい。
function makeEl() {
  return {
    className: '', textContent: '', type: '', title: '', value: '', placeholder: '',
    style: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); return c; },
    append(...c) { this.children.push(...c); },
    replaceChildren(...c) { this.children = c; },
    addEventListener() {}, focus() {}, scrollIntoView() {}, remove() {},
  };
}

// 実際のワークスペースに近い数（リスト 177 件・メンバー 78 人）。
const LISTS = Array.from({ length: 177 }, (_, i) => ({
  id: String(i), name: 'list' + String(i).padStart(3, '0'), path: 'Space > Folder',
}));
const MEMBERS = Array.from({ length: 78 }, (_, i) => ({
  id: i + 1, name: 'member' + String(i).padStart(2, '0'), email: '',
}));

// picker.js が触るもののうち、ui.js と wide.js が持っているぶん。
function sandbox() {
  return {
    console,
    document: {
      createElement: makeEl,
      createDocumentFragment: makeEl,
      createTextNode: (t) => ({ textContent: t }),
    },
    DIR: { lists: LISTS, members: MEMBERS },
    FAV: { lists: [], members: [] },
    RECENT: [],
    DEFAULT_LIST: LISTS[0],
    SELF: MEMBERS[0],
    DUE_PRESETS: [{ id: 'today', name: '今日' }, { id: 'tomorrow', name: '明日' },
                  { id: 'd3', name: '3日以内' }, { id: 'week', name: '今週中' },
                  { id: 'd7', name: '1週間' }, { id: 'none', name: '期限なし' }],
    DEFAULT_DUE: 'today',
    pickedList: LISTS[0], pickedUser: MEMBERS[0], pickedDue: { id: 'today' },
    favRank: () => 1, isFav: () => false, toggleFav: () => {}, setDefault: () => {},
    renderTargets: () => {}, bridge: null,
    EXCLUDED: [], WIDE_TASKS: [], toggleExcluded: () => {},
    dueLabel: () => ({ text: '3 日後', cls: '' }),   // 6 つのどれにも当たらない期限
    closeUpdatePanel: () => {},
    pickerSearch: makeEl(), pickerList: makeEl(), pickerNote: makeEl(),
    picker: makeEl(), pickerScrim: makeEl(),
    chipList: makeEl(), chipUser: makeEl(), chipDue: makeEl(), taskInput: makeEl(),
  };
}

const source = fs.readFileSync(target, 'utf8');

// picker.js の中の const（state など）は外から取れないので、
// 調べる式も同じスクリプトの一部として一緒に走らせる。
function run(setup, probe) {
  const box = sandbox();
  Object.assign(box, setup);
  return vm.runInContext(source + '\n' + probe, vm.createContext(box), { filename: target });
}

const REPORT = `({
  rows: state.rows.length, active: state.active,
  children: pickerList.children.length,
  lit: state.active >= 0 && state.rows[state.active]
       ? state.rows[state.active].item.name : null,
  tag: state.active >= 0 && state.rows[state.active]
       ? state.rows[state.active].tag : null,
})`;

let failed = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? 'OK ' : 'NG '} ${label}`);
  if (!ok) console.log(`      得た: ${JSON.stringify(got)}\n      期待: ${JSON.stringify(want)}`);
}

// 1. ふだんの状態（既定のリストを使っている）
let r = run({}, `openPicker('list'); ${REPORT}`);
check('既定を選んでいるとき、先頭の既定が光る',
  { active: r.active, lit: r.lit, tag: r.tag, children: r.children },
  { active: 0, lit: 'list000', tag: '既定', children: 61 });   // 60 行 + 断り書き

// 2. 60 件の外を選んでいる（このバグの本題）
r = run({ pickedList: LISTS[120] }, `openPicker('list'); ${REPORT}`);
check('60 件の外を選んでいても、それが先頭で光る',
  { active: r.active, lit: r.lit, tag: r.tag, children: r.children },
  { active: 0, lit: 'list120', tag: 'いま', children: 61 });

// 3. 開き直して Enter を押しただけで登録先が変わらない
r = run({ pickedList: LISTS[120] },
  `openPicker('list'); choose(state.active); ({ after: pickedList.name })`);
check('Enter を押しても選んだものが変わらない', r, { after: 'list120' });

// 4. 末尾の断り書き（「ほかに N 件あります」）へ矢印で入り込まない
r = run({ pickedList: LISTS[120] },
  `openPicker('list'); setActive(999); ({ active: state.active })`);
check('矢印で下端を越えても行の中に留まる', r, { active: 59 });

// 5. 担当者も同じ（78 人）
r = run({ pickedUser: MEMBERS[70] }, `openPicker('user'); ${REPORT}`);
check('担当者も、60 人の外を指していれば上の方で光る',
  { active: r.active, lit: r.lit, tag: r.tag },
  { active: 1, lit: 'member70', tag: 'いま' });   // 自分の次

// 6. 出さないリストは「選んであるもの」という概念が無い
r = run({}, `openPicker('exclude'); ${REPORT}`);
check('出さないリストはどこも光らない', { active: r.active }, { active: -1 });

// 7. 期限ずらしで、いまの期限が 6 つのどれでもないとき
//    ここで先頭を光らせると、Enter を押した拍子に「今日」へ動いてしまう。
r = run({}, `openPicker('reschedule', { task: { id: 't', due: 1 }, el: null }); ${REPORT}`);
check('期限ずらしで当てはまらないときは光らせない', { active: r.active }, { active: -1 });

// 8. 絞り込んで 1 件も無いとき
r = run({}, `pickerSearch.value = 'zzzz'; openPicker('list'); pickerSearch.value = 'zzzz';
             renderPicker(); choose(state.active); ({ rows: state.rows.length,
             children: pickerList.children.length, after: pickedList.name })`);
check('見つからないときは押しても何も起きない', r,
  { rows: 0, children: 1, after: 'list000' });

console.log(failed ? `\n${failed} 件しくじりました` : '\nすべて通りました');
process.exit(failed ? 1 : 0);
