const form = document.querySelector("#query-form");
const symbolInput = document.querySelector("#symbol");
const costInput = document.querySelector("#cost");
const errorNode = document.querySelector("#error");
const resultNode = document.querySelector("#result");
const REQUEST_TIMEOUT_MS = 25000;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const symbol = symbolInput.value.trim().toUpperCase();
  const cost = costInput.value.trim();
  if (!symbol) {
    return;
  }

  symbolInput.value = symbol;
  setLoading(true);
  hideError();
  let timeoutId;

  try {
    const params = new URLSearchParams({ symbol });
    if (cost) {
      params.set("cost", cost);
    }
    const controller = new AbortController();
    timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const response = await fetch(`/api/analyze?${params.toString()}`, { signal: controller.signal });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "查詢失敗");
    }
    renderResult(payload);
  } catch (error) {
    resultNode.hidden = true;
    if (error.name === "AbortError") {
      showError("查詢逾時，官方資料來源回應較慢，請稍後再試。");
    } else {
      showError(error.message || "查詢失敗");
    }
  } finally {
    clearTimeout(timeoutId);
    setLoading(false);
  }
});

function renderResult(payload) {
  document.querySelector("#result-market").textContent = `${payload.market}｜資料日期 ${payload.dataDate}`;
  if (payload.meta?.cached) {
    document.querySelector("#result-market").textContent += `｜快取 ${payload.meta.cacheTtlSeconds} 秒`;
  }
  document.querySelector("#result-title").textContent = `${payload.symbol} ${payload.name}`;
  document.querySelector("#result-date").textContent = payload.dataDate;
  document.querySelector("#result-close").textContent = formatNumber(payload.latestClose);
  document.querySelector("#decision-label").textContent = "決策分數";
  document.querySelector("#decision-score").textContent = `${payload.decision.score}/${payload.decision.maxScore}`;
  document.querySelector("#decision-text").textContent =
    `${payload.decision.recommendation}｜${payload.decision.score >= payload.decision.entryThreshold ? "達進場門檻" : payload.decision.score >= payload.decision.watchThreshold ? "達觀察門檻" : "未達觀察門檻"}`;
  document.querySelector("#industry-group").textContent = payload.industry || payload.themeGroup || "待補資料";

  renderTags(payload.colorTags || []);
  renderChart(payload.chartSeries);

  document.querySelector("#ma-values").textContent =
    `MA5 ${formatNumber(payload.ma5)} / MA10 ${formatNumber(payload.ma10)} / MA20 ${formatNumber(payload.ma20)} / MA60 ${formatNumber(payload.ma60)} / MA120 ${formatNumber(payload.ma120)}`;
  document.querySelector("#ma-price").textContent =
    `股價與五日線：${payload.maAnalysis.priceAboveMa5 ? "站穩 MA5" : "跌破 MA5"}`;
  document.querySelector("#ma-alignment").textContent =
    `短中期排列：${payload.maAnalysis.bullishAlignment ? "MA5 > MA10 > MA20" : "未形成完整多頭排列"}`;
  document.querySelector("#ma-longtrend").textContent =
    `長線保護：MA60 ${payload.maAnalysis.ma60Trend}｜MA120 ${payload.maAnalysis.ma120Trend}`;
  document.querySelector("#ma-score").textContent = `均線分數：${payload.maAnalysis.score}/4`;

  document.querySelector("#kd-values").textContent = `K=${formatNumber(payload.k)} / D=${formatNumber(payload.d)}`;
  document.querySelector("#kd-direction").textContent = `KD 方向：${payload.kdDirection}`;
  document.querySelector("#kd-curve").textContent =
    `KD 轉折：${payload.kdCurve}｜低檔區 ${payload.kdAnalysis.isLowZone ? "是" : "否"}｜上彎 ${payload.kdAnalysis.isTurningUp ? "是" : "否"}`;
  document.querySelector("#kd-signal").textContent = `KD 滿足點：${payload.kdSignal}`;
  document.querySelector("#kd-score").textContent = `KD 訊號分數：${payload.kdAnalysis.score}/3`;

  document.querySelector("#macd-values").textContent =
    `DIF=${formatNumber(payload.dif)} / DEA=${formatNumber(payload.dea)} / OSC=${formatNumber(payload.osc)}`;
  document.querySelector("#macd-direction").textContent = `MACD 方向：${payload.macdDirection}`;
  document.querySelector("#macd-curve").textContent =
    `MACD 彎曲：${payload.macdCurve}｜交叉：${payload.macdSignal}｜綠柱縮短 ${payload.macdAnalysis.oscNegativeShrinking ? "是" : "否"}`;
  document.querySelector("#macd-axis").textContent =
    `MACD 零軸：${payload.macdZeroAxis}｜${payload.oscSign}｜零軸上方 ${payload.macdAnalysis.difAboveZero ? "是" : "否"}`;
  document.querySelector("#macd-score").textContent = `MACD 訊號分數：${payload.macdAnalysis.score}/3`;

  document.querySelector("#volume-values").textContent =
    `成交量 ${payload.latestVolume.toLocaleString()} / VMA5 ${formatNumber(payload.vma5)} / VMA20 ${formatNumber(payload.vma20)}`;
  document.querySelector("#volume-ratio").textContent =
    `量增倍率：${formatNumber(payload.volumeAnalysis.volumeRatio5)} 倍五日均量`;
  document.querySelector("#volume-breakout").textContent =
    `量能驗證：${payload.volumeAnalysis.isBreakout ? "量能已冒頭" : "量能未完全展開"}｜大於 VMA20 ${payload.volumeAnalysis.volumeAboveVma20 ? "是" : "否"}｜連三日增量 ${payload.volumeAnalysis.rollingUp3d ? "是" : "否"}｜無量過高 ${payload.volumeAnalysis.noVolumeHigh ? "是" : "否"}`;
  document.querySelector("#volume-score").textContent = `量能分數：${payload.volumeAnalysis.score}/3`;

  document.querySelector("#valuation-values").textContent =
    `PE ${formatMaybe(payload.valuation.pe)} / PB ${formatMaybe(payload.valuation.pb)} / 殖利率 ${formatMaybe(payload.valuation.dividendYield, "%")}`;
  document.querySelector("#revenue-values").textContent =
    `月營收 ${payload.revenue.monthLabel || "N/A"}：${formatMaybe(payload.revenue.revenue)}`;
  document.querySelector("#revenue-trend").textContent =
    `YoY ${formatMaybe(payload.revenue.yoy, "%")}｜MoM ${formatMaybe(payload.revenue.mom, "%")}`;
  document.querySelector("#revenue-base").textContent =
    `上月 ${formatMaybe(payload.revenue.previousRevenue)}｜去年同月 ${formatMaybe(payload.revenue.lastYearRevenue)}`;
  document.querySelector("#revenue-cumulative").textContent =
    `累計營收 ${formatMaybe(payload.revenue.cumulativeRevenue)}｜去年累計 ${formatMaybe(payload.revenue.cumulativeLastYearRevenue)}｜累計 YoY ${formatMaybe(payload.revenue.cumulativeYoy, "%")}`;
  document.querySelector("#revenue-note").textContent =
    payload.revenue.note ? `備註：${payload.revenue.note}` : "備註：無";

  document.querySelector("#chip-summary").textContent =
    `近 5 日合計 ${formatSigned(payload.institutional.total5d)} 股`;
  document.querySelector("#chip-flow").textContent =
    `外資 ${formatSigned(payload.institutional.foreign5d)}｜投信 ${formatSigned(payload.institutional.investment5d)}｜自營 ${formatSigned(payload.institutional.dealer5d)}｜${payload.institutional.streak}`;
  document.querySelector("#chip-concentration").textContent =
    `集中度代理：5日 ${formatMaybe(payload.chipFocus.concentration5d, "%")}｜10日 ${formatMaybe(payload.chipFocus.concentration10d, "%")}｜20日 ${formatMaybe(payload.chipFocus.concentration20d, "%")}｜${payload.chipFocus.concentrationView}`;
  document.querySelector("#chip-broker-status").textContent =
    `分點監控：${payload.chipFocus.brokerStatus}｜${payload.chipFocus.brokerNote}`;
  renderMiniList(
    document.querySelector("#chip-days"),
    (payload.institutional.recentDays || []).map((day) => ({
      title: day.tradeDate,
      subtitle: `外資 ${formatSigned(day.foreignNet)} / 投信 ${formatSigned(day.investmentNet)} / 自營 ${formatSigned(day.dealerNet)} / 合計 ${formatSigned(day.totalNet)}`,
    })),
  );

  document.querySelector("#theme-group").textContent = payload.themeGroup || "待判讀";
  document.querySelector("#theme-tags").textContent = `標籤：${(payload.themeTags || []).join(" / ") || "無"}`;
  document.querySelector("#peer-leader").textContent =
    `同族群領先股：${payload.peerComparison.leader || "暫無"}${payload.peerComparison.group ? `｜群組 ${payload.peerComparison.group}` : ""}`;
  renderMiniList(
    document.querySelector("#peer-members"),
    (payload.peerComparison.members || []).map((peer) => ({
      title: `${peer.symbol} ${peer.name}`,
      subtitle: `強度 ${peer.strengthScore}/2｜收盤 ${formatNumber(peer.latestClose)}`,
    })),
  );

  document.querySelector("#cost-summary").textContent =
    payload.costAnalysis.costBasis == null
      ? "未輸入成本價"
      : `成本 ${formatNumber(payload.costAnalysis.costBasis)}｜損益 ${formatSigned(payload.costAnalysis.pnl)}｜報酬 ${formatSigned(payload.costAnalysis.pnlPercent, "%")}`;
  document.querySelector("#cost-detail").textContent = payload.costAnalysis.status;
  document.querySelector("#cost-suggestion").textContent = payload.costAnalysis.suggestion;

  document.querySelector("#risk-summary").textContent =
    `ATR14 ${formatNumber(payload.riskAnalysis.atr14)}｜2 倍 ATR 停損 ${formatNumber(payload.riskAnalysis.atrStop)}`;
  document.querySelector("#risk-entry").textContent =
    `未進場參考：${payload.riskAnalysis.suggestedEntryLabel} ${formatNumber(payload.riskAnalysis.suggestedEntryPrice)}｜${payload.riskAnalysis.suggestedEntryReason}`;
  document.querySelector("#risk-support").textContent =
    `支撐：主要 ${formatMaybe(payload.riskAnalysis.primarySupport)}｜大量 K 低點 ${formatMaybe(payload.riskAnalysis.volumeSupport)}｜關鍵紅棒低點 ${formatMaybe(payload.riskAnalysis.bullishCandleSupport)}`;
  document.querySelector("#risk-resistance").textContent =
    `壓力：近一季高點 ${formatMaybe(payload.riskAnalysis.resistance)}｜判讀 ${payload.riskAnalysis.stance}`;
  document.querySelector("#risk-reward").textContent =
    payload.riskAnalysis.rewardRiskRatio == null
      ? `進場基準 ${formatNumber(payload.riskAnalysis.entryReference)}｜損益比 ${payload.riskAnalysis.ratioLabel}`
      : `進場 ${formatNumber(payload.riskAnalysis.entryReference)}｜目標 ${formatMaybe(payload.riskAnalysis.targetPrice)}｜停損 ${formatMaybe(payload.riskAnalysis.stopPrice)}｜損益比 ${formatNumber(payload.riskAnalysis.rewardRiskRatio)}`;
  document.querySelector("#risk-note").textContent =
    `${payload.riskAnalysis.ratioLabel}｜${payload.riskAnalysis.note}`;

  document.querySelector("#news-summary").textContent =
    `熱度 ${payload.news.heat}｜情緒 ${payload.news.sentiment}｜分數 ${payload.news.score}`;
  renderNewsList(document.querySelector("#news-items"), payload.news.items || []);

  document.querySelector("#signal-summary").textContent =
    `${payload.decision.recommendation}｜總分 ${payload.decision.score}/${payload.decision.maxScore}｜${payload.signalSummary}`;
  document.querySelector("#trade-narrative").textContent = payload.tradeNarrative;
  resultNode.hidden = false;
}

function renderTags(tags) {
  const node = document.querySelector("#color-tags");
  node.innerHTML = "";
  for (const tag of tags) {
    const pill = document.createElement("span");
    pill.className = `tag tone-${tag.tone || "cyan"}`;
    pill.textContent = tag.label;
    node.appendChild(pill);
  }
}

function renderMiniList(node, items) {
  node.innerHTML = "";
  if (!items.length) {
    node.textContent = "暫無資料";
    return;
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "mini-item";
    row.innerHTML = `<strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.subtitle)}</span>`;
    node.appendChild(row);
  }
}

function renderNewsList(node, items) {
  node.innerHTML = "";
  if (!items.length) {
    node.textContent = "暫無新聞資料";
    return;
  }
  for (const item of items.slice(0, 5)) {
    const row = document.createElement("a");
    row.className = "news-item";
    row.href = item.link;
    row.target = "_blank";
    row.rel = "noreferrer";
    row.innerHTML = `<strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.source)}｜${escapeHtml(item.published)}</span>`;
    node.appendChild(row);
  }
}

function renderChart(series) {
  const root = document.querySelector("#chart-root");
  if (!series || !series.closes || !series.closes.length) {
    root.innerHTML = "<p>暫無技術圖資料</p>";
    return;
  }

  const priceSvg = buildCandlestickPanel({
    title: "K線 / MA",
    width: 980,
    height: 300,
    series,
    lines: [
      { values: series.ma5, color: "#6bdcff" },
      { values: series.ma10, color: "#70f0d3" },
      { values: series.ma20, color: "#ff82c9" },
      { values: series.ma60, color: "#d8dce6" },
      { values: series.ma120, color: "#ff8c42" },
    ],
  });
  const volumeSvg = buildBarPanel({
    title: "VOL",
    subtitle: `VOL ${formatInteger(series.volumes.at(-1))} / VMA5 ${formatNumber(series.ma5Volume ?? averageTail(series.volumes, 5))} / VMA20 ${formatNumber(series.ma20Volume ?? averageTail(series.volumes, 20))}`,
    width: 980,
    height: 110,
    values: series.volumes,
    opens: series.opens,
    closes: series.closes,
  });
  const macdSvg = buildMacdPanel(series);
  const kdSvg = buildLinePanel({
    title: "KD",
    subtitle: `K ${formatNumber(series.k.at(-1))} / D ${formatNumber(series.d.at(-1))}`,
    width: 980,
    height: 140,
    lines: [
      { values: series.k, color: "#f7d26a" },
      { values: series.d, color: "#6bdcff" },
    ],
    fixedMin: 0,
    fixedMax: 100,
  });

  root.innerHTML = `${priceSvg}${volumeSvg}${macdSvg}${kdSvg}`;
  attachChartTooltip(root, series);
}

function buildLinePanel({ title, subtitle, width, height, lines, fixedMin, fixedMax }) {
  const values = lines.flatMap((line) => line.values.filter((value) => Number.isFinite(value)));
  const min = fixedMin ?? Math.min(...values);
  const max = fixedMax ?? Math.max(...values);
  const topOffset = subtitle ? 42 : 18;
  const innerWidth = width - 48;
  const innerHeight = height - (topOffset + 18);
  const toX = (index, total) => 24 + (index / Math.max(total - 1, 1)) * innerWidth;
  const toY = (value) => topOffset + innerHeight - ((value - min) / Math.max(max - min, 1e-6)) * innerHeight;

  let paths = "";
  for (const line of lines) {
    const d = line.values
      .map((value, index) => `${index === 0 ? "M" : "L"} ${toX(index, line.values.length).toFixed(2)} ${toY(value).toFixed(2)}`)
      .join(" ");
    paths += `<path d="${d}" fill="none" stroke="${line.color}" stroke-width="2" stroke-linecap="round" />`;
  }

  return `
    <svg class="chart-panel" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <text x="24" y="16" class="chart-title">${title}</text>
      <text x="24" y="32" class="chart-subtitle">${subtitle || ""}</text>
      <line x1="24" y1="${height - 18}" x2="${width - 24}" y2="${height - 18}" class="chart-axis" />
      <line x1="24" y1="${topOffset}" x2="24" y2="${height - 18}" class="chart-axis" />
      ${paths}
    </svg>
  `;
}

function buildCandlestickPanel({ title, width, height, series, lines }) {
  const priceValues = [...series.highs, ...series.lows, ...lines.flatMap((line) => line.values)];
  const min = Math.min(...priceValues);
  const max = Math.max(...priceValues);
  const innerWidth = width - 56;
  const innerHeight = height - 54;
  const toX = (index, total) => 30 + (index / Math.max(total - 1, 1)) * innerWidth;
  const toY = (value) => 30 + innerHeight - ((value - min) / Math.max(max - min, 1e-6)) * innerHeight;
  const candleWidth = Math.max(innerWidth / series.closes.length - 2, 2);

  const candles = series.closes
    .map((close, index) => {
      const open = series.opens[index];
      const high = series.highs[index];
      const low = series.lows[index];
      const x = toX(index, series.closes.length);
      const top = toY(Math.max(open, close));
      const bottom = toY(Math.min(open, close));
      const wickTop = toY(high);
      const wickBottom = toY(low);
      const color = close >= open ? "#ff4f4f" : "#33d17a";
      return `
        <line x1="${x.toFixed(2)}" y1="${wickTop.toFixed(2)}" x2="${x.toFixed(2)}" y2="${wickBottom.toFixed(2)}" stroke="${color}" stroke-width="1.2" />
        <rect x="${(x - candleWidth / 2).toFixed(2)}" y="${Math.min(top, bottom).toFixed(2)}" width="${candleWidth.toFixed(2)}" height="${Math.max(Math.abs(bottom - top), 1).toFixed(2)}" fill="${color}" />
      `;
    })
    .join("");

  let linePaths = "";
  for (const line of lines) {
    const d = line.values
      .map((value, index) => `${index === 0 ? "M" : "L"} ${toX(index, line.values.length).toFixed(2)} ${toY(value).toFixed(2)}`)
      .join(" ");
    linePaths += `<path d="${d}" fill="none" stroke="${line.color}" stroke-width="1.8" stroke-linecap="round" />`;
  }

  const latest = series.closes.length - 1;
  const summary = [
    `O ${formatNumber(series.opens[latest])}`,
    `H ${formatNumber(series.highs[latest])}`,
    `L ${formatNumber(series.lows[latest])}`,
    `C ${formatNumber(series.closes[latest])}`,
    `MA5 ${formatNumber(series.ma5[latest])}`,
    `MA20 ${formatNumber(series.ma20[latest])}`,
  ].join("   ");
  const latestX = toX(latest, series.closes.length);
  const latestY = toY(series.closes[latest]);
  const labelColor = series.closes[latest] >= series.opens[latest] ? "#ff4f4f" : "#33d17a";
  const priceLabelX = Math.min(latestX + 12, width - 76);
  const priceLabelY = Math.max(48, Math.min(latestY, height - 28));

  return `
    <svg
      class="chart-panel chart-price"
      viewBox="0 0 ${width} ${height}"
      preserveAspectRatio="none"
      data-viewbox-width="${width}"
      data-plot-left="30"
      data-plot-right="${(30 + innerWidth).toFixed(2)}"
    >
      <text x="24" y="18" class="chart-title">${title}</text>
      <text x="24" y="36" class="chart-subtitle">${summary}</text>
      <line x1="30" y1="${height - 24}" x2="${width - 18}" y2="${height - 24}" class="chart-axis" />
      <line x1="30" y1="30" x2="30" y2="${height - 24}" class="chart-axis" />
      ${candles}
      ${linePaths}
      <line x1="${latestX.toFixed(2)}" y1="${latestY.toFixed(2)}" x2="${priceLabelX.toFixed(2)}" y2="${priceLabelY.toFixed(2)}" stroke="${labelColor}" stroke-width="1.2" stroke-dasharray="3 3" />
      <rect x="${priceLabelX.toFixed(2)}" y="${(priceLabelY - 11).toFixed(2)}" width="56" height="18" rx="9" fill="${labelColor}" opacity="0.95" />
      <text x="${(priceLabelX + 28).toFixed(2)}" y="${(priceLabelY + 1).toFixed(2)}" class="chart-value-tag" text-anchor="middle">${formatNumber(series.closes[latest])}</text>
    </svg>
  `;
}

function buildBarPanel({ title, subtitle, width, height, values, opens, closes }) {
  const max = Math.max(...values, 1);
  const topOffset = subtitle ? 38 : 14;
  const innerWidth = width - 48;
  const innerHeight = height - (topOffset + 20);
  const barWidth = innerWidth / values.length;
  const bars = values
    .map((value, index) => {
      const barHeight = (value / max) * innerHeight;
      const x = 24 + index * barWidth;
      const y = topOffset + innerHeight - barHeight;
      const isUp = closes[index] >= opens[index];
      const fill = isUp ? "#ff4f4f" : "#33d17a";
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${Math.max(barWidth - 1, 1).toFixed(2)}" height="${barHeight.toFixed(2)}" fill="${fill}" opacity="0.78" />`;
    })
    .join("");
  return `
    <svg class="chart-panel chart-small" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <text x="24" y="15" class="chart-title">${title}</text>
      <text x="24" y="30" class="chart-subtitle">${subtitle || ""}</text>
      <line x1="24" y1="${height - 18}" x2="${width - 24}" y2="${height - 18}" class="chart-axis" />
      ${bars}
    </svg>
  `;
}

function buildMacdPanel(series) {
  const width = 980;
  const height = 150;
  const values = [...series.osc, ...series.dif, ...series.dea];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const topOffset = 40;
  const innerWidth = width - 48;
  const innerHeight = height - (topOffset + 18);
  const zeroY = topOffset + innerHeight - ((0 - min) / Math.max(max - min, 1e-6)) * innerHeight;
  const toX = (index, total) => 24 + (index / Math.max(total - 1, 1)) * innerWidth;
  const toY = (value) => topOffset + innerHeight - ((value - min) / Math.max(max - min, 1e-6)) * innerHeight;
  const barWidth = innerWidth / series.osc.length;

  const bars = series.osc
    .map((value, index) => {
      const x = 24 + index * barWidth;
      const y = value >= 0 ? toY(value) : zeroY;
      const h = Math.abs(toY(value) - zeroY);
      const fill = value >= 0 ? "#ff6b6b" : "#33d17a";
      return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${Math.max(barWidth - 1, 1).toFixed(2)}" height="${Math.max(h, 1).toFixed(2)}" fill="${fill}" opacity="0.8" />`;
    })
    .join("");
  const difPath = buildPath(series.dif, toX, toY);
  const deaPath = buildPath(series.dea, toX, toY);
  const subtitle = `DIF ${formatNumber(series.dif.at(-1))} / DEA ${formatNumber(series.dea.at(-1))} / OSC ${formatNumber(series.osc.at(-1))}`;

  return `
    <svg class="chart-panel" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <text x="24" y="16" class="chart-title">MACD</text>
      <text x="24" y="32" class="chart-subtitle">${subtitle}</text>
      <line x1="24" y1="${zeroY.toFixed(2)}" x2="${width - 24}" y2="${zeroY.toFixed(2)}" class="chart-axis" />
      ${bars}
      <path d="${difPath}" fill="none" stroke="#f7d26a" stroke-width="2" />
      <path d="${deaPath}" fill="none" stroke="#6bdcff" stroke-width="2" />
    </svg>
  `;
}

function buildPath(values, toX, toY) {
  return values
    .map((value, index) => `${index === 0 ? "M" : "L"} ${toX(index, values.length).toFixed(2)} ${toY(value).toFixed(2)}`)
    .join(" ");
}

function formatNumber(value) {
  return Number(value).toFixed(2);
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString();
}

function formatMaybe(value, suffix = "") {
  return value == null ? "N/A" : `${Number(value).toFixed(2)}${suffix}`;
}

function formatSigned(value, suffix = "") {
  if (value == null) {
    return "N/A";
  }
  const num = Number(value);
  return `${num >= 0 ? "+" : ""}${num.toFixed(2).replace(".00", "")}${suffix}`;
}

function showError(message) {
  errorNode.hidden = false;
  errorNode.textContent = message;
}

function hideError() {
  errorNode.hidden = true;
  errorNode.textContent = "";
}

function setLoading(isLoading) {
  const button = form.querySelector("button");
  button.disabled = isLoading;
  button.textContent = isLoading ? "查詢中..." : "查詢";
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function averageTail(values, size) {
  const tail = values.slice(-size);
  if (!tail.length) {
    return 0;
  }
  return tail.reduce((sum, value) => sum + value, 0) / tail.length;
}

function attachChartTooltip(root, series) {
  const pricePanel = root.querySelector(".chart-price");
  if (!pricePanel) {
    return;
  }
  let tooltip = root.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    root.appendChild(tooltip);
  }
  let guide = root.querySelector(".chart-guide");
  if (!guide) {
    guide = document.createElement("div");
    guide.className = "chart-guide";
    root.appendChild(guide);
  }

  const showTooltip = (event) => {
    const rect = pricePanel.getBoundingClientRect();
    const viewboxWidth = Number(pricePanel.dataset.viewboxWidth || 980);
    const plotLeft = Number(pricePanel.dataset.plotLeft || 30);
    const plotRight = Number(pricePanel.dataset.plotRight || viewboxWidth - 26);
    const relativeX = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
    const viewboxX = (relativeX / Math.max(rect.width, 1)) * viewboxWidth;
    const clampedViewboxX = Math.max(plotLeft, Math.min(viewboxX, plotRight));
    const normalized = (clampedViewboxX - plotLeft) / Math.max(plotRight - plotLeft, 1e-6);
    const index = Math.min(
      series.closes.length - 1,
      Math.max(0, Math.round(normalized * (series.closes.length - 1))),
    );
    const candleCenterViewboxX =
      plotLeft + (index / Math.max(series.closes.length - 1, 1)) * (plotRight - plotLeft);
    tooltip.hidden = false;
    guide.hidden = false;
    tooltip.innerHTML = `
      <strong>${escapeHtml(series.dates[index])}</strong>
      <span>O ${formatNumber(series.opens[index])} / H ${formatNumber(series.highs[index])} / L ${formatNumber(series.lows[index])} / C ${formatNumber(series.closes[index])}</span>
      <span>VOL ${formatInteger(series.volumes[index])} / MA5 ${formatNumber(series.ma5[index])} / MA20 ${formatNumber(series.ma20[index])}</span>
      <span>DIF ${formatNumber(series.dif[index])} / DEA ${formatNumber(series.dea[index])} / OSC ${formatNumber(series.osc[index])}</span>
      <span>K ${formatNumber(series.k[index])} / D ${formatNumber(series.d[index])}</span>
    `;
    const rootRect = root.getBoundingClientRect();
    const guideX = rect.left - rootRect.left + (candleCenterViewboxX / viewboxWidth) * rect.width;
    guide.style.left = `${guideX}px`;
    tooltip.style.left = `${Math.min(guideX + 16, rootRect.width - 240)}px`;
    tooltip.style.top = `18px`;
  };

  const hideTooltip = () => {
    tooltip.hidden = true;
    guide.hidden = true;
  };

  pricePanel.addEventListener("mousemove", showTooltip);
  pricePanel.addEventListener("mouseleave", hideTooltip);
  hideTooltip();
}
