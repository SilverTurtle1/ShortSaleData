

// Parse the Data
//function createBarchart(data, {

//d3.csv("https://raw.githubusercontent.com/holtzy/data_to_viz/master/Example_dataset/7_OneCatOneNum_header.csv").then(function(data) {

function createBarChart(data) {

    // format the data
//  console.log(data)
//  data.forEach(function(d) {
//    d.value = +d.value;
//  });

//const svg = d3.create("svg")
//      .attr("viewBox", [-marginLeft, -marginTop, width, height])
//      .attr("width", width)
//      .attr("height", height)
//      .attr("style", "max-width: 100%; height: auto; height: intrinsic;")
//      .attr("font-family", "work sans")
//      .attr("font-size", 12)
//      .attr("font-weight", "light")
//      .attr("fill", "white");

// set the dimensions and margins of the graph
var margin = {top: 20, right: 30, bottom: 40, left: 90},
    width = 800 - margin.left - margin.right,
    height = 400 - margin.top - margin.bottom;

// create the svg object to the body of the page
var svg = d3.create("svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom);

svg.append("g")
    .attr("transform",
          "translate(" + margin.left + "," + margin.top + ")");


  // Add X axis
  var x = d3.scaleLinear()
    .domain([0, d3.max(data, function(d) { return d.TotalVolume; })])
    .range([ 0, width]);

  svg.append("g")
    .attr("transform", "translate(0," + height + ")")
    .call(d3.axisBottom(x))
    .selectAll("text")
      .attr("transform", "translate(-10,0)rotate(-45)")
      .style("text-anchor", "end");

  // Y axis
  var y = d3.scaleBand()
    .range([ 0, height ])
    .domain(data.map(function(d) { return d.Date; }))
    .padding(.1);

  svg.append("g")
//    .call(d3.axisLeft(y))
    .attr("transform", "translate(70,0)")//magic number, change it at will
    .call(d3.axisLeft(y))

//svg.append("text")
//   .attr("x", width/2)
//   .attr("y", 10)
//   .attr("text-anchor", "middle")
//   .style("font-size", "16px")
//   .text("Awesome Barchart");


// // Scale the range of the data in the domains
//  x.domain(data.map(function(d) { return d.Country; }));
//  y.domain([0, d3.max(data, function(d) { return d.value; })]);


  //Bars
  svg.selectAll("myRect")
    .data(data)
    .enter()
    .append("rect")
    .attr("x", x(0) )
    .attr("y", function(d) { return y(d.Date); })
//    .attr("width", function(d) { return x(d.TotalVolume); })
    .attr("width", function(d) { return x(0); })
    .attr("height", Math.min(y.bandwidth(), 40) )
    .attr("fill", "#69b3a2")
    .attr("transform", "translate(70,0)")

    // Animation
    svg.selectAll("rect")
      .transition()
      .duration(800)
      .attr("x", function(d) { return y(d.Value); })
      .attr("width", function(d) { return x(d.TotalVolume); })
      .delay(function(d,i){return(i*100)})



    // .attr("x", function(d) { return x(d.Country); })
    // .attr("y", function(d) { return y(d.Value); })
    // .attr("width", x.bandwidth())
    // .attr("height", function(d) { return height - y(d.Value); })
    // .attr("fill", "#69b3a2")
    return Object.assign(svg.node());

}

const renderJSONBarChart = (jsonData) => {
    oldBarChart = document.getElementById("svg_detail").childNodes[0]
    barchart = createBarChart(jsonData)

    if (typeof oldBarChart === 'undefined') document.getElementById("svg_detail").appendChild(barchart);
           else document.getElementById("svg_detail").replaceChild(barchart, oldBarChart);
}