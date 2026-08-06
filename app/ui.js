const taskInput   = document.getElementById('taskInput');
const memoInput   = document.getElementById('memoInput');
const errMsg      = document.getElementById('errMsg');
const hintArea    = document.getElementById('hintArea');
const submitBtn   = document.getElementById('submitBtn');
const formArea    = document.getElementById('form-area');
const successArea = document.getElementById('successArea');
const successText = document.querySelector('.success-text');
const feedBody    = document.getElementById('feedBody');

const feedTitle   = document.getElementById('feedTitle');
const expandBtn   = document.getElementById('expandBtn');
const wideArea    = document.getElementById('wideArea');
const wideTabs    = document.getElementById('wideTabs');
const wideBody    = document.getElementById('wideBody');
const wideFoot    = document.getElementById('wideFoot');
const wideSort    = document.getElementById('wideSort');
const wideReload  = document.getElementById('wideReload');
const wideBack    = document.getElementById('wideBack');
const wideSearch  = document.getElementById('wideSearch');
const wideExclude = document.getElementById('wideExclude');

const targetsRow    = document.getElementById('targetsRow');
const chipList      = document.getElementById('chipList');
const chipUser      = document.getElementById('chipUser');
const chipDue       = document.getElementById('chipDue');
const chipListLabel = document.getElementById('chipListLabel');
const chipUserLabel = document.getElementById('chipUserLabel');
const chipDueLabel  = document.getElementById('chipDueLabel');
const picker        = document.getElementById('picker');
const pickerScrim   = document.getElementById('pickerScrim');
const pickerSearch  = document.getElementById('pickerSearch');
const pickerNote    = document.getElementById('pickerNote');
const pickerList    = document.getElementById('pickerList');

let bridge = null;
new QWebChannel(qt.webChannelTransport, ch => { bridge = ch.objects.bridge; });

// pause.pyw がウィンドウを出す直前に、背後を撮った画像を渡してくる。
function setBackdrop(uri) {
  document.documentElement.style.setProperty('--backdrop', 'url("' + uri + '")');
}

// エラーとヒントは同じ場所を使う。出し入れしても高さが動かないようにするため。
function showError(text) {
  errMsg.textContent = text;
  errMsg.style.display = text ? '' : 'none';
  hintArea.style.display = text ? 'none' : '';
}

// ── 登録先の候補 ──────────────────────────────────────────

let DIR = { lists: [], members: [] };
let DEFAULT_LIST = { id: '', name: '読み込み中…', path: '' };
let SELF = { id: 0, name: '自分', email: '' };
let RECENT = [];

// よく使うもの。id の文字列を並べておくだけ。押した順は保つ。
let FAV = { lists: [], members: [] };

// 一覧に出さないリスト。config.json の excluded_lists と同じもの。
// 読む側（どのタスクを一覧に載せるか）は Python が見ている。こちらは出し入れのため。
let EXCLUDED = [];

// 期限。start は常に今日で、動かすのは due だけ。
const DUE_PRESETS = [
  { id: 'today',    name: '今日',     hint: '今日じゅう' },
  { id: 'tomorrow', name: '明日',     hint: '明日まで' },
  { id: 'd3',       name: '3日以内',  hint: '3日後まで' },
  { id: 'week',     name: '今週中',   hint: '今週の金曜まで' },
  { id: 'd7',       name: '1週間',    hint: '7日後まで' },
  { id: 'none',     name: '期限なし', hint: '期限を付けない' },
];
let DEFAULT_DUE = 'today';

let pickedList = DEFAULT_LIST;
let pickedUser = SELF;
let pickedDue  = DUE_PRESETS[0];

// pause.pyw が手元の控えから丸ごと渡してくる。絞り込みはこちら側でやる。
// 打鍵ごとに Python を往復させるより速く、通信も要らない。
function setDirectory(data) {
  DIR = { lists: data.lists || [], members: data.members || [] };
  DEFAULT_LIST = data.default_list || DEFAULT_LIST;
  SELF = data.self || SELF;
  RECENT = data.recent || [];
  FAV = {
    lists:   ((data.favorites || {}).lists   || []).map(String),
    members: ((data.favorites || {}).members || []).map(String),
  };
  DEFAULT_DUE = data.default_due || 'today';
  EXCLUDED = (data.excluded || []).map(String);
  resetTargets();
}

// 最近使ったリストだけを入れ替える（登録するたびに変わるので）。
function setRecent(ids) { RECENT = ids || []; }

// よく使うものを入れ替える。★を押した結果は画面側でも持っているが、
// 保存に失敗していた場合はここで実際に保存できた内容へ揃う。
function setFavorites(fav) {
  FAV = {
    lists:   ((fav || {}).lists   || []).map(String),
    members: ((fav || {}).members || []).map(String),
  };
}

function resetTargets() {
  pickedList = DEFAULT_LIST;
  pickedUser = SELF;
  pickedDue  = DUE_PRESETS.find(d => d.id === DEFAULT_DUE) || DUE_PRESETS[0];
  renderTargets();
}

function isDefaultList() { return pickedList.id === DEFAULT_LIST.id; }
function isSelf()        { return pickedUser.id === SELF.id; }
function isDefaultDue()  { return pickedDue.id === DEFAULT_DUE; }

function renderTargets() {
  chipListLabel.textContent = pickedList.name;
  chipUserLabel.textContent = isSelf() ? '自分' : pickedUser.name;
  chipDueLabel.textContent  = pickedDue.name;
  chipList.classList.toggle('changed', !isDefaultList());
  chipUser.classList.toggle('changed', !isSelf());
  chipDue.classList.toggle('changed', !isDefaultDue());
}

// ── よく使うもの ──────────────────────────────────────────

function favIds(kind) { return kind === 'list' ? FAV.lists : FAV.members; }

function isFav(item, kind) { return favIds(kind).includes(String(item.id)); }

// 付いているものを上に。並べ替えの同点を割るのに使う。
function favRank(item, kind) { return isFav(item, kind) ? 0 : 1; }

function toggleFav(item, kind) {
  const key = kind === 'list' ? 'lists' : 'members';
  const id  = String(item.id);
  const on  = FAV[key].includes(id);
  FAV = { ...FAV, [key]: on ? FAV[key].filter(x => x !== id) : [...FAV[key], id] };
  if (bridge) bridge.toggleFavorite(kind, id);
  renderPicker();
}

// ── 既定の入れ替え ────────────────────────────────────────

// ★と違って既定は 1 つだけ。押したものへ移す。
// 初回設定でしか決められなかったものを、後からでも変えられるようにするための入口。
function setDefault(item, kind) {
  if (kind === 'list')     setDefaultList(item);
  else if (kind === 'due') setDefaultDue(item);
}

function redrawDefault() {
  if (isOpen()) renderPicker();      // 返事が来る頃には閉じていることがある
  renderTargets();
}

// ピンを押してもパネルは閉じないので、返事を待つあいだに別の行を選べてしまう。
// あとから届いた古い返事で、そのあとの操作を巻き戻さないための世代番号。
let listSeq = 0;
let dueSeq  = 0;

function setDefaultList(item) {
  if (String(item.id) === String(DEFAULT_LIST.id)) return;
  const seq    = ++listSeq;
  const before = { list: DEFAULT_LIST, recent: RECENT, picked: pickedList };
  // 既定を選んだままなら新しい既定へ追随する。手で別のリストに変えてあるなら触らない。
  const follow = isDefaultList();
  DEFAULT_LIST = item;
  RECENT = RECENT.filter(id => String(id) !== String(item.id));   // 既定は別枠で出る
  if (follow) pickedList = item;
  redrawDefault();

  if (!bridge) return;
  bridge.setDefaultList(String(item.id), raw => {
    if (seq !== listSeq) return;        // もっと新しい操作が走っている。この返事は捨てる
    const res = JSON.parse(raw);
    if (res.ok) {
      if (res.default_list) DEFAULT_LIST = res.default_list;   // 名前や親パスを整えたもの
    } else {
      DEFAULT_LIST = before.list;
      RECENT       = before.recent;
      // 待っているあいだに選び直していたら、そちらを尊重する。
      if (pickedList === item) pickedList = before.picked;
      showError(res.error || '既定を変えられませんでした');
    }
    redrawDefault();
  });
}

function setDefaultDue(item) {
  if (item.id === DEFAULT_DUE) return;
  const seq    = ++dueSeq;
  const before = { due: DEFAULT_DUE, picked: pickedDue };
  const follow = isDefaultDue();
  DEFAULT_DUE = item.id;
  if (follow) pickedDue = item;
  redrawDefault();

  if (!bridge) return;
  bridge.setDefaultDue(item.id, raw => {
    if (seq !== dueSeq) return;
    const res = JSON.parse(raw);
    if (res.ok) return;
    DEFAULT_DUE = before.due;
    if (pickedDue === item) pickedDue = before.picked;
    showError(res.error || '既定を変えられませんでした');
    redrawDefault();
  });
}


// ── フォーム ──────────────────────────────────────────────

// 自動で入れたメモ。手で直されたかを見分けるために覚えておく。
let autoMemo = '';

// context には中断直前まで前にいたウィンドウ名が入る。あくまで下書きなので消して構わない。
function resetForm(context) {
  taskInput.value = '';
  autoMemo = context || '';
  memoInput.value = autoMemo;
  showError('');
  closePicker(false);
  closeWide();             // 広げたまま呼び出されても、打つ画面から始める
  resetTargets();          // 呼び出すたび既定（自分のリスト・自分）へ戻す
  formArea.style.display = '';
  successArea.style.display = 'none';
  submitting = false;              // 前回の送信が終わったままなので、ここで開ける
  submitBtn.disabled = false;
  setTimeout(() => taskInput.focus(), 30);
}

// 出しっぱなしのまま呼び直されたとき。まだ何も手を付けていなければ、
// 今の作業先に入れ替える。打ちかけているなら触らない。
function refreshContext(context) {
  if (!taskInput.value && memoInput.value === autoMemo) {
    autoMemo = context || '';
    memoInput.value = autoMemo;
  }
  if (!taskInput.value) setTimeout(() => taskInput.focus(), 30);
}

function feedNote(text) {
  feedBody.replaceChildren();
  const note = document.createElement('div');
  note.className = 'feed-note';
  note.textContent = text;
  feedBody.appendChild(note);
}

function buildRow(task) {
  const row = document.createElement('div');
  row.className = 'feed-row';
  row.title = 'クリックで ClickUp を開く';

  const check = document.createElement('button');
  check.className = 'feed-check';
  check.title = '完了にする';
  check.innerHTML =
    '<svg viewBox="0 0 12 12" fill="none" stroke-width="2.4" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M2 6.2L4.8 9L10 3"/></svg>';
  check.addEventListener('click', e => {
    e.stopPropagation();
    if (!bridge) return;
    check.disabled = true;
    // 完了を表すステータス名はリストごとに違うので、どのリストの分かも渡す。
    bridge.completeTask(task.id, String(task.list_id || ''), raw => {
      const res = JSON.parse(raw);
      if (res.ok) {
        row.remove();
        if (!feedBody.children.length) feedNote('最近登録したタスクはありません');
      } else {
        check.disabled = false;
        showError(res.error || '完了にできませんでした');
      }
    });
  });

  const text = document.createElement('div');
  text.className = 'feed-text';
  const name = document.createElement('div');
  name.className = 'feed-name';
  name.textContent = task.name;
  text.appendChild(name);

  // いつものリスト以外へ入れたものは、どこへ入れたかも出す。
  // リストを跨いで集めているので、それが無いと見分けが付かない。
  const elsewhere = task.list_id && String(task.list_id) !== String(DEFAULT_LIST.id)
    ? (task.list_name || '') : '';
  const sub = [elsewhere, task.memo].filter(Boolean).join(' · ');
  if (sub) {
    const memo = document.createElement('div');
    memo.className = 'feed-memo';
    memo.textContent = sub;
    text.appendChild(memo);
  }

  row.appendChild(check);
  row.appendChild(text);
  row.addEventListener('click', () => { if (bridge && task.url) bridge.openTask(task.url); });
  return row;
}

// pause.pyw がワーカースレッドで取ってきた中断中タスクを流し込む。
function setTasks(data) {
  if (!data.ok) { feedNote('一覧を取得できませんでした'); return; }
  if (!data.tasks.length) { feedNote('最近登録したタスクはありません'); return; }
  feedBody.replaceChildren();
  data.tasks.forEach(task => feedBody.appendChild(buildRow(task)));
}

// 送信中かどうか。Ctrl+Enter は document 全体で拾っているので、
// ボタンを無効にするだけでは 2 回目・3 回目が素通りしてしまう。
let submitting = false;


// ── フォーム ──────────────────────────────────────────────

function doSubmit() {
  if (submitting) return;
  // 候補を開いたまま Ctrl+Enter された場合。閉じてから送る。
  closePicker(false);
  const name = taskInput.value.trim();
  if (!name) { showError('タスク名を入力してください'); taskInput.focus(); return; }
  if (!bridge) { showError('初期化中です。もう一度お試しください'); return; }
  showError('');
  submitting = true;
  submitBtn.disabled = true;
  bridge.submit(name, memoInput.value, String(pickedList.id), String(pickedUser.id),
                pickedDue.id, raw => {
    const data = JSON.parse(raw);
    if (data.ok) {
      // 送れずに退避した場合は、登録できたように見せずそのことを伝える。
      successText.textContent = data.queued
        ? '接続できないため保存しました。つながり次第、登録します'
        : '登録しました';
      formArea.style.display = 'none';
      successArea.style.display = 'flex';
      setTimeout(() => bridge.closeWindow(), data.queued ? 1800 : 600);
    } else {
      // 失敗したときだけ解除する。成功したら窓ごと引っ込むので戻す必要がない。
      submitting = false;
      showError(data.error || '登録に失敗しました');
      submitBtn.disabled = false;
    }
  });
}

submitBtn.addEventListener('click', doSubmit);

// キーの行き先は、上に載っているものから順に決める。
//
//   1. 更新の知らせ          Esc で閉じるだけ（選ぶものが無い）
//   2. 候補パネル            ↑↓ Enter Esc。広げた一覧の上に出ていてもこちらが先
//   3. 広げた一覧            Esc は、絞り込みに文字があれば消す。無ければ入力へ戻る
//   4. 入力画面              Esc で窓を閉じる、Ctrl+Enter で登録
//
// 2 が 3 より先なのが肝心。逆にすると、一覧から開いた期限のパネルで矢印も Enter も
// 効かず、Esc を押すとパネルではなく一覧ごと閉じてしまう。
document.addEventListener('keydown', e => {
  // 更新の知らせは選ぶものが無いので、Esc で閉じるだけ。
  // 矢印や Enter を候補パネルの操作として拾わせない。
  if (state.kind === 'update') {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeUpdatePanel(); }
    return;
  }

  if (isOpen()) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(state.active + 1); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setActive(state.active - 1); return; }
    if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
      // 変換確定の Enter を決定と取り違えない。
      if (e.isComposing || e.keyCode === 229) return;
      e.preventDefault();
      choose(state.active);
      return;
    }
    if (e.key === 'Escape') {
      // 候補を閉じるだけ。窓は閉じない。
      e.preventDefault();
      e.stopPropagation();
      closePicker(true);
      return;
    }
    if (e.key === 'Tab') { closePicker(false); return; }
  }

  // 広げている間は、こちらの決めごとだけを見る。
  // Esc は窓を閉じるのではなく入力へ戻す（閉じたつもりで消えると打ち直しになる）。
  // 絞り込んでいる最中なら、まずそれを消す。打った文字ごと一覧が畳まれると、
  // 「絞り込みをやめたいだけ」のときに一覧を出し直すことになる。
  if (WIDE.open) {
    if (e.key === 'Escape') {
      e.preventDefault();
      if (WIDE.query) { clearWideSearch(); renderWide(); }
      else            closeWide();
    }
    return;
  }

  if (e.ctrlKey && (e.key === 'e' || e.key === 'E')) { e.preventDefault(); openWide(); return; }

  if (e.ctrlKey && (e.key === 'l' || e.key === 'L')) { e.preventDefault(); openPicker('list'); return; }
  if (e.ctrlKey && (e.key === 'u' || e.key === 'U')) { e.preventDefault(); openPicker('user'); return; }
  if (e.ctrlKey && (e.key === 'd' || e.key === 'D')) { e.preventDefault(); openPicker('due');  return; }


  if (e.key === 'Escape' && bridge) bridge.closeWindow();
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    // 変換の途中なら送らない。未確定のまま飛んでしまうため。
    if (e.isComposing || e.keyCode === 229) return;
    doSubmit();
  }
});
