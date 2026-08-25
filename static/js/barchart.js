function createBarChart(data) {
  const margin = {top: 16, right: 30, bottom: 36, left: 90},
      width = 800 - margin.left - margin.right,
      height = 400 - margin.top - margin.bottom;

  const colors = {ShortVolume: "#e15759", LongVolume: "#4f5df4"};
  const volgroups = ["ShortVolume", "LongVolume"];
  const dates = data.map(d => d.Date);

  const svg = d3.create("svg")
      .attr("width", width + margin.left + margin.right)
      .attr("height", height + margin.top + margin.bottom)
      .attr("font-family", "Roboto, sans-serif");

  const chart = svg.append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

  const x = d3.scaleLinear()
      .domain([0, d3.max(data, d => d.TotalVolume)])
      .range([0, width]);

  const y = d3.scaleBand()
      .range([0, height])
      .domain(dates)
      .padding(0.25);

  const color = d3.scaleOrdinal().domain(volgroups).range(volgroups.map(k => colors[k]));

  // Light gridlines read as more contemporary than solid black axis
  // lines, and they make it easier to read a bar's value at a glance.
  chart.append("g")
      .attr("stroke", "#e3e5ea")
      .selectAll("line")
      .data(x.ticks(6))
      .join("line")
        .attr("x1", d => x(d))
        .attr("x2", d => x(d))
        .attr("y1", 0)
        .attr("y2", height);

  chart.append("g")
      .attr("transform", `translate(0,${height})`)
      .call(d3.axisBottom(x).ticks(6).tickFormat(d => `${(d / 1000000).toFixed(1)}M`))
      .call(g => g.select(".domain").remove())
      .call(g => g.selectAll("line").remove())
      .call(g => g.selectAll("text").attr("fill", "#6b7180").attr("font-size", 11));

  chart.append("g")
      .call(d3.axisLeft(y))
      .call(g => g.select(".domain").remove())
      .call(g => g.selectAll("line").remove())
      .call(g => g.selectAll("text").attr("fill", "#6b7180").attr("font-size", 11));

  const stackedData = d3.stack().keys(volgroups)(data);

  chart.append("g")
      .selectAll("g")
      .data(stackedData)
      .join("g")
        .attr("fill", d => color(d.key))
      .selectAll("rect")
      .data(d => d)
      .join("rect")
        .attr("y", d => y(d.data.Date))
        .attr("height", y.bandwidth())
        .attr("x", d => x(d[0]))
        .attr("width", d => x(d[1]) - x(d[0]));

  // Simple inline swatches instead of pulling in the d3-legend plugin
  // just for two colored squares.
  const legend = svg.append("g")
      .attr("transform", `translate(${margin.left}, ${height + margin.top + 28})`)
      .attr("font-size", 12);

  const legendItems = legend.selectAll("g")
      .data(volgroups)
      .join("g")
        .attr("transform", (d, i) => `translate(${i * 130}, 0)`);

  legendItems.append("rect")
      .attr("width", 11)
      .attr("height", 11)
      .attr("rx", 2)
      .attr("fill", d => color(d));

  legendItems.append("text")
      .attr("x", 18)
      .attr("y", 10)
      .attr("fill", "#1a1d29")
      .text(d => d === "ShortVolume" ? "Short Volume" : "Long Volume");

  return svg.node();
}

const renderJSONBarChart = (jsonData) => {
    oldBarChart = document.getElementById("svg_detail").childNodes[0]
    barchart = createBarChart(jsonData)

    if (typeof oldBarChart === 'undefined') document.getElementById("svg_detail").appendChild(barchart);
           else document.getElementById("svg_detail").replaceChild(barchart, oldBarChart);
}
