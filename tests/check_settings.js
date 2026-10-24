// 設定画面を、画面なしで動かして確かめる。
//
//     node tests\check_settings.js
//
// ui.js・picker.js・wide.js・settings.js を続けて読み込む（設定は ui.js の状態を書き換え、
// 一覧の最初のタブは wide.js が読む）。Python 側は偽物の settingsBridge に差し替える。
// 見ているのは主に 3 つ。
//
//   ・呼び出すキーを待ち受けている間、押したキーが入力や Esc（窓を閉じる）に流れないこと
//   ・Ctrl も Alt も無い組み合わせを Python へ送らないこと
//   ・最初のタブの設定が、次に広げたときに効くこと
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const APP = path.join(__dirname, '..', 'app');
const source = ['ui.js', 'picker.js', 'wide.js', 'settings.js']
  .map(name => fs.readFileSync(path.join(APP, name), 'utf8')).join('\n');

function makeEl() {
  const classes = new Set();
  return {
    className: '', textContent: '', type: '', title: '', value: '', placeholder: '',
    disabled: false, style: {}, children: [], dataset: {}, listeners: {},
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
    addEventListener(type, fn) { this.listeners[type] = fn; },
    focus() {}, blur() {}, scrollIntoView() {}, remove() {},
  };
}

function sandbox() {
  const els = {};
  const get = (k) => (els[k] || (els[k] = makeEl()));
  get('hotkeyLabel').parentElement = get('hotkeyBox');
  get('wideTabs').children = ['overdue', 'today', 'week', 'all'].map(scope => {
    const tab = makeEl();
    tab.dataset.scope = scope;
    return tab;
  });
  const keydown = [];
  const calls = [];
  const settings = {
    // 返し方は本物と同じ（JSON 文字列をコールバックへ）。失敗させたいものは box.__fail に入れる。
    loadSettings(cb) {
      calls.push(['loadSettings']);
      cb(JSON.stringify({ ok: true, zoom: 1.25, zoom_steps: [1.0, 1.1, 1.25, 1.4, 1.5],
        corner: 'bottom-right', wide_scope: 'today',
        hotkey: { mods: ['ctrl', 'shift'], vk: 32, label: 'Ctrl+Shift+Space', fell_back: false } }));
    },
    loadAutostart() { calls.push(['loadAutostart']); },
    setAutostart(on) { calls.push(['setAutostart', on]); },
    setZoom(v, cb) { calls.push(['setZoom', v]); cb(JSON.stringify({ ok: true, zoom: Number(v) })); },
    setCorner(v, cb) { calls.push(['setCorner', v]); cb(JSON.stringify({ ok: true, corner: v })); },
    setWideScope(v, cb) { calls.push(['setWideScope', v]); cb(JSON.stringify({ ok: true, wide_scope: v })); },
    setHotkey(mods, vk, cb) {
      calls.push(['setHotkey', mods, vk]);
      cb(JSON.stringify(box.__fail
        ? { ok: false, error: 'そのキーは他のアプリが使っています' }
        : { ok: true, label: 'Ctrl+Shift+K' }));
    },
  };
  const box = {
    console, setTimeout, clearTimeout, JSON,
    document: {
      body: makeEl(),
      getElementById: get, querySelector: get,
      addEventListener(type, fn) { if (type === 'keydown') keydown.push(fn); },
      createElement: makeEl, createDocumentFragment: makeEl,
      createTextNode: (t) => ({ textContent: t }),
    },
    qt: { webChannelTransport: {} },
    QWebChannel: function (t, cb) {
      cb({ objects: {
        bridge: { closeWindow() { calls.push(['closeWindow']); }, imeAlphanumeric() {},
                  setViewMode() {}, loadWide() {} },
        settings,
      } });
    },
    __calls: calls,
    __fail: false,
  };
  box.__press = (e) => {
    const ev = { preventDefault() {}, stopPropagation() {}, ctrlKey: false, altKey: false,
                 shiftKey: false, metaKey: false, isComposing: false, keyCode: 0, ...e };
    keydown.forEach((fn) => fn(ev));
  };
  return box;
}

function run(probe) {
  return vm.runInContext(source + '\n' + probe, vm.createContext(sandbox()),
                         { filename: 'check_settings' });
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

// 並んだボタンのうち、選ばれている（on）ものの文字。
const ON = 'el => el.children.filter(b => b.className.includes(" on")).map(b => b.textContent)';

let r = run(`
  openSettings();
  ({ open: document.body.classList.contains('settings'),
     asked: __calls.map(c => c[0]),
     zoom: (${ON})(setZoomEl), corner: (${ON})(setCornerEl), key: hotkeyLabel.textContent,
     autostartLocked: setAutostartEl.children.every(b => b.disabled) })
`);
check('開くと今の設定が選ばれた状態で並ぶ', r, {
  open: true, asked: ['loadSettings', 'loadAutostart'],
  zoom: ['125%'], corner: ['右下'], key: 'Ctrl+Shift+Space', autostartLocked: true,
});

r = run(`
  openSettings();
  setZoomEl.children.find(b => b.textContent === '150%').listeners.click();
  ({ sent: __calls.filter(c => c[0] === 'setZoom'), zoom: (${ON})(setZoomEl) })
`);
check('大きさを押すとすぐ送り、選び直した表示になる', r, { sent: [['setZoom', '1.5']], zoom: ['150%'] });

r = run(`
  openSettings();
  setWideScopeEl.children.find(b => b.textContent === '期限切れ').listeners.click();
  closeSettings();
  openWide();
  ({ scope: WIDE.scope, on: wideTabs.children.filter(t => t.classList.contains('on')).map(t => t.dataset.scope) })
`);
check('最初のタブの設定が次に広げたときに効く', r, { scope: 'overdue', on: ['overdue'] });

r = run(`
  openSettings();
  startRecording();
  __press({ key: 'K', keyCode: 75, ctrlKey: true, shiftKey: true });
  ({ sent: __calls.filter(c => c[0] === 'setHotkey'), recording: SETTINGS.recording,
     key: hotkeyLabel.textContent })
`);
check('Ctrl+Shift+K を採って送る', r,
  { sent: [['setHotkey', 'ctrl,shift', 75]], recording: false, key: 'Ctrl+Shift+K' });

r = run(`
  openSettings();
  startRecording();
  __press({ key: 'Shift', keyCode: 16, shiftKey: true });
  __press({ key: 'A', keyCode: 65, shiftKey: true });
  __press({ key: 'a', keyCode: 229, ctrlKey: true, isComposing: true });
  ({ sent: __calls.filter(c => c[0] === 'setHotkey').length, recording: SETTINGS.recording,
     msg: settingsMsg.textContent })
`);
check('修飾キーだけ・Shift だけ・変換中は送らない', r,
  { sent: 0, recording: true, msg: 'Ctrl か Alt と一緒に押してください' });

r = run(`
  __fail = true;
  openSettings();
  startRecording();
  __press({ key: 'J', keyCode: 74, ctrlKey: true });
  ({ recording: SETTINGS.recording, msg: settingsMsg.textContent })
`);
check('取られているキーなら待ち受けたまま理由を出す', r,
  { recording: true, msg: 'そのキーは他のアプリが使っています' });

r = run(`
  openSettings();
  startRecording();
  __press({ key: 'Escape', keyCode: 27 });
  const first = { recording: SETTINGS.recording, open: SETTINGS.open };
  __press({ key: 'Escape', keyCode: 27 });
  ({ first, second: SETTINGS.open, closedWindow: __calls.some(c => c[0] === 'closeWindow') })
`);
check('Esc は 1 回目で待ち受けをやめ、2 回目で入力へ戻る（窓は閉じない）', r,
  { first: { recording: false, open: true }, second: false, closedWindow: false });

r = run(`
  openSettings();
  startRecording();
  resetForm('メモ帳');
  ({ open: SETTINGS.open, recording: SETTINGS.recording,
     body: document.body.classList.contains('settings') })
`);
check('窓を出し直すと入力画面から始まる', r, { open: false, recording: false, body: false });

r = run(`
  openSettings();
  onAutostartState({ ok: true, autostart: true, watchdog: false, note: '' });
  ({ on: (${ON})(setAutostartEl), warn: autostartNote.classList.contains('warn'),
     locked: setAutostartEl.children.some(b => b.disabled) })
`);
check('見張り役が欠けていたら知らせる', r, { on: ['オン'], warn: true, locked: false });

r = run(`
  openSettings();
  onAutostartState({ ok: true, autostart: true, watchdog: true, note: '' });
  setAutostartEl.children.find(b => b.textContent === 'オフ').listeners.click();
  ({ sent: __calls.filter(c => c[0] === 'setAutostart'),
     locked: setAutostartEl.children.every(b => b.disabled) })
`);
check('オフを押すと送り、終わるまで押せない', r, { sent: [['setAutostart', false]], locked: true });

console.log(failed ? `\n${failed} 件しくじりました` : '\nすべて通りました');
process.exit(failed ? 1 : 0);
