// 設定画面。ui.js が用意した要素と状態（bridge・settingsBridge・DEFAULT_WIDE_SCOPE）を使う。
//
// 選んだ瞬間に Python 側（settings_bridge.py）へ渡し、保存できたものだけを表示に反映する。
// 「保存」ボタンは置かない。窓を引っ込めたら消える画面なので、押し忘れると変えたつもりの
// ものが黙って戻ってしまう。

const settingsBtn    = document.getElementById('settingsBtn');
const settingsBack   = document.getElementById('settingsBack');
const settingsMsg    = document.getElementById('settingsMsg');
const setZoomEl      = document.getElementById('setZoom');
const setCornerEl    = document.getElementById('setCorner');
const setWideScopeEl = document.getElementById('setWideScope');
const setAutostartEl = document.getElementById('setAutostart');
const autostartNote  = document.getElementById('autostartNote');
const hotkeyLabel    = document.getElementById('hotkeyLabel');
const hotkeyChange   = document.getElementById('hotkeyChange');
const hotkeyNote     = document.getElementById('hotkeyNote');

const SETTINGS = { open: false, recording: false, hotkey: '' };

const CORNER_CHOICES = [
  ['bottom-right', '右下'], ['top-right', '右上'], ['bottom-left', '左下'], ['top-left', '左上'],
];
const SCOPE_CHOICES = [
  ['overdue', '期限切れ'], ['today', '今日'], ['week', '今週'], ['all', 'すべて'],
];
const AUTOSTART_CHOICES = [['on', 'オン'], ['off', 'オフ']];

// 押しただけでは記録しないキー。修飾キーは組み合わせの一部として後で拾う。
const MODIFIER_KEYS = ['Control', 'Shift', 'Alt', 'Meta', 'AltGraph'];

const HOTKEY_HELP = '変えたいときは「変更」を押して、新しい組み合わせを押してください';

function settingsMessage(text, isError) {
  settingsMsg.textContent = text || '';
  settingsMsg.classList.toggle('error', !!(text && isError));
}

// 選ぶボタンを並べる。3 つの択（大きさ・位置・タブ）と自動起動で共通。
function renderSegments(container, choices, current, onPick, disabled) {
  container.replaceChildren(...choices.map(([value, text]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'wide-tab' + (value === current ? ' on' : '');
    button.textContent = text;
    button.disabled = !!disabled;
    button.addEventListener('click', () => { if (value !== current) onPick(value); });
    return button;
  }));
}

// 1.25 → 「125%」。倍率のままより、どれくらい大きいかが掴みやすい。
function zoomText(zoom) { return Math.round(zoom * 100) + '%'; }

function renderZoom(zoom, steps) {
  const choices = steps.map(step => [String(step), zoomText(step)]);
  renderSegments(setZoomEl, choices, String(zoom),
    value => applySetting('setZoom', value, res => renderZoom(res.zoom, steps)));
}

function renderCorner(corner) {
  renderSegments(setCornerEl, CORNER_CHOICES, corner,
    value => applySetting('setCorner', value, res => renderCorner(res.corner)));
}

function renderWideScope(scope) {
  renderSegments(setWideScopeEl, SCOPE_CHOICES, scope,
    value => applySetting('setWideScope', value, res => {
      DEFAULT_WIDE_SCOPE = res.wide_scope;
      renderWideScope(res.wide_scope);
    }));
}

// 決めごとは Python 側が持つ。通らなかったら表示は変えず、理由だけ出す。
function applySetting(call, value, onDone) {
  if (!settingsBridge) return;
  settingsBridge[call](String(value), raw => {
    const res = JSON.parse(raw);
    if (!res.ok) { settingsMessage(res.error || '変えられませんでした', true); return; }
    settingsMessage('');
    onDone(res);
  });
}

function renderSettings(raw) {
  const s = JSON.parse(raw);
  if (!s.ok) { settingsMessage('設定を読めませんでした', true); return; }
  renderZoom(s.zoom, s.zoom_steps);
  renderCorner(s.corner);
  renderWideScope(s.wide_scope);
  SETTINGS.hotkey = s.hotkey.label;
  hotkeyLabel.textContent = s.hotkey.label;
  showHotkeyNote(s.hotkey.fell_back);
}

function showHotkeyNote(fellBack) {
  hotkeyNote.textContent = fellBack
    ? '保存してあったキーは他のアプリに使われていたので、いまはこのキーで動いています'
    : HOTKEY_HELP;
  hotkeyNote.classList.toggle('warn', !!fellBack);
}

// ── 開け閉め ──────────────────────────────────────────────

function openSettings() {
  if (SETTINGS.open || !settingsBridge) return;
  closePicker(false);
  closeWide();
  SETTINGS.open = true;
  document.body.classList.add('settings');
  settingsMessage('');
  renderAutostart(null, '確かめています…');
  settingsBridge.loadSettings(renderSettings);
  settingsBridge.loadAutostart();       // 返事は onAutostartState へ届く
}

// resetForm からも呼ばれる。窓を出し直したら、必ず打つ画面から始めるため。
function closeSettings() {
  if (!SETTINGS.open) return;
  stopRecording();
  SETTINGS.open = false;
  document.body.classList.remove('settings');
  setTimeout(() => taskInput.focus(), 30);
}

// ── 呼び出すキー ──────────────────────────────────────────

function startRecording() {
  SETTINGS.recording = true;
  hotkeyLabel.parentElement.classList.add('recording');
  hotkeyLabel.textContent = 'キーを押してください';
  hotkeyChange.textContent = 'やめる';
  hotkeyNote.textContent = 'Ctrl か Alt と一緒に押してください（Esc でやめる）';
  hotkeyNote.classList.remove('warn');
  settingsMessage('');
  // ボタンに当たりを残すと、Space や Enter がキーとして採られる前にボタンを押してしまう。
  hotkeyChange.blur();
  // 日本語入力のままだと文字キーが変換に取られ、どのキーかが届かない。
  if (bridge) bridge.imeAlphanumeric();
}

function stopRecording() {
  if (!SETTINGS.recording) return;
  SETTINGS.recording = false;
  hotkeyLabel.parentElement.classList.remove('recording');
  hotkeyLabel.textContent = SETTINGS.hotkey;
  hotkeyChange.textContent = '変更';
  showHotkeyNote(false);
}

// 押されたキーを {mods, vk} にする。まだ組み合わせになっていなければ null。
//
// vk には keyCode をそのまま使う。Windows の Chromium では仮想キーコードと同じ値で、
// RegisterHotKey にそのまま渡せる。e.key は Shift で記号に化けるので使えない。
function recordHotkey(e) {
  if (e.isComposing || e.keyCode === 229) return null;
  if (MODIFIER_KEYS.includes(e.key)) return null;
  const mods = [e.ctrlKey && 'ctrl', e.altKey && 'alt', e.shiftKey && 'shift'].filter(Boolean);
  return { mods, vk: e.keyCode };
}

function submitHotkey(combo) {
  settingsBridge.setHotkey(combo.mods.join(','), combo.vk, raw => {
    const res = JSON.parse(raw);
    // 通らなければ待ち受けたままにする。続けて別の組み合わせを試せるように。
    if (!res.ok) { settingsMessage(res.error, true); return; }
    SETTINGS.hotkey = res.label;
    stopRecording();
    settingsMessage(res.note || `${res.label} で呼び出せるようになりました`, !!res.note);
  });
}

// 設定画面が開いている間のキー。ui.js の keydown から回ってくる。
function onSettingsKey(e) {
  if (!SETTINGS.recording) {
    if (e.key === 'Escape') { e.preventDefault(); closeSettings(); }
    return;
  }
  e.preventDefault();
  e.stopPropagation();
  if (e.key === 'Escape' && !e.ctrlKey && !e.altKey && !e.shiftKey) { stopRecording(); return; }
  const combo = recordHotkey(e);
  if (!combo) return;
  if (!combo.mods.includes('ctrl') && !combo.mods.includes('alt')) {
    settingsMessage('Ctrl か Alt と一緒に押してください', true);
    return;
  }
  submitHotkey(combo);
}

// ── 自動起動 ──────────────────────────────────────────────

// state が null のあいだは調べている最中。押せないようにしておく
//（PowerShell を並べて走らせると、登録と解除が入れ違う）。
function renderAutostart(state, note) {
  if (!state) {
    renderSegments(setAutostartEl, AUTOSTART_CHOICES, '', () => {}, true);
    autostartNote.textContent = note || '';
    autostartNote.classList.remove('warn');
    return;
  }
  const current = state.autostart ? 'on' : 'off';
  renderSegments(setAutostartEl, AUTOSTART_CHOICES, current, toggleAutostart);
  const half = state.autostart !== state.watchdog;
  autostartNote.textContent = autostartText(state);
  autostartNote.classList.toggle('warn', half);
}

function autostartText(state) {
  if (state.autostart && !state.watchdog) {
    return '見張り役（落ちたときに起こし直す仕組み）が登録されていません。オンを押すと登録し直します';
  }
  if (!state.autostart && state.watchdog) return '見張り役だけ残っています。オフを押すと外れます';
  return state.autostart ? 'もし落ちても、5 分以内に自動で起こし直します' : '';
}

function toggleAutostart(value) {
  if (!settingsBridge) return;
  const on = value === 'on';
  renderAutostart(null, on ? '登録しています…' : '外しています…');
  settingsBridge.setAutostart(on);
}

// settings_bridge.py が裏で調べ終えたら呼ぶ。
function onAutostartState(res) {
  if (!res.ok) {
    settingsMessage(res.error || '自動起動を確かめられませんでした', true);
    renderSegments(setAutostartEl, AUTOSTART_CHOICES, '', toggleAutostart);
    autostartNote.textContent = '';
    return;
  }
  renderAutostart(res);
  if (res.note) settingsMessage(res.note, true);
}

settingsBtn.addEventListener('click', openSettings);
settingsBack.addEventListener('click', closeSettings);
hotkeyChange.addEventListener('click', () => {
  if (SETTINGS.recording) stopRecording();
  else startRecording();
});
