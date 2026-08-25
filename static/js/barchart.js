function createBarChart(data) {
  // Sorted chronologically (the /barchart response order isn't
  // guaranteed) so the line reads left-to-right as a proper time series.
  const sorted = [...data].sort((a, b) => parseChartDate(a.Date) - parseChartDate(b.Date));

  // % short is the metric this whole app is built around, so it gets
  // the precise encoding (a line against a 0-100% axis) instead of
  // being something you have to eyeball as a fraction of a stacked
  // bar's length. Volume stays visible as a secondary, lighter-weight
  // encoding (bars) rather than competing for the same axis.
  const margin = {top: 16, right: 46, bottom: 40, left: 40},
      width = 640 - margin.left - margin.right,
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
      .attr("width", 640)
      .attr("height", 340)
      .attr("font-family", "Roboto, sans-serif");

  const chart = svg.append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

  const x = d3.scalePoint()
      .domain(sorted.map(d => d.Date))
      .range([0, width])
      .padding(0.5);

  const yPct = d3.scaleLinear().domain([0, 100]).range([height, 0]);
  const yVol = d3.scaleLinear()
      .domain([0, d3.max(sorted, d => d.TotalVolume)]).nice()
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
      .call(d3.axisBottom(x))
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
      .call(d3.axisRight(yVol).ticks(4).tickFormat(d => `${(d / 1000000).toFixed(0)}M`))
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

const renderJSONBarChart = (jsonData) => {
    oldBarChart = document.getElementById("svg_detail").childNodes[0]
    barchart = createBarChart(jsonData)

    if (typeof oldBarChart === 'undefined') document.getElementById("svg_detail").appendChild(barchart);
           else document.getElementById("svg_detail").replaceChild(barchart, oldBarChart);
}
