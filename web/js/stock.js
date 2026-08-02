import {
  loadJSON, PERIOD_LABELS, nf, pct, money, dirClass, el,
  initTheme, initSearch, markNav, themeChips,
} from './common.js';
import { KiwoomChart } from './chart.js';

initTheme();
markNav('');
initSearch();

const params = new URLSearchParams(location.search);
const code = params.get('code');

const LEVEL_COLORS = {
  '1M': '--ma5', '3M': '--ma20', '6M': '--ma60', '12M': '--ma120',
};

const RANGES = [
  ['3개월', 60], ['6개월', 120], ['1년', 9999],
];

let chart = null;

function head(d) {
  const h = document.getElementById('head');
  h.innerHTML = '';
  h.append(
    el('div', {},
      el('h1', {}, d.name, ' ', el('span', { class: 'code' }, d.code)),
      el('div', { style: 'margin-top:6px' },
        el('span', { class: 'chip' }, d.market),
        ...themeChips(d.themes)),
    ),
    el('div', { class: 'spacer', style: 'flex:1' }),
    el('div', { class: 'px' },
      el('span', { class: 'last ' + dirClass(d.change_pct) }, nf(d.close)),
      el('span', { class: 'chg ' + dirClass(d.change_pct) }, pct(d.change_pct)),
    ),
  );
  document.title = `${d.name} (${d.code}) — MarketFlow`;
}

function buildChart(d) {
  const host = document.getElementById('chart');
  const levels = Object.entries(d.periods).map(([k, p]) => ({
    value: p.high,
    label: `${PERIOD_LABELS[k]} 고가 ${nf(p.high)}`,
    color: getComputedStyle(document.documentElement)
      .getPropertyValue(LEVEL_COLORS[k]).trim(),
  }));

  chart = new KiwoomChart(host, d.ohlcv, {
    height: Math.max(360, Math.min(560, Math.round(window.innerHeight * 0.56))),
    levels,
    initialBars: 120,
  });

  const box = document.getElementById('range-btns');
  RANGES.forEach(([label, bars], i) => {
    const b = el('button', {
      class: i === 1 ? 'on' : '',
      onclick: () => {
        box.querySelectorAll('button').forEach((x) => x.classList.remove('on'));
        b.classList.add('on');
        chart.setRange(bars);
      },
    }, label);
    box.appendChild(b);
  });

  const maBtn = document.getElementById('t-ma');
  maBtn.addEventListener('click', () => {
    chart.opts.showMA = !chart.opts.showMA;
    maBtn.classList.toggle('on', chart.opts.showMA);
    chart.draw();
  });
  const lvBtn = document.getElementById('t-lv');
  lvBtn.addEventListener('click', () => {
    chart.opts.showLevels = !chart.opts.showLevels;
    lvBtn.classList.toggle('on', chart.opts.showLevels);
    chart.draw();
  });

  // Level colours are CSS variables, so re-resolve them when the theme flips.
  window.addEventListener('mf-theme', () => {
    chart.opts.levels = Object.entries(d.periods).map(([k, p]) => ({
      value: p.high,
      label: `${PERIOD_LABELS[k]} 고가 ${nf(p.high)}`,
      color: getComputedStyle(document.documentElement)
        .getPropertyValue(LEVEL_COLORS[k]).trim(),
    }));
    chart.draw();
  });
}

const COMPONENT_LABELS = {
  prob: '돌파확률', trend: '추세', rs: '상대강도', volume: '거래대금', proximity: '근접도',
};

function periodCards(d) {
  const box = document.getElementById('periods');
  box.innerHTML = '';

  const shown = Object.keys(d.periods).length;
  const missing = Object.keys(PERIOD_LABELS).filter((k) => !(k in d.periods));

  if (!shown) {
    box.appendChild(el('div', { class: 'panel', style: 'grid-column:1/-1' },
      el('div', { class: 'body' },
        el('strong', {}, '분석 기간이 아직 부족합니다'),
        el('div', { class: 'note', style: 'margin-top:6px' },
          `상장 이후 거래일이 ${nf(d.bars)}일뿐이라 가장 짧은 1개월(20일) 신고가도 `
          + '아직 계산할 수 없습니다. 위 차트로 시세는 확인할 수 있고, '
          + '거래일이 쌓이면 자동으로 분석에 포함됩니다.'))));
    return;
  }

  for (const [k, p] of Object.entries(d.periods)) {
    const hasProb = p.prob != null;
    const probPct = (p.prob ?? 0) * 100;

    const bars = el('div', { class: 'bars' },
      ...Object.entries(p.components || {}).map(([ck, cv]) =>
        el('div', { class: 'row' },
          el('span', { class: 'muted' }, COMPONENT_LABELS[ck] || ck),
          el('div', { class: 'track' }, el('div', { class: 'fill', style: `width:${cv}%` })),
          el('span', { class: 'n' }, cv.toFixed(0)))));

    box.appendChild(el('div', { class: 'pcard' + (p.candidate ? ' cand' : '') },
      el('h3', {},
        `${PERIOD_LABELS[k]} 신고가`,
        p.at_high ? el('span', { class: 'badge hi' }, '돌파 중') : null,
        p.candidate ? el('span', { class: 'badge hi' }, '주도주 후보') : null),

      el('div', { class: 'big ' + (hasProb && probPct >= 20 ? 'up' : '') },
        hasProb ? probPct.toFixed(1) + '%' : '–'),
      el('div', { class: 'note', style: 'margin-bottom:10px' },
        hasProb ? `오늘 장중 돌파 빈도 · 표본 ${nf(p.prob_n)}일`
                : '표본이 부족해 확률을 내지 않습니다'),

      el('dl', { class: 'kv' },
        el('dt', {}, '기간 고가'), el('dd', {}, nf(p.high)),
        el('dt', {}, '고가 일자'), el('dd', {}, `${p.high_date} (${p.days_since_high}일 전)`),
        el('dt', {}, '남은 상승폭'),
        el('dd', { class: p.at_high ? 'up' : '' }, p.at_high ? '돌파' : pct(p.gap_pct, 2, false)),
        el('dt', {}, '기간 수익률'), el('dd', { class: dirClass(p.ret_pct) }, pct(p.ret_pct, 1)),
        el('dt', {}, '상대강도'), el('dd', { class: dirClass(p.rs) }, pct(p.rs, 1)),
        el('dt', {}, '추세 적합도'), el('dd', {}, (p.r2 ?? 0).toFixed(2)),
      ),
      el('div', { style: 'margin-top:10px' },
        el('div', { class: 'note', style: 'margin-bottom:4px' },
          '주도주 점수 ', el('strong', {}, (p.score ?? 0).toFixed(0))),
        bars),
    ));
  }

  if (missing.length) {
    box.appendChild(el('div', { class: 'note', style: 'grid-column:1/-1' },
      `상장 이후 거래일이 ${nf(d.bars)}일이라 `
      + missing.map((k) => PERIOD_LABELS[k]).join(' · ')
      + ' 신고가는 기간이 채워지지 않아 표시하지 않습니다.'));
  }
}

function panels(d) {
  const info = document.getElementById('info');
  const rows = [
    ['기준일', d.date],
    ['시장', d.market],
    ['종가', nf(d.close)],
    ['거래량', nf(d.volume)],
    ['거래대금(추정)', money(d.amount)],
    ['20일 평균 거래대금', money(d.amount20)],
    ['시가총액', d.marcap ? money(d.marcap) : '–'],
    ['상장주식수', d.shares ? nf(d.shares) : '–'],
  ];
  info.innerHTML = '';
  for (const [k, v] of rows) info.append(el('dt', {}, k), el('dd', {}, v));

  const diag = document.getElementById('diag');
  const yes = (b) => el('span', { class: b ? 'up' : 'muted' }, b ? '예' : '아니오');
  const drows = [
    ['20일선 위', yes(d.uptrend)],
    ['정배열 (종가>20>60>120)', yes(d.ma_aligned)],
    ['유동성 충족', yes(d.liquid)],
    ['일간 변동성', (d.volatility ?? 0).toFixed(2) + '%'],
    ['거래대금 증가율', d.vol_surge ? d.vol_surge.toFixed(2) + '×' : '–'],
  ];
  diag.innerHTML = '';
  for (const [k, v] of drows) diag.append(el('dt', {}, k), el('dd', {}, v));

  document.getElementById('foot-note').textContent =
    `돌파확률은 ${d.name}의 과거 일간 상방 변동폭을 현재 변동성 기준으로 표준화해 집계한 빈도입니다. `
    + '예측이 아니며, 개별 이벤트나 시장 충격은 반영하지 않습니다.';
}

(async function init() {
  const main = document.getElementById('main');
  if (!code) {
    main.innerHTML = '<div class="empty"><strong>종목이 지정되지 않았습니다</strong>'
      + '<div>상단 검색창에서 종목을 찾아보세요.</div></div>';
    return;
  }
  let d;
  try {
    d = await loadJSON(`data/stocks/${code}.json`);
  } catch {
    main.innerHTML = `<div class="empty"><strong>${code} 데이터를 찾을 수 없습니다</strong>`
      + '<div>분석 대상(코스피·코스닥 보통주)이 아니거나 상장 이력이 짧은 종목일 수 있습니다.</div></div>';
    return;
  }
  head(d);
  buildChart(d);
  periodCards(d);
  panels(d);
})();
