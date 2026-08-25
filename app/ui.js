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

// ── 人の名前の見せ方 ──────────────────────────────────────

// 名前に使える幅。半角を 1、全角を 2 として数える。担当者のチップは
// 窓幅 390px のうち 4 割しか使えず、そこに「+2」まで収める必要がある。
const NAME_WIDTH_MAX = 16;

// 半角を 1、全角を 2 として数えた幅。実際の字送りは書体で変わるが、
// ここで欲しいのは「刈るかどうか」の見当なので、これで足りる。
//
// 字数で切ってはいけない。ClickUp の表示名はローマ字のこともあり、
// 日本語の 4 文字ぶんの幅しかない「Furukawa」まで刈ってしまう。
function displayWidth(text) {
  let width = 0;
  for (const ch of text) width += /[\x20-\x7E\uFF61-\uFF9F]/.test(ch) ? 1 : 2;
  return width;
}

// 空白（半角・全角）で割った先頭の塊。ClickUp の表示名は「姓 名」と「名 姓」が
// 混ざっているので、どちらでも頭のひと塊を採る。長い名前はここで刈ってしまう。
//
// CSS の省略記号（text-overflow）に任せてはいけない。チップは幅が足りず、
// 削られるのは右端＝「+2」の側になる。名前が少し長いだけで、何人に振ったのかが
// 画面から消える。
function shortName(name) {
  const head = String(name || '').split(/[\s　]+/).filter(Boolean)[0] || '';
  if (displayWidth(head) <= NAME_WIDTH_MAX) return head;
  let out = '';
  for (const ch of head) {
    if (displayWidth(out + ch) > NAME_WIDTH_MAX - 1) break;   // 「…」のぶんを空ける
    out += ch;
  }
  return out + '…';
}

// 何人かをひと目ぶんに畳む。「先頭ひとり ＋ 残りの数」。
function peopleLabel(names) {
  const list = (names || []).filter(Boolean);
  if (!list.length) return '';
  const head = shortName(list[0]);
  return list.length === 1 ? head : `${head} +${list.length - 1}`;
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

let pickedList  = DEFAULT_LIST;
// 担当者は何人でも。押した順に並ぶ（送るときに Python 側が昇順へ均す）。
let pickedUsers = [SELF];
let pickedDue   = DUE_PRESETS[0];

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
  pickedList  = DEFAULT_LIST;
  pickedUsers = [SELF];
  pickedDue   = DUE_PRESETS.find(d => d.id === DEFAULT_DUE) || DUE_PRESETS[0];
  renderTargets();
}

function isDefaultList() { return pickedList.id === DEFAULT_LIST.id; }
function isDefaultDue()  { return pickedDue.id === DEFAULT_DUE; }

// 人の id は、控え（ClickUp の応答）では数、画面で組んだものでは文字と、
// 経路によって型が変わる。=== で比べると同じ人を別人と読んで、
// 「自分が担当に入っていない」と言い続けることになる。必ず文字にしてから比べる。
function samePerson(a, b) { return String(a && a.id) === String(b && b.id); }

function isPickedUser(item) { return pickedUsers.some(u => samePerson(u, item)); }
function hasSelf()          { return isPickedUser(SELF); }
function isDefaultUsers()   { return pickedUsers.length === 1 && hasSelf(); }

// 担当者の名前を、見せる順に並べる。自分は先頭。
// まず知りたいのは「これは自分の手元に残るのか」なので。
function pickedUserNames() {
  // 元の配列は触らない。並べ替えは見せ方の話で、選んだ順そのものではない。
  return [...pickedUsers]
    .sort((a, b) => (samePerson(a, SELF) ? 0 : 1) - (samePerson(b, SELF) ? 0 : 1))
    .map(u => (samePerson(u, SELF) ? '自分' : u.name));
}

// 自分が担当から外れているとき、誰に振ったのかをひと言で。
// ここは幅に余裕があるので名前は刈らない（チップと違って 2 行使える）。
function awayText() {
  const names = pickedUserNames();
  const head  = names[0] || '';
  return names.length > 1 ? `${head}さんほか ${names.length - 1} 人` : `${head}さん`;
}

// チップに載せきれない中身は、指を置けば読めるようにしておく。
// ui.html に書いてある「担当者（Ctrl+U）」を上書きする形になるので、
// ショートカットの案内もここで併せて出す。
function userChipTitle() {
  const lines = ['担当者（Ctrl+U）', pickedUserNames().join('、')];
  if (!hasSelf())
    lines.push('自分が担当に入っていません。'
             + 'この一覧は自分が担当のぶんだけを出すので、ここには出ません');
  return lines.join('\n');
}

function renderTargets() {
  chipListLabel.textContent = pickedList.name;
  chipUserLabel.textContent = peopleLabel(pickedUserNames());
  chipDueLabel.textContent  = pickedDue.name;
  chipList.classList.toggle('changed', !isDefaultList());
  chipUser.classList.toggle('changed', !isDefaultUsers());
  chipDue.classList.toggle('changed', !isDefaultDue());
  // 自分が外れているときは、登録する前に言っておく。一覧は自分の担当ぶんだけを
  // 取ってくるので、このまま送ると手元のどこにも出てこない。
  // .changed（既定と違う）とは別の話なので、色は潰さず枠だけで言う。
  chipUser.classList.toggle('away', !hasSelf());
  chipUser.title = userChipTitle();
}

// 担当者の入り切り。候補パネルは開けたままにする（続けて何人か選ぶのが普通なので）。
//
// 最後のひとりは外せない。担当のいないタスクは、作った当人しか在り処を知らないまま
// ClickUp のどこかに残る。外したいなら、先に別の人を足してから外せばよい。
function toggleUser(item) {
  const on = isPickedUser(item);
  if (on && pickedUsers.length === 1) {
    // 次にどれかを入り切りすれば renderPicker が書き戻すので、ここでは出すだけ。
    pickerNote.textContent = 'ひとりは選んでください。'
                           + '先に別の人を足せば、この人は外せます';
    pickerNote.style.display = '';
    return;
  }
  // 配列は差し替える。push で書き換えると、それを握っている側が
  // 気づかないまま中身だけ変わる。
  pickedUsers = on ? pickedUsers.filter(u => !samePerson(u, item))
                   : [...pickedUsers, item];
  renderTargets();
  if (isOpen()) renderPicker();      // ☑ の付け外しと並び順を、その場で映す
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

// 少し置いてから窓を閉じる／表示を戻すためのタイマー。1 つだけ持っておく。
// 呼び直されたときに取り消せないと、出し直した直後に前の名残で勝手に隠れる。
let pendingTimer = null;

function later(ms, run) {
  cancelLater();
  pendingTimer = setTimeout(() => { pendingTimer = null; run(); }, ms);
}

function cancelLater() {
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
}

// 出しっぱなしのまま、もう一度呼ばれたとき。pause.pyw は必ずここを通す。
//
// 「登録しました」や更新の知らせを出したままだと、打つ画面へ戻さない限り
// Ctrl+Enter も効かないまま固まって見える（送信中の札を下ろすのは resetForm だけ）。
// 呼び直された以上、閉じるつもりで仕掛けたタイマーも取り消す。
function wakeUp(context) {
  cancelLater();
  if (successArea.style.display !== 'none') { resetForm(context); return; }
  if (context) refreshContext(context);      // 空で上書きしてメモを消さない
}

// 手で打ったものが残っているか。
//
// メモは autoMemo と比べる。自動で入れた下書きのままなら、手は付いていない。
// 見分ける規則をここ 1 か所に集めて、resetForm と refreshContext の両方で使う。
function hasDraft() {
  return !!taskInput.value.trim() || memoInput.value !== autoMemo;
}

// context には中断直前まで前にいたウィンドウ名が入る。あくまで下書きなので消して構わない。
//
// ただし打ちかけているものは消さない。中断メモを打っている最中に別の用事が入るのは
// 日常的で、そのたびに Esc で引っ込めると打ち直しになっていた。窓を閉じても
// このプロセスは生きているので、値はそのまま残っている。消さなければよいだけ。
//
// リストや担当者まで組んであるなら、そちらも一緒に残す（resetTargets を飛ばす）。
// 文字だけ残して選び先を既定へ戻すと、送る直前に気づかないまま別の場所へ入る。
//
// 打つ画面へ戻す手当て——送信中の札を下ろす・広げた一覧を畳む・候補を閉じる——は、
// 打ちかけの有無に関わらず必ずやる。ここを飛ばすと窓が固まったまま戻せなくなる。
function resetForm(context) {
  cancelLater();
  showError('');
  closePicker(false);
  closeWide();             // 広げたまま呼び出されても、打つ画面から始める
  if (!hasDraft()) {
    taskInput.value = '';
    autoMemo = context || '';
    memoInput.value = autoMemo;
    resetTargets();        // 打ちかけが無いときだけ、既定（自分のリスト・自分）へ戻す
  }
  formArea.style.display = '';
  successArea.style.display = 'none';
  submitting = false;              // 前回の送信が終わったままなので、ここで開ける
  submitBtn.disabled = false;
  setTimeout(() => taskInput.focus(), 30);
}

// 出しっぱなしのまま呼び直されたとき。まだ何も手を付けていなければ、
// 今の作業先に入れ替える。打ちかけているなら触らない。
function refreshContext(context) {
  if (!hasDraft()) {
    autoMemo = context || '';
    memoInput.value = autoMemo;
  }
  // 候補パネルが出ている間はフォーカスを動かさない。パネルは入力欄を隠さない
  //（暗幕の下で生きている）ので、ここで移すと絞り込みに打っている続きが
  // 見えないまま入力欄へ流れ込み、絞り込みが反応しなくなる。
  if (!taskInput.value && !isOpen()) setTimeout(() => taskInput.focus(), 30);
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
    pendingComplete.set(String(task.id), res => {
      if (res.ok) {
        row.remove();
        if (!feedBody.children.length) feedNote('最近登録したタスクはありません');
      } else {
        check.disabled = false;
        showError(res.error || '完了にできませんでした');
      }
    });
    // 完了を表すステータス名はリストごとに違うので、どのリストの分かも渡す。
    bridge.completeTask(String(task.id), String(task.list_id || ''));
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
  // 誰と分け合っているかは、メモより前に置く。この行は 1 行しかないので、
  // 溢れたぶんは後ろから省略記号で切られる。メモは ClickUp を開けば読めるが、
  // 担当者は行から読めないと確かめようがない。切られてよいのはメモの側。
  const who = peopleLabel(task.others);
  const sub = [elsewhere, who && '@' + who, task.memo].filter(Boolean).join(' · ');
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
  // 担当者はカンマで繋いで 1 本にする（QWebChannel の口に配列は渡せない）。
  // 重なりや並び順を均すのは Python 側。画面の押し順のまま送ってよい。
  bridge.submit(name, memoInput.value, String(pickedList.id),
                pickedUsers.map(u => String(u.id)).join(','), pickedDue.id);
}

// 登録の結果。送るのは裏でやっているので、返事はここへ届く
//（待っている間も窓は動くし、ホットキーも効く）。
function onSubmitDone(data) {
  if (data.ok) {
    // 送れた（または預かった）ぶんは、打ちかけとしては片付いている。ここで空に
    // しておかないと、次に窓を出したとき resetForm が「打ちかけがある」と読んで、
    // 登録済みのものが入ったまま出てくる。
    // duplicate（連打の 2 件目）も queued（預かった分）も、入っていることに変わりない。
    taskInput.value = '';
    memoInput.value = '';
    autoMemo = '';
    // 送れずに退避した場合は、登録できたように見せずそのことを伝える。
    //
    // 自分が担当から外れているときは「出ません」ではなく「なぜ出ないか」を言う。
    // 行に担当者を出すようにしたので、ただ「出ません」とだけ書くと、
    // 一覧に他人ぶんも出るようになったのに、という食い違いに読める。
    // 預かった場合は触れない。まだ登録していないのだから、出ないのは当たり前で、
    // 言うべきは「まだ送れていない」ことの方。
    // 改行は自分で決める（.success-text は white-space: pre-line）。
    // 折り返しに任せると「担当の / ぶんだけを」のように語の途中で切れて、
    // 一目で読めない。文の切れ目で改める。
    successText.textContent = data.queued
      ? '接続できないため保存しました\nつながり次第、登録します'
      : data.away
        ? `${awayText()}に振りました\n`
          + '自分は担当ではないので、一覧には出ません'
        : '登録しました';
    formArea.style.display = 'none';
    successArea.style.display = 'flex';
    // 読ませたい字数ぶんだけ置く。600ms は「登録しました」を読み取る間。
    later(data.queued ? 1800 : data.away ? 2600 : 600, () => bridge.closeWindow());
    return;
  }
  // 失敗したときだけ解除する。成功したら窓ごと引っ込むので戻す必要がない。
  submitting = false;
  showError(data.error || '登録に失敗しました');
  submitBtn.disabled = false;
}

// 完了の返事を、押した行へ配る。裏で送るので、どの行の分かは id で引き当てる。
const pendingComplete = new Map();

function onTaskCompleted(res) {
  const done = pendingComplete.get(String(res.id));
  if (!done) return;
  pendingComplete.delete(String(res.id));
  done(res);
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
      // 担当者の Enter は「選ぶ」だけで、閉じない。何人でも選べるので、
      // ひとりごとに窓が引っ込んでは用を成さない。
      // 閉じるのは Esc・Tab・外を押したとき。
      if (state.kind === 'user') {
        // 当たるものが無ければ何もしない。ここで欄まで空にすると、打ち間違いや
        // 変換し忘れのときに、誰も選べないうえ打ち直しになる。
        if (!state.rows.length) return;
        choose(state.active);
        // 打ってあったぶんは流す。続けて次の人を名前で探せるようにするため。
        if (pickerSearch.value) {
          pickerSearch.value = '';
          renderPicker();          // 空欄の並び（選んだ人が上に来る）へ組み直す
        }
        return;
      }
      choose(state.active);
      return;
    }
    // 絞り込みに何も打っていないときの空白は、光っている行の入り切りに使う。
    // 矢印だけで選ぶ道を残すため。打ちかけているなら名前の中の空白として通すので、
    // 「田中 太郎」のような 2 語での絞り込みはそのまま効く。
    if (e.key === ' ' && state.kind === 'user' && !pickerSearch.value) {
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
