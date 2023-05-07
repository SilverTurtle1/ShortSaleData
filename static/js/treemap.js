// Copyright 2021 Observable, Inc.
// Released under the ISC license.
// https://observablehq.com/@d3/treemap
var treemap
var Grp
var rectColor = d3.local();
//#7acc33 - bright green
//#3d8c40 - dull green
//#7a221b - dull red
//#f44336 - bright red

const percentColors = [ '#7acc33 ', '#3d8c40', '#f44336', '#7a221b ' ]
const treemapColorRange = ["#1984c5", "#22a7f0", "#63bff0", "#a7d5ed", "#e2e2e2", "#e1a692", "#de6e56", "#e14b31", "#c23728"]
const treemapRange = [0.9,0.8,0.7,0.6,0.5,0.4,0.3,0.2,0.1]

function shadeColor(color, percent) {
          var R = parseInt(color.substring(1,3),16);
          var G = parseInt(color.substring(3,5),16);
          var B = parseInt(color.substring(5,7),16);

          R = parseInt(R * (100 + percent) / 100);
          G = parseInt(G * (100 + percent) / 100);
          B = parseInt(B * (100 + percent) / 100);

          R = (R<255)?R:255;
          G = (G<255)?G:255;
          B = (B<255)?B:255;

          var RR = ((R.toString(16).length==1)?"0"+R.toString(16):R.toString(16));
          var GG = ((G.toString(16).length==1)?"0"+G.toString(16):G.toString(16));
          var BB = ((B.toString(16).length==1)?"0"+B.toString(16):B.toString(16));

          return "#"+RR+GG+BB;
      }

function createTreemap(data, { // data is either tabular (array of objects) or hierarchy (nested objects)
  path, // as an alternative to id and parentId, returns an array identifier, imputing internal nodes
  id = Array.isArray(data) ? d => d.id : null, // if tabular data, given a d in data, returns a unique identifier (string)
  parentId = Array.isArray(data) ? d => d.parentId : null, // if tabular data, given a node d, returns its parent’s identifier
  children, // if hierarchical data, given a d in data, returns its children
  size, // given a node d, returns a quantitative value (for area encoding; null for count)
  value, // given a node d, returns a quantitative value attribute (for area encoding; null for count)
  gain, // percent gain through selected time period
  sort = (a, b) => d3.descending(a.value, b.value), // how to sort nodes prior to layout
  label, // given a leaf node d, returns the name to display on the rectangle
  group, // given a leaf node d, returns a categorical value (for color encoding)
  title, // given a leaf node d, returns its hover text
  link, // given a leaf node d, its link (if any)
  linkTarget = "_blank", // the target attribute for links (if any)
  tile = d3.treemapBinary, // treemap strategy
  width = 640, // outer width, in pixels
  height = 400, // outer height, in pixels
  margin = 0, // shorthand for margins
  marginTop = margin, // top margin, in pixels
  marginRight = margin, // right margin, in pixels
  marginBottom = margin, // bottom margin, in pixels
  marginLeft = margin, // left margin, in pixels
  padding = 2, // shorthand for inner and outer padding
  paddingInner = padding, // to separate a node from its adjacent siblings
  paddingOuter = padding, // shorthand for top, right, bottom, and left padding
  paddingTop = paddingOuter, // to separate a node’s top edge from its children
  paddingRight = paddingOuter, // to separate a node’s right edge from its children
  paddingBottom = paddingOuter, // to separate a node’s bottom edge from its children
  paddingLeft = paddingOuter, // to separate a node’s left edge from its children
  round = true, // whether to round to exact pixels
  colors = d3.schemeTableau10, // array of colors
  zDomain, // array of values for the color scale
  fill = "#ccc", // fill for node rects (if no group color encoding)
  fillOpacity = group == null ? null : 0.6, // fill opacity for node rects
  stroke, // stroke for node rects
  strokeWidth, // stroke width for node rects
  strokeOpacity, // stroke opacity for node rects
  strokeLinejoin, // stroke line join for node rects
} = {}) {

  // If id and parentId options are specified, or the path option, use d3.stratify
  // to convert tabular data to a hierarchy; otherwise we assume that the data is
  // specified as an object {children} with nested objects (a.k.a. the “flare.json”
  // format), and use d3.hierarchy.
//  console.log("In CreateTreemap")

  const root = path != null ? d3.stratify().path(path)(data)
      : id != null || parentId != null ? d3.stratify().id(id).parentId(parentId)(data)
      : d3.hierarchy(data, children);
//    console.log("root")
//    console.log(root)
    var dataScale = d3.scaleLog()
    .domain([d3.min(data, function(d){return d.size}),
         d3.max(data, function(d){return d.size})]);


    var percentRange = (data, function(d) {
        shortPercent = d.value >= 0.6 ? "strong buy" : d.value >= 0.45 ? "buy" : d.value <= 0.30 ? "strong sell" : "sell"
        return shortPercent
    })


    dataScale.range([0,100]); //here you can choose a hard coded a

  // Compute the size of internal nodes by aggregating from the leaves.
  size == null ? root.count() : root.sum(d => Math.max(0, dataScale(d?.size)));

  // Prior to sorting, if a group channel is specified, construct an ordinal color scale.
  const leaves = root.leaves();
//  console.log(root)
//  const G = group == null ? null : leaves.map(d => group(d.data, d));
   Grp = group == null ? null : leaves.map(d => value(d.data, d));



//  if (zDomain === undefined) zDomain = Grp;
//  zDomain = new d3.InternSet(zDomain);
  const color = group == null ? null : (
    d3.scaleLinear()
//        .domain(["strong buy", "buy", "strong sell", "sell"])
        .domain(treemapRange)
        .range(treemapColorRange)
  );


  // prepare a color scale
//  var color = d3.scaleOrdinal()
//    .domain(["boss1", "boss2", "boss3"])
//    .range([ "#402D54", "#D18975", "#8FD175"])

  // Compute labels and titles.
  const L = label == null ? null : leaves.map(d => label(d.data, d));
  const T = title === undefined ? L : title == null ? null : leaves.map(d => title(d.data, d));
//  const R = gain === undefined ? L : gain == null ? null : leaves.map(d => gain(d.data, d));


  // Sort the leaves (typically by descending value for a pleasing layout).
  if (sort != null) root.sort(sort);

  // Compute the treemap layout.
  d3.treemap()
      .tile(tile)
      .size([width - marginLeft - marginRight, height - marginTop - marginBottom])
      .paddingInner(paddingInner)
      .paddingTop(paddingTop)
      .paddingRight(paddingRight)
      .paddingBottom(paddingBottom)
      .paddingLeft(paddingLeft)
      .round(round)
    (root);

  const svg = d3.create("svg")
      .attr("viewBox", [-marginLeft, -marginTop, width, height])
      .attr("width", width)
      .attr("height", height)
      .attr("style", "max-width: 100%; height: auto; height: intrinsic;")
      .attr("font-family", "work sans")
      .attr("font-size", 12)
      .attr("font-weight", "light")
      .attr("fill", "white");

  const node = svg.selectAll("a")
    .data(leaves)
    .join("a")
      .attr("xlink:href", link == null ? null : (d, i) => link(d.data, d))
      .attr("target", link == null ? null : linkTarget)
      .attr("transform", d => `translate(${d.x0},${d.y0})`);

  // Add one dot in the legend for each name.
//    svg.selectAll("mydots")
//      .data(treemapRange)
//      .enter()
//      .append("circle")
//        .attr("cx", 1100)
//        .attr("cy", function(d,i){ return 100 + i*25}) // 100 is where the first dot appears. 25 is the distance between dots
//        .attr("r", 7)
//        .style("fill", function(d){ return color(d)})

  node.append("rect")
//      .attr("fill", color ? (d, i) => color(G[i]) : fill)
      .attr("fill", color ? function(d, i) {
           return color(Grp[i]);
       } : fill)
      .attr("fill-opacity", fillOpacity)
      .attr("stroke", stroke)
      .attr("stroke-width", strokeWidth)
      .attr("stroke-opacity", strokeOpacity)
      .attr("stroke-linejoin", strokeLinejoin)
      .attr("width", d => d.x1 - d.x0)
      .attr("height", d => d.y1 - d.y0)
      .on("mouseover", function(d, i) {
        rectColor.set(this, d3.select(this).attr("fill"));
        d3.select(this).attr("fill", shadeColor(d3.select(this).attr("fill"), -15));
       })
       .on("mouseout", function(d, i) {
        var oldColor = rectColor.get(this)
        d3.select(this).attr("fill", oldColor);
       });
//       .each(function(d) { previousData.set(this, d) });




  if (T) {
    node.append("title").text((d, i) => T[i]);
  }

//  if (R) {
//    node.append("gain").text((d, i) => R[i]);
//  }

  if (L) {
    // A unique identifier for clip paths (to avoid conflicts).
    const uid = `O-${Math.random().toString(16).slice(2)}`;

    node.append("clipPath")
       .attr("id", (d, i) => `${uid}-clip-${i}`)
     .append("rect")
       .attr("width", d => d.x1 - d.x0)
       .attr("height", d => d.y1 - d.y0);

    node.append("text")

        .attr("clip-path", (d, i) => `url(${new URL(`#${uid}-clip-${i}`, location)})`)
        .selectAll("tspan")
        .data((d, i) => `${L[i]}`.split(/\n/g))
        .join("tspan")
//        .attr("text-anchor", (d, i, D) => i === D.length - 1 ? "middle": "middle");
        .attr("x", function (d, i, D) {
          const parentData = d3.select(this.parentNode).datum();
          var ctrPos = (parentData.x1 - parentData.x0) / 2;
          return i === D.length ? ctrPos : 3;
        })
        .attr("y", function (d, i, D) {
          const parentData = d3.select(this.parentNode).datum();
          var ctrPos = (parentData.y1 - parentData.y0) / 2;
          if (i == D.length - 2) return `${1.1 + i * 0.9}em`
          else return `${1 + 1.1 + i * 0.9}em`
        })
//        .attr("y", (d, i, D) => `${(i === D.length - 1) * 0.3 + 1.1 + i * 0.9}em`)
//        .attr("fill-opacity", (d, i, D) => i === D.length - 1 ? 0.7 : null)
        .attr("fill-opacity", (d, i, D) => i === D.length - 1 ? 0.7 : null)
        .text((d, i, D) => i === D.length - 1 ? parseFloat(d*100).toFixed(0)+"%" : d)
        .attr("font-size", (d, i, D) => i === D.length - 2 ? 16: 12)
        .style("fill", (d, i, D) => i === D.length - 1 ? "black": "black");




  }

  return Object.assign(svg.node(), {scales: {color}});
}

const renderTreeMap = (filepath) => {
    console.log("index.html JS Begin")
    oldtreemap = document.getElementById("svg_container").childNodes[0]
    console.log("Before createTreemap, treemap = " + oldtreemap)

    d3.csv(filepath)
        .then(function(data) {
    //       console.log("Loading CSV via D3 sending data to Treemap function")
//           console.log(data)
            treemap = createTreemap(data, {
                path: d => d.name.replace(/\./g, "/"), // e.g., "flare/animate/Easing
                size: d => d?.size, // size of each node (file); null for internal nodes (folders)
                value: d => d?.value, // value attribute of each node (file); null for internal nodes (folders)
                group: d => d.name.split(".")[0], // e.g., "animate" in "flare.animate.Easing"; for color
            <!--    label: (d, n) => [...d.name.split(".").pop().split(/(?=[A-Z][a-z])/g), n.value.toLocaleString("en"), d?.value].join("\n"),-->
                label: (d, n) => [...d.name.split(".").pop().split(/(?=[A-Z][a-z])/g), d?.value].join("\n"),
                title: (d, n) => `${d.name}\n${n.value.toLocaleString("en")}`, // text to show on hover
            <!--    link: (d, n) => `https://github.com/prefuse/Flare/blob/master/flare/src${n.id}.as`,-->
                tile: d3.treemapBinary,
                width: 1152,
                height: 1152
           })
           console.log("Built Treemap")
           console.log("Treemap =")
           console.log(treemap)
           if (typeof oldtreemap === 'undefined') document.getElementById("svg_container").appendChild(treemap);
           else document.getElementById("svg_container").replaceChild(treemap, oldtreemap);

//           document.getElementById("svg_container").appendChild(treemap);
    });
}


const renderJSONTreeMap = (jsonData) => {
//    console.log("In JSON Treemap")
//       console.log(jsonData)
    oldtreemap = document.getElementById("svg_container").childNodes[0]
//    d3.json(jsonData)
//        .then(function(data) {
//           console.log(data)
            treemap = createTreemap(jsonData, {
                path: d => d.name.replace(/\./g, "/"),
                size: d => d?.size, // size of each node (file); null for internal nodes (folders)
                value: d => d?.value, // value attribute of each node (file); null for internal nodes (folders)
                gain: d=> d?.gain,
                group: d => d.name.split(".")[0], // e.g., "animate" in "flare.animate.Easing"; for color
            <!--    label: (d, n) => [...d.name.split(".").pop().split(/(?=[A-Z][a-z])/g), n.value.toLocaleString("en"), d?.value].join("\n"),-->
                label: (d, n) => [...d.name.split(".").pop().split(/(?=[A-Z][a-z])/g), d?.value].join("\n"),
                title: (d, n) => `ETF: ${d.name.split(".")[0]}\n% Short: ${parseFloat(d.value.toLocaleString("en")*100).toFixed(0)+"%"}\nVolume: ${d.size.toLocaleString("en")}\n% Return: ${parseFloat(d.gain*100).toFixed(1)+"%"}`, // text to show on hover
            <!--    link: (d, n) => `https://github.com/prefuse/Flare/blob/master/flare/src${n.id}.as`,-->
                tile: d3.treemapBinary,
                width: 1100,
                height: 900
           })
//           console.log("Built JSON Treemap")
//           console.log("JSON Treemap =")
//           console.log(treemap)
           if (typeof oldtreemap === 'undefined') document.getElementById("svg_container").appendChild(treemap);
           else document.getElementById("svg_container").replaceChild(treemap, oldtreemap);

//           document.getElementById("svg_container").appendChild(treemap);
//    });
}
