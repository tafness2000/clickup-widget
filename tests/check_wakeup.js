// 出しっぱなしの窓を、もう一度呼んだときの振る舞いを画面なしで確かめる。
//
//     node tests\check_wakeup.js
//     node tests\check_wakeup.js <別の ui.js>    ← 直す前との対比に使う
//
// 登録すると成功表示に切り替わり、少し置いてから窓が引っ込む。その待ち時間に
// ホットキーを押されると、pause.pyw は resetForm を通らない（出しっぱなしのときは
// 中身を入れ替えるだけ）。送信中の札を下ろすのは resetForm だけなので、
// 打つ画面へ戻す手当てが無いと、Ctrl+Enter も効かないまま固まって見える。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const target = process.argv[2] || path.join(__dirname, '..', 'app', 'ui.js');

// 使うところだけの DOM。表示の出し入れと値の読み書きができればよい。
function makeEl() {
  return {
    className: '', textContent: '', value: '', title: '', disabled: false,
    style: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); return c; },
    append(...c) { this.children.push(...c); },
    replaceChildren(...c) { this.children = c; },
    addEventListener() {}, focus() {}, scrollIntoView() {}, remove() {},
  };
}

function sandbox() {
  const els = {};
  const get = (k) => (els[k] || (els[k] = makeEl()));
  return {
    console, setTimeout, clearTimeout,
    document: {
      getElementById: get, querySelector: get, addEventListener() {},
      createElement: makeEl, createDocumentFragment: makeEl,
      createTextNode: (t) => ({ textContent: t }),
    },
    qt: { webChannelTransport: {} },
    QWebChannel: function (t, cb) { cb({ objects: { bridge: { closeWindow() {} } } }); },
    // picker.js / wide.js / update.js が持っているもの
    closePicker() {}, isOpen: () => false, state: { kind: null },
    renderPicker() {}, closeWide() {}, WIDE: { open: false, query: '' },
    closeUpdatePanel() {},
  };
}

const source = fs.readFileSync(target, 'utf8');

function run(probe) {
  return vm.runInContext(source + '\n' + probe, vm.createContext(sandbox()), { filename: target });
}

let failed = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? 'OK ' : 'NG '} ${label}`);
  if (!ok) console.log(`      得た: ${JSON.stringify(got)}\n      期待: ${JSON.stringify(want)}`);
}

(async () => {
  // 1. 「登録しました」を出したまま呼び戻す → 打つ画面へ戻り、送信中の札も下りる
  let r = run(`
    successArea.style.display = 'flex';
    formArea.style.display = 'none';
    submitting = true;
    submitBtn.disabled = true;
    (typeof wakeUp === 'function' ? wakeUp('メモ帳') : refreshContext('メモ帳'));
    ({ success: successArea.style.display, form: formArea.style.display,
       submitting: submitting, disabled: submitBtn.disabled })
  `);
  check('成功表示中に呼び戻すと、打つ画面へ戻る', r,
    { success: 'none', form: '', submitting: false, disabled: false });

  // 2. 閉じるつもりで仕掛けたタイマーが、呼び戻しで取り消される
  r = run(`
    let closed = 0;
    bridge = { closeWindow: () => closed++ };
    successArea.style.display = 'flex';
    formArea.style.display = 'none';
    if (typeof later === 'function') later(40, () => bridge.closeWindow());
    else setTimeout(() => bridge.closeWindow(), 40);
    (typeof wakeUp === 'function' ? wakeUp('メモ帳') : refreshContext('メモ帳'));
    ({ read: () => closed })
  `);
  await new Promise((res) => setTimeout(res, 140));
  check('呼び戻したあと、前のタイマーで勝手に閉じない', { closed: r.read() }, { closed: 0 });

  // 3. ふだんの呼び戻し（成功表示は出ていない）は、メモの下書きを入れ替える
  r = run(`
    successArea.style.display = 'none';
    formArea.style.display = '';
    autoMemo = '前の下書き'; memoInput.value = '前の下書き'; taskInput.value = '';
    (typeof wakeUp === 'function' ? wakeUp('新しい作業先') : refreshContext('新しい作業先'));
    ({ memo: memoInput.value })
  `);
  check('打ちかけが無ければ、下書きは今の作業先に入れ替わる', r, { memo: '新しい作業先' });

  // 4. 作業先の名前が取れなかった（空）ときに、下書きを消さない
  r = run(`
    successArea.style.display = 'none';
    formArea.style.display = '';
    autoMemo = '前の下書き'; memoInput.value = '前の下書き'; taskInput.value = '';
    (typeof wakeUp === 'function' ? wakeUp('') : (function () { /* 旧: 空なら呼ばれない */ })());
    ({ memo: memoInput.value })
  `);
  check('作業先が取れなくても、下書きは消さない', r, { memo: '前の下書き' });

  // 5. 打ちかけているときは触らない
  r = run(`
    successArea.style.display = 'none';
    formArea.style.display = '';
    autoMemo = '前の下書き'; memoInput.value = '手で直したメモ'; taskInput.value = '打ちかけ';
    (typeof wakeUp === 'function' ? wakeUp('新しい作業先') : refreshContext('新しい作業先'));
    ({ memo: memoInput.value, task: taskInput.value })
  `);
  check('打ちかけているときは下書きを触らない', r,
    { memo: '手で直したメモ', task: '打ちかけ' });

  console.log(failed ? `\n${failed} 件しくじりました` : '\nすべて通りました');
  process.exit(failed ? 1 : 0);
})();
