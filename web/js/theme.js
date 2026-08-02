import {
  loadJSON, PERIOD_LABELS, nf, pct, money, dirClass, el,
  initTheme, initSearch, markNav, makeSortable, themeChips, probCell,
} from './common.js';

initTheme();
markNav('theme');
initSearch();

const params = new URLSearchParams(location.search);
const themeId = params.get('id');

const tbl = document.getElementById('tbl');
const thead = document.getElementById('th');
const tb = document.getElementById('tb');
const emptyBox = document.getElementById('empty');
const countEl = document.getElementById('count');
const periodSel = document.getElementById('f-period');
const nameInput = document.getElementById('f-name');

let themes = [], meta = {}, period = '1M';

function headRow(cells) {
  // New th elements need fresh listeners, and the two views sort on different
  // keys, so drop any sort state held on the table.
  delete tbl._mfSort;
  thead.innerHTML = '';
  thead.appendChild(el('tr', {}, ...cells.map((c) =>
    el('th', {
      class: c.l ? 'l' : '',
      'data-sort': c.sort || null,
      'data-asc': c.asc ? '1' : null,
      title: c.title || null,
    }, c.label))));
}

/* ---------------- theme list ---------------- */

function listView() {
  document.getElementById('title').textContent = '테마';
  document.getElementById('sub').textContent =
    `${meta.trade_date} 기준 · ${themes.length}개 테마 · 기간 수익률은 소속 종목 중앙값`;

  headRow([
    { label: '#', l: true },
    { label: '테마', l: true, sort: 'name', asc: true },
    { label: '종목수', sort: 'count' },
    { label: '기간 수익률(중앙값)', sort: 'ret' },
    { label: '주도주 후보', sort: 'cands', title: '해당 기간 후보 조건을 만족한 종목 수' },
    { label: '최고 점수', sort: 'best' },
  ]);

  const q = nameInput.value.trim().toLowerCase();
  const rows = themes
    .filter((t) => !q || t.name.toLowerCase().includes(q))
    .map((t) => ({
      ...t,
      ret: t[`ret_${period}`],
      cands: t[`cands_${period}`] ?? 0,
      best: t[`best_${period}`],
    }));

  const render = (sorted) => {
    tb.innerHTML = '';
    countEl.textContent = `${sorted.length}개`;
    emptyBox.hidden = sorted.length > 0;
    if (!sorted.length) {
      emptyBox.innerHTML = '<strong>일치하는 테마가 없습니다</strong>';
      return;
    }
    sorted.forEach((t, i) => {
      tb.appendChild(el('tr', { onclick: () => (location.href = `theme.html?id=${t.id}`) },
        el('td', { class: 'l rank' }, String(i + 1)),
        el('td', { class: 'l' }, el('span', { class: 'nm' }, t.name)),
        el('td', { class: 'num' }, nf(t.count)),
        el('td', { class: 'num ' + dirClass(t.ret) }, pct(t.ret, 1)),
        el('td', { class: 'num' }, t.cands ? el('span', { class: 'up' }, nf(t.cands)) : '–'),
        el('td', { class: 'num' }, t.best != null ? t.best.toFixed(0) : '–'),
      ));
    });
  };

  makeSortable(tbl, rows, render, { key: 'ret', dir: -1 });
}

/* ---------------- single theme ---------------- */

async function detailView(t) {
  document.getElementById('title').textContent = t.name;
  document.getElementById('sub').innerHTML = '';
  document.getElementById('sub').append(
    el('a', { href: 'theme.html', style: 'color:var(--accent)' }, '← 전체 테마'),
    `  ·  ${t.count}종목  ·  ${meta.trade_date} 기준`,
  );

  headRow([
    { label: '#', l: true },
    { label: '종목', l: true, sort: 'name', asc: true },
    { label: '종가', sort: 'close' },
    { label: '등락률', sort: 'change_pct' },
    { label: '신고가까지', sort: 'gap_pct', asc: true },
    { label: '돌파확률', sort: 'prob' },
    { label: '기간 수익률', sort: 'ret_pct' },
    { label: '주도주점수', sort: 'score' },
  ]);

  // One shared fetch covers every member; see rows.json in build_site.py.
  const all = await loadJSON('data/rows.json');
  const want = new Set(t.members);

  const rows = all.filter((d) => want.has(d.code)).map((d) => {
    const p = d.periods[period] || {};
    return {
      code: d.code, name: d.name, close: d.close, change_pct: d.change_pct,
      gap_pct: p.gap, at_high: p.at_high, prob: p.prob,
      ret_pct: p.ret, score: p.score, candidate: p.cand,
    };
  });

  const render = (sorted) => {
    tb.innerHTML = '';
    countEl.textContent = `${sorted.length}종목`;
    emptyBox.hidden = sorted.length > 0;
    sorted.forEach((r, i) => {
      tb.appendChild(el('tr', { onclick: () => (location.href = `stock.html?code=${r.code}`) },
        el('td', { class: 'l rank' }, String(i + 1)),
        el('td', { class: 'l' },
          el('span', { class: 'nm' }, r.name),
          el('span', { class: 'cd' }, r.code),
          r.candidate ? el('span', { class: 'badge hi', style: 'margin-left:6px' }, '후보') : null),
        el('td', { class: 'num' }, nf(r.close)),
        el('td', { class: 'num ' + dirClass(r.change_pct) }, pct(r.change_pct)),
        el('td', { class: 'num' }, r.gap_pct == null ? '–'
          : r.at_high ? el('span', { class: 'up' }, '돌파') : pct(r.gap_pct, 2, false)),
        el('td', {}, probCell(r.prob)),
        el('td', { class: 'num ' + dirClass(r.ret_pct) }, pct(r.ret_pct, 1)),
        el('td', { class: 'num' }, r.score != null ? r.score.toFixed(0) : '–'),
      ));
    });
  };

  makeSortable(tbl, rows, render, { key: 'score', dir: -1 });
}

/* ---------------- boot ---------------- */

function rebuild() {
  const t = themeId ? themes.find((x) => x.id === themeId) : null;
  if (themeId && !t) {
    document.getElementById('main').innerHTML =
      '<div class="empty"><strong>테마를 찾을 수 없습니다</strong>'
      + '<div><a href="theme.html" style="color:var(--accent)">전체 테마 보기</a></div></div>';
    return;
  }
  if (t) detailView(t); else listView();
}

(async function init() {
  try {
    [meta, themes] = await Promise.all([
      loadJSON('data/meta.json'),
      loadJSON('data/themes.json'),
    ]);
  } catch {
    document.getElementById('sub').textContent = '데이터를 불러오지 못했습니다.';
    return;
  }

  for (const p of meta.periods || Object.keys(PERIOD_LABELS)) {
    periodSel.appendChild(el('option', { value: p }, PERIOD_LABELS[p]));
  }
  period = periodSel.value = (meta.periods || ['1M'])[0];
  periodSel.addEventListener('change', () => { period = periodSel.value; rebuild(); });
  nameInput.addEventListener('input', () => { if (!themeId) rebuild(); });
  if (themeId) nameInput.closest('label').style.display = 'none';

  rebuild();
})();
