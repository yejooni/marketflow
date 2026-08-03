import {
  loadJSON, PERIOD_LABELS, nf, pct, money, dirClass, el,
  initTheme, initSearch, markNav, makeSortable, themeChips, probCell, eok,
} from './common.js';

initTheme();
markNav('home');
initSearch();

const tb = document.getElementById('tb');
const table = document.getElementById('tbl');
const emptyBox = document.getElementById('empty');
const countEl = document.getElementById('count');

let leaders = {}, meta = {}, period = '1M', sorter = null;

const filters = {
  market: document.getElementById('f-market'),
  amount: document.getElementById('f-amount'),
  prob: document.getElementById('f-prob'),
  align: document.getElementById('f-align'),
};

function rowsFor(p) {
  const minProb = parseFloat(filters.prob.value) || 0;
  const minAmount = parseFloat(filters.amount.value) || 0;
  const mkt = filters.market.value;
  const alignOnly = filters.align.checked;
  return (leaders[p] || []).filter((r) =>
    (!mkt || r.market === mkt)
    && (r.amount ?? 0) >= minAmount
    && (r.prob ?? 0) >= minProb
    && (!alignOnly || r.ma_aligned));
}

function render(rows) {
  tb.innerHTML = '';
  countEl.textContent = rows.length ? `${rows.length}종목` : '';

  if (!rows.length) {
    emptyBox.hidden = false;
    const any = (leaders[period] || []).length;
    emptyBox.innerHTML = '';
    emptyBox.append(
      el('strong', {}, any ? '조건에 맞는 종목이 없습니다'
                           : `${PERIOD_LABELS[period]} 기준 주도주 후보가 없습니다`),
      el('div', {}, any
        ? '필터를 완화해 보세요.'
        : '상승 추세이면서 신고가가 오늘 사정권(20% 이내)에 든 종목이 없다는 뜻입니다. 하락장에서는 정상적인 결과입니다.'),
    );
    return;
  }
  emptyBox.hidden = true;

  rows.forEach((r, i) => {
    const tr = el('tr', { onclick: () => (location.href = `stock.html?code=${r.code}`) },
      el('td', { class: 'l rank' }, String(i + 1)),
      // No 신고가 badge here: the 신고가까지 column already prints 돌파 in red for
      // exactly these rows, and a badge on a single row widens the 종목 column
      // for the whole table, pushing 주도주점수 out of view.
      el('td', { class: 'l' },
        el('span', { class: 'nm' }, r.name),
        el('span', { class: 'cd' }, r.code),
      ),
      el('td', { class: 'l' }, themeChips(r.themes)),
      el('td', { class: 'num' }, nf(r.close)),
      el('td', { class: 'num ' + dirClass(r.change_pct) }, pct(r.change_pct)),
      el('td', { class: 'num' }, eok(r.marcap)),
      el('td', { class: 'num' }, eok(r.amount)),
      el('td', { class: 'num' }, r.at_high ? el('span', { class: 'up' }, '돌파') : pct(r.gap_pct, 2, false)),
      el('td', {}, probCell(r.prob)),
      el('td', { class: 'num ' + dirClass(r.ret_pct) }, pct(r.ret_pct, 1)),
      el('td', { class: 'num ' + dirClass(r.rs) }, pct(r.rs, 1)),
      el('td', { class: 'num' }, r.vol_surge ? r.vol_surge.toFixed(2) + '×' : '–'),
      el('td', { class: 'num' }, r.turnover != null ? (r.turnover * 100).toFixed(2) + '%' : '–'),
      el('td', {},
        el('div', { class: 'scorecell' },
          el('div', { class: 'track' },
            el('div', { class: 'fill', style: `width:${r.score}%` })),
          el('span', { class: 'val num' }, (r.score ?? 0).toFixed(0)))),
    );
    tb.appendChild(tr);
  });
}

function refresh() {
  sorter = makeSortable(table, rowsFor(period), render, { key: 'score', dir: -1 });
}

function buildTabs() {
  const box = document.getElementById('tabs');
  box.innerHTML = '';
  for (const p of meta.periods || Object.keys(PERIOD_LABELS)) {
    const n = (meta.candidates || {})[p] ?? 0;
    box.appendChild(el('button', {
      class: 'tab' + (p === period ? ' active' : ''),
      onclick: () => {
        period = p;
        box.querySelectorAll('.tab').forEach((b, i) =>
          b.classList.toggle('active', (meta.periods || [])[i] === p));
        refresh();
      },
    }, `${PERIOD_LABELS[p]} 신고가`, el('span', { class: 'muted' }, ` ${n}`)));
  }
}

/** Surface anything that will quietly degrade the data if left alone. */
function buildNotices() {
  const box = document.getElementById('notices');
  box.innerHTML = '';
  const left = meta.krx_key_days_left;

  if (meta.amount_source === 'krx' && left != null && left <= 30) {
    box.appendChild(el('div', { class: 'notice' },
      el('strong', {}, `KRX 인증키 만료 ${left}일 전`),
      el('span', {}, `(${meta.krx_key_expires}) — 갱신하지 않으면 거래대금이 추정치로 돌아갑니다.`)));
  } else if (meta.amount_source !== 'krx' && left != null && left <= 0) {
    box.appendChild(el('div', { class: 'notice' },
      el('strong', {}, 'KRX 인증키 만료됨'),
      el('span', {}, `(${meta.krx_key_expires}) — 거래대금이 추정치로 표시되고 있습니다.`)));
  }
}

function buildStats() {
  const s = document.getElementById('stats');
  const total = Object.values(meta.candidates || {}).reduce((a, b) => a + b, 0);
  const items = [
    ['분석 종목', nf(meta.universe)],
    ['주도주 후보', nf(total)],
    ['상승 / 하락', `${nf(meta.advancing)} / ${nf(meta.declining)}`],
    ['테마', nf(meta.themes)],
    ['기준일', meta.trade_date || '–'],
  ];
  s.innerHTML = '';
  for (const [k, v] of items) {
    s.appendChild(el('div', { class: 'stat' },
      el('div', { class: 'k' }, k), el('div', { class: 'v' }, v)));
  }
}

(async function init() {
  try {
    [meta, leaders] = await Promise.all([
      loadJSON('data/meta.json'),
      loadJSON('data/leaders.json'),
    ]);
  } catch (e) {
    document.getElementById('sub').textContent =
      '데이터를 불러오지 못했습니다. 첫 수집이 아직 실행되지 않았을 수 있습니다.';
    return;
  }

  document.getElementById('sub').textContent =
    `${meta.trade_date} 종가 기준 · ${meta.generated_at} 생성 · `
    + `상승 추세이면서 신고가가 ${meta.reach_pct}% 이내인 종목`;

  period = (meta.periods || ['1M'])[0];
  buildNotices();
  buildStats();
  buildTabs();
  refresh();

  for (const f of Object.values(filters)) f.addEventListener('change', refresh);
})();
