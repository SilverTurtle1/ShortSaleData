



function createBarChart(data) {


// set the dimensions and margins of the graph
var margin = {top: 20, right: 30, bottom: 100, left: 90},
    width = 800 - margin.left - margin.right,
    height = 400 - margin.top - margin.bottom;

// create the svg object to the body of the page
var svg = d3.create("svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom);

svg.append("g")
    .attr("transform",
          "translate(" + margin.left + "," + margin.top + ")");

 const volgroups = ["ShortVolume", "LongVolume"]
 const dates = data.map(d => (d.Date))


  // Add X axis
  var x = d3.scaleLinear()
    .domain([0, d3.max(data, function(d) { return d.TotalVolume; })])
    .range([ 0, width]);

    var x_axis = d3.axisBottom(x)
        .tickFormat(x => `${(x/1000000).toFixed(1)}M`);

  svg.append("g")
    .attr("transform", "translate(70," + height + ")")
    .call(x_axis)
    .selectAll("text")
      .attr("transform", "translate(-10,0)rotate(-45)")
      .style("text-anchor", "end");

  // Y axis
  var y = d3.scaleBand()
    .range([ 0, height ])
    .domain(dates)
    .padding(.02);

  svg.append("g")
    .attr("transform", "translate(70,0)")//magic number, change it at will
    .call(d3.axisLeft(y))

//svg.append("text")
//   .attr("x", width/2)
//   .attr("y", 10)
//   .attr("text-anchor", "middle")
//   .style("font-size", "16px")
//   .text("Awesome Barchart");

  const color = d3.scaleOrdinal()
    .domain(volgroups)
    .range(['#377eb8', '#69b3a2'])

  const stackedData = d3.stack()
    .keys(volgroups)
    (data)


 svg.append("g")
    .selectAll("g")
    .data(stackedData)
    .join("g")
        .attr("fill", d => color(d.key))
        .selectAll("rect")
        .data(d => d)
        .join("rect")
            .attr("y", d => y(d.data.Date))
            .attr("height", Math.min(y.bandwidth(), 40) )
            .attr("transform", "translate(70,0)")
            .attr("x", x(0) )
            .attr("width", function(d) { return x(0); })

    // Animation
    svg.selectAll("rect")
      .transition()
      .duration(800)
      .attr("x", d => x(d[0]) )
      .attr("width", function(d) { return x(d[1]) - x(d[0]); })
      .delay(function(d,i){return(i*100)})

    var legend = d3.legendColor()
        .shape("path", d3.symbol().type(d3.symbolTriangle).size(100)())
        .shapePadding(20)
        .scale(color)
//        .orient("horizontal");
    svg.append("g")
        .attr("transform", "translate(70, 350)")
        .attr("class", "legendOrdinal")
        .call(legend);

    return Object.assign(svg.node());

}

const renderJSONBarChart = (jsonData) => {
    oldBarChart = document.getElementById("svg_detail").childNodes[0]
    barchart = createBarChart(jsonData)

    if (typeof oldBarChart === 'undefined') document.getElementById("svg_detail").appendChild(barchart);
           else document.getElementById("svg_detail").replaceChild(barchart, oldBarChart);
}