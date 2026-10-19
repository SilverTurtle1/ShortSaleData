function createBarChart(data) {
  // Sorted chronologically (the /barchart response order isn't
  // guaranteed) so the line reads left-to-right as a proper time series.
  const sorted = [...data].sort((a, b) => parseChartDate(a.Date) - parseChartDate(b.Date));

  // % short is the metric this whole app is built around, so it gets
  // the precise encoding (a line against a 0-100% axis) instead of
  // being something you have to eyeball as a fraction of a stacked
  // bar's length. Volume stays visible as a secondary, lighter-weight
  // encoding (bars) rather than competing for the same axis.
  const margin = {top: 16, right: 46, bottom: 40, left: 40};
  // Comfortable spacing per data point before date labels start crowding
  // or overlapping -- a 7-day treemap range and a 30-day report
  // drill-down both need to stay readable, so this scales with however
  // many points there actually are instead of a fixed width.
  const pointSpacing = 32;
  const outerWidth = Math.max(640, sorted.length * pointSpacing + margin.left + margin.right);
  const width = outerWidth - margin.left - margin.right,
      height = 340 - margin.top - margin.bottom - 32; // reserve room for the legend

  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  // Matches the treemap's own high-short% blue in each theme (see
  // treemapColorRangeLight/Dark in treemap.js) so "short" reads as the
  // same color everywhere in the app, in both themes.
  const shortColor = dark ? "#3fa9f5" : "#1984c5";
  const volumeColor = "var(--border)";
  const gridColor = dark ? "#20222b" : "#eef0f3";
  const refLineColor = dark ? "#3a3d47" : "#c7cad1";

  const svg = d3.create("svg")
      .attr("width", outerWidth)
      .attr("height", 340)
      .attr("font-family", "Roboto, sans-serif");

  const chart = svg.append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

  const x = d3.scalePoint()
      .domain(sorted.map(d => d.Date))
      .range([0, width])
      .padding(0.5);

  const yPct = d3.scaleLinear().domain([0, 100]).range([height, 0]);
  // Log, not linear -- this chart's whole purpose is showing symbols
  // with an unusual volume spike, so the flagged day is routinely an
  // order of magnitude (or more) above the symbol's normal days. On a
  // linear scale that outlier stretches the axis until every other
  // day's bar rounds down to an invisible sliver.
  const yVol = d3.scaleLog()
      .domain([Math.max(1, d3.min(sorted, d => d.TotalVolume)), d3.max(sorted, d => d.TotalVolume)])
      .range([height, 0]);

  const pctOf = d => (d.ShortVolume / d.TotalVolume) * 100;

  // Gridlines at fixed 25% steps so the 50% split point is always
  // directly labeled, not just implied.
  chart.append("g")
      .attr("stroke", gridColor)
      .selectAll("line")
      .data([0, 25, 50, 75, 100])
      .join("line")
        .attr("x1", 0).attr("x2", width)
        .attr("y1", d => yPct(d)).attr("y2", d => yPct(d));

  chart.append("line")
      .attr("x1", 0).attr("x2", width)
      .attr("y1", yPct(50)).attr("y2", yPct(50))
      .attr("stroke", refLineColor)
      .attr("stroke-dasharray", "3,3");

  // Total volume, as muted background bars behind the line -- present
  // and comparable, but visually secondary to the % short trend.
  const barWidth = Math.min(28, x.step() * 0.5);
  chart.append("g")
      .selectAll("rect")
      .data(sorted)
      .join("rect")
        .attr("x", d => x(d.Date) - barWidth / 2)
        .attr("y", d => yVol(d.TotalVolume))
        .attr("width", barWidth)
        .attr("height", d => height - yVol(d.TotalVolume))
        .attr("fill", volumeColor);

  chart.append("path")
      .datum(sorted)
      .attr("fill", "none")
      .attr("stroke", shortColor)
      .attr("stroke-width", 2)
      .attr("d", d3.line().x(d => x(d.Date)).y(d => yPct(pctOf(d))));

  chart.selectAll("circle")
      .data(sorted)
      .join("circle")
        .attr("cx", d => x(d.Date))
        .attr("cy", d => yPct(pctOf(d)))
        .attr("r", 3.5)
        .attr("fill", shortColor);

  chart.selectAll("text.pct-label")
      .data(sorted)
      .join("text")
        .attr("class", "pct-label")
        .attr("x", d => x(d.Date))
        .attr("y", d => yPct(pctOf(d)) - 9)
        .attr("text-anchor", "middle")
        .attr("font-size", 11)
        .attr("fill", shortColor)
        .text(d => `${pctOf(d).toFixed(0)}%`);

  chart.append("g")
      .attr("transform", `translate(0,${height})`)
      .call(d3.axisBottom(x).tickFormat(dateTickFormat(sorted)))
      .call(g => g.select(".domain").remove())
      .call(g => g.selectAll("line").remove())
      .call(g => g.selectAll("text").attr("fill", "var(--text-muted)").attr("font-size", 10));

  chart.append("g")
      .call(d3.axisLeft(yPct).tickValues([0, 25, 50, 75, 100]).tickFormat(d => d + "%"))
      .call(g => g.select(".domain").remove())
      .call(g => g.selectAll("line").remove())
      .call(g => g.selectAll("text").attr("fill", shortColor).attr("font-size", 10));

  chart.append("g")
      .attr("transform", `translate(${width},0)`)
      // Log scale ticks span a much wider range of magnitudes than a
      // linear axis would (e.g. 200K up to 300M on the same axis) --
      // a fixed "always millions" format rounds every sub-1M tick down
      // to a meaningless "0M".
      .call(d3.axisRight(yVol).ticks(4).tickFormat(d => d >= 1000000 ? `${(d / 1000000).toFixed(0)}M` : `${(d / 1000).toFixed(0)}K`))
      .call(g => g.select(".domain").remove())
      .call(g => g.selectAll("line").remove())
      .call(g => g.selectAll("text").attr("fill", "var(--text-faint)").attr("font-size", 10));

  const legendItems = [
    {label: "% Short volume", swatch: "line", color: shortColor},
    {label: "Total volume", swatch: "square", color: volumeColor},
  ];

  const legend = svg.append("g")
      .attr("transform", `translate(${margin.left}, ${height + margin.top + 28})`)
      .attr("font-size", 12);

  const legendGroups = legend.selectAll("g")
      .data(legendItems)
      .join("g")
        .attr("transform", (d, i) => `translate(${i * 150}, 0)`);

  legendGroups.filter(d => d.swatch === "line")
      .append("line")
      .attr("x1", 0).attr("x2", 14).attr("y1", 5).attr("y2", 5)
      .attr("stroke", d => d.color)
      .attr("stroke-width", 2);

  legendGroups.filter(d => d.swatch === "square")
      .append("rect")
      .attr("width", 11).attr("height", 11).attr("rx", 2)
      .attr("fill", d => d.color);

  legendGroups.append("text")
      .attr("x", 20)
      .attr("y", 10)
      .attr("fill", "var(--text)")
      .text(d => d.label);

  return svg.node();
}

function parseChartDate(mmddyyyy) {
  const [m, d, y] = mmddyyyy.split("-").map(Number);
  return new Date(y, m - 1, d);
}

// Repeating the year on every tick ("08-19-2026", "08-20-2026", ...) is
// redundant noise when the whole range sits in one calendar year, and
// with more than a handful of dates it's what actually causes the
// labels to overlap into an unreadable smear. Drop the year entirely
// when it doesn't vary across the range; when it does, show it only at
// the tick(s) where it changes rather than on every single label.
//
// Numeric M/D rather than "Mon DD" -- narrower text at the same spacing
// leaves more of a gap between adjacent labels before they touch, on
// top of the point spacing itself.
function dateTickFormat(sortedRows) {
  const years = sortedRows.map(d => parseChartDate(d.Date).getFullYear());
  const spansMultipleYears = new Set(years).size > 1;
  let lastYear = null;

  return function(dateStr) {
    const date = parseChartDate(dateStr);
    const monthDay = `${date.getMonth() + 1}/${date.getDate()}`;
    if (!spansMultipleYears) return monthDay;

    const year = date.getFullYear();
    const showYear = year !== lastYear;
    lastYear = year;
    return showYear ? `${monthDay}/${String(year).slice(2)}` : monthDay;
  };
}

const renderJSONBarChart = (jsonData) => {
    oldBarChart = document.getElementById("svg_detail").childNodes[0]
    barchart = createBarChart(jsonData)

    if (typeof oldBarChart === 'undefined') document.getElementById("svg_detail").appendChild(barchart);
           else document.getElementById("svg_detail").replaceChild(barchart, oldBarChart);
}

// Rasterizes the rendered chart (plus a title line) to a PNG. The chart
// is styled with CSS variables (var(--border), var(--text-muted), ...),
// which don't exist once the SVG is serialized into a standalone image,
// so they're resolved to the current theme's concrete colors first --
// the copied image matches whatever theme is on screen.
function chartToPngBlob(svgEl, title) {
  const rootStyle = getComputedStyle(document.documentElement);
  const resolveVars = value => value.replace(/var\((--[\w-]+)\)/g,
      (_, name) => rootStyle.getPropertyValue(name).trim());

  const clone = svgEl.cloneNode(true);
  [clone, ...clone.querySelectorAll("*")].forEach(el => {
    for (const attr of Array.from(el.attributes)) {
      if (attr.value.includes("var(")) el.setAttribute(attr.name, resolveVars(attr.value));
    }
  });
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");

  const width = Number(svgEl.getAttribute("width"));
  const height = Number(svgEl.getAttribute("height"));
  const headerHeight = title ? 36 : 12;
  const scale = 2; // retina-sharp when pasted into a doc or chat
  const bg = rootStyle.getPropertyValue("--panel-bg").trim() || "#ffffff";
  const textColor = rootStyle.getPropertyValue("--text").trim() || "#000000";

  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = (height + headerHeight) * scale;
      const ctx = canvas.getContext("2d");
      ctx.scale(scale, scale);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, width, height + headerHeight);
      if (title) {
        ctx.fillStyle = textColor;
        ctx.font = "500 15px Roboto, Helvetica, Arial, sans-serif";
        ctx.textBaseline = "middle";
        ctx.fillText(title, 40, headerHeight / 2 + 2);
      }
      ctx.drawImage(img, 0, headerHeight, width, height);
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error("PNG encoding failed")), "image/png");
    };
    img.onerror = () => reject(new Error("Chart image failed to load"));
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
  });
}

// Wired to the modal's copy button. Copies the chart image to the
// clipboard; where the async Clipboard API isn't available (older
// browsers, or a non-HTTPS origin), downloads the PNG instead.
function copyChartImage(button) {
  const svgEl = document.querySelector("#svg_detail svg");
  if (!svgEl) return;

  const subtitle = document.getElementById("modal-subtitle");
  const title = `${subtitle ? subtitle.textContent : ""} \u2014 Daily Off-Exchange Volume`.replace(/^ \u2014 /, "");
  const blobPromise = chartToPngBlob(svgEl, title);
  const original = button.innerHTML;
  const flash = (html, tip) => {
    button.innerHTML = html;
    button.title = tip;
    setTimeout(() => { button.innerHTML = original; button.title = "Copy chart as image"; }, 1500);
  };

  const canCopy = navigator.clipboard && navigator.clipboard.write && typeof ClipboardItem !== "undefined";
  if (canCopy) {
    // Handing ClipboardItem the promise (not the resolved blob) keeps
    // Safari happy -- it requires write() to be called synchronously
    // inside the click handler.
    navigator.clipboard.write([new ClipboardItem({"image/png": blobPromise})])
        .then(() => flash("\u2713", "Copied!"))
        .catch(() => flash("!", "Copy failed"));
  } else {
    blobPromise.then(blob => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "off-exchange-volume.png";
      a.click();
      URL.revokeObjectURL(a.href);
      flash("\u2713", "Downloaded");
    }).catch(() => flash("!", "Copy failed"));
  }
}
