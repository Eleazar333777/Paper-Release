// chart.js - Enhanced version with multiple chart types and improved visualization
document.addEventListener("DOMContentLoaded", async () => {
  const token = localStorage.getItem("token");
  const chartError = document.getElementById("chartError");
  let chartInstance = null;
  let allData = [];

//  if (!token) {
  //  window.location.href = "login.html";
   // return;
 // }

  // Register Chart.js zoom plugin
  Chart.register(ChartZoom);

  const xSelect = document.getElementById("x-axis-select");
  const ySelect = document.getElementById("y-axis-select");
  const chartTypeSelect = document.getElementById("chartTypeSelect");
  const bubbleSizeSelect = document.getElementById("bubble-size-select");
  const logToggle = document.getElementById("logScaleToggle");
  const showTrendLine = document.getElementById("showTrendLine");
  const compareContainer = document.getElementById("compareMembranesContainer");
  const filterMembrane = document.getElementById("filterMembrane");
  const filterPFAS = document.getElementById("filterPFAS");
  const filterRemovalRate = document.getElementById("filterRemovalRate");
  const filterMWCO_DA = document.getElementById("filterMWCO_DA");

  // Chart control buttons
  const resetZoomBtn = document.getElementById("resetZoomBtn");
  const toggleGridBtn = document.getElementById("toggleGridBtn");
  const exportBtn = document.getElementById("exportBtn");
  const bubbleOptions = document.getElementById("bubbleOptions");

  let showGrid = true;

  const unitsMap = {
    mwco_da: "MWCO (Da)",
    removal_rate: "Removal Rate (%)",
    pressure: "Pressure (psi)",
    isoelectric_point: "Isoelectric Point (pH)",
    water_contact_angle: "Water Contact Angle (°)",
    compound_size: "Compound Size (Å)",
    log_kow: "Log K_ow",
    pka: "pKa",
    initial_concentration: "Initial Concentration (ng/L)",
    mw: "Molecular Weight (g/mol)"
  };

  // Enhanced color palette for better distinction
  const membraneColors = {
    NF270: "#FF6B6B",    // Coral red
    NF90:  "#4ECDC4",    // Teal
    XLE:   "#45B7D1",    // Sky blue
    BW30:  "#96CEB4",    // Mint green
    SW30:  "#FFEAA7",    // Light yellow
    TFC:   "#DDA0DD",    // Plum
    RO:    "#FFB347",    // Peach
    NF:    "#A8E6CF",    // Light green
    NF270PAA: "#FF8A80", // Light red
    NF270PEI: "#81C784", // Light green
    NF2702540: "#64B5F6", // Light blue
    DK:    "#F48FB1",    // Pink
    DL:    "#CE93D8",    // Light purple
    NF200: "#FFAB91",    // Light orange
    NTR7450: "#90CAF9",  // Very light blue
    Unknown: "#95A5A6"   // Gray
  };

  function getColor(membrane, alpha = 0.8) {
    const baseColor = membraneColors[membrane] || "#3498DB";
    // Convert hex to rgba
    const hex = baseColor.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  const numericFields = [
    "mwco_da", "pressure", "removal_rate", "isoelectric_point",
    "water_contact_angle", "compound_size", "log_kow", "pka",
    "initial_concentration", "mw"
  ];

  // Populate axis selectors
  numericFields.forEach(field => {
    if (unitsMap[field]) {
      [xSelect, ySelect, bubbleSizeSelect].forEach(sel => {
        const opt = document.createElement("option");
        opt.value = field;
        opt.textContent = unitsMap[field];
        sel.appendChild(opt);
      });
    }
  });

  xSelect.value = "mwco_da";
  ySelect.value = "removal_rate";
  bubbleSizeSelect.value = "compound_size";

  function populateCompare(data) {
    data.sort((a, b) => a.id - b.id);
    const membranes = Array.from(new Set(data.map(i => i.membrane)));
    compareContainer.innerHTML = '';
    membranes.forEach(mem => {
      const div = document.createElement('div');
      div.className = 'form-check';
      const cb = document.createElement('input');
      cb.className = 'form-check-input';
      cb.type = 'checkbox';
      cb.id = `cmp-${mem}`;
      cb.value = mem;
      const lbl = document.createElement('label');
      lbl.className = 'form-check-label';
      lbl.htmlFor = cb.id;
      lbl.textContent = mem;
      div.appendChild(cb);
      div.appendChild(lbl);
      compareContainer.appendChild(div);
    });
  }

  function getSelectedCompare() {
    return Array.from(compareContainer.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
  }

  function applyFilters(data) {
    const xField = xSelect.value;
    const yField = ySelect.value;
    const sizeField = bubbleSizeSelect.value;
    const compareVals = getSelectedCompare();
    const memFilter = filterMembrane.value;
    const pfasFilter = filterPFAS.value;
    const minRemoval = parseFloat(filterRemovalRate.value);
    const maxMWCO_DA = parseFloat(filterMWCO_DA.value);

    return data.filter(item => {
      if (compareVals.length && !compareVals.includes(item.membrane)) return false;
      if (memFilter && item.membrane !== memFilter) return false;
      if (pfasFilter && item.pfas !== pfasFilter) return false;
      if (!isNaN(minRemoval) && +item.removal_rate < minRemoval) return false;
      if (!isNaN(maxMWCO_DA) && +item.mwco_da > maxMWCO_DA) return false;
      return !isNaN(+item[xField]) && !isNaN(+item[yField]);
    }).map(item => {
      const point = {
        x: +item[xField],
        y: +item[yField],
        label: item.pfas,
        membrane: item.membrane,
        backgroundColor: getColor(item.membrane),
        borderColor: getColor(item.membrane, 1),
        // Store original data for tooltip
        originalData: item
      };

      // Add bubble size if bubble chart or scatter3d
      if ((chartTypeSelect.value === 'bubble' || chartTypeSelect.value === 'scatter3d') && sizeField && !isNaN(+item[sizeField])) {
        point.r = Math.max(3, Math.min(20, +item[sizeField] / 10)); // Scale bubble size
      }

      return point;
    });
  }

  function populateFilters(data) {
    const membranes = Array.from(new Set(data.map(i => i.membrane))).sort();
    const pfasTypes = Array.from(new Set(data.map(i => i.pfas))).sort();

    function fill(select, items) {
      items.forEach(val => {
        if (![...select.options].some(o => o.value === val)) {
          const opt = document.createElement('option');
          opt.value = val;
          opt.textContent = val;
          select.appendChild(opt);
        }
      });
    }

    fill(filterMembrane, membranes);
    fill(filterPFAS, pfasTypes);
  }

  // Calculate trend line using linear regression
  function calculateTrendLine(points) {
    if (points.length < 2) return null;

    const n = points.length;
    const sumX = points.reduce((sum, p) => sum + p.x, 0);
    const sumY = points.reduce((sum, p) => sum + p.y, 0);
    const sumXY = points.reduce((sum, p) => sum + p.x * p.y, 0);
    const sumXX = points.reduce((sum, p) => sum + p.x * p.x, 0);

    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;

    const minX = Math.min(...points.map(p => p.x));
    const maxX = Math.max(...points.map(p => p.x));

    return [
      { x: minX, y: slope * minX + intercept },
      { x: maxX, y: slope * maxX + intercept }
    ];
  }

  // Helper function for correlation calculation
  function calculateCorrelation(x, y) {
    const n = Math.min(x.length, y.length);
    if (n < 2) return 0;

    const xSlice = x.slice(0, n);
    const ySlice = y.slice(0, n);

    const sumX = xSlice.reduce((a, b) => a + b, 0);
    const sumY = ySlice.reduce((a, b) => a + b, 0);
    const sumXY = xSlice.reduce((sum, xi, i) => sum + xi * ySlice[i], 0);
    const sumXX = xSlice.reduce((sum, xi) => sum + xi * xi, 0);
    const sumYY = ySlice.reduce((sum, yi) => sum + yi * yi, 0);

    const numerator = n * sumXY - sumX * sumY;
    const denominator = Math.sqrt((n * sumXX - sumX * sumX) * (n * sumYY - sumY * sumY));

    return denominator === 0 ? 0 : numerator / denominator;
  }

  // Function to prepare data for different chart types
  function prepareDataForChartType(filteredData, chartType) {
    const xField = xSelect.value;
    const yField = ySelect.value;

    switch (chartType) {
      case 'bar':
        // Group by membrane type and calculate averages
        const membraneGroups = {};
        filteredData.forEach(point => {
          const membrane = point.originalData.membrane;
          if (!membraneGroups[membrane]) {
            membraneGroups[membrane] = { values: [], color: getColor(membrane) };
          }
          membraneGroups[membrane].values.push(point.y);
        });

        return {
          labels: Object.keys(membraneGroups),
          datasets: [{
            label: unitsMap[yField],
            data: Object.values(membraneGroups).map(group =>
              group.values.reduce((a, b) => a + b, 0) / group.values.length
            ),
            backgroundColor: Object.values(membraneGroups).map(group => group.color),
            borderColor: Object.values(membraneGroups).map(group => group.color.replace('0.8', '1')),
            borderWidth: 2
          }]
        };

      case 'stackedBar':
        // Stack by PFAS type within each membrane
        const stackedGroups = {};
        const pfasTypes = Array.from(new Set(filteredData.map(p => p.originalData.pfas)));

        filteredData.forEach(point => {
          const membrane = point.originalData.membrane;
          const pfas = point.originalData.pfas;
          if (!stackedGroups[membrane]) {
            stackedGroups[membrane] = {};
            pfasTypes.forEach(type => stackedGroups[membrane][type] = []);
          }
          if (!stackedGroups[membrane][pfas]) {
            stackedGroups[membrane][pfas] = [];
          }
          stackedGroups[membrane][pfas].push(point.y);
        });

        const membraneLabels = Object.keys(stackedGroups);
        const datasets = pfasTypes.map((pfas, index) => ({
          label: pfas,
          data: membraneLabels.map(membrane => {
            const values = stackedGroups[membrane][pfas] || [];
            return values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : 0;
          }),
          backgroundColor: `hsla(${index * 137.5 % 360}, 70%, 60%, 0.8)`,
          borderColor: `hsla(${index * 137.5 % 360}, 70%, 50%, 1)`,
          borderWidth: 1
        }));

        return { labels: membraneLabels, datasets };

      case 'boxplot':
        // Simulate box plot with error bars using bar chart
        const boxGroups = {};
        filteredData.forEach(point => {
          const membrane = point.originalData.membrane;
          if (!boxGroups[membrane]) {
            boxGroups[membrane] = { values: [], color: getColor(membrane) };
          }
          boxGroups[membrane].values.push(point.y);
        });

        const boxData = Object.keys(boxGroups).map(membrane => {
          const values = boxGroups[membrane].values.sort((a, b) => a - b);
          const q1 = values[Math.floor(values.length * 0.25)];
          const median = values[Math.floor(values.length * 0.5)];
          const q3 = values[Math.floor(values.length * 0.75)];

          return {
            label: membrane,
            median,
            q1,
            q3,
            color: boxGroups[membrane].color
          };
        });

        return {
          labels: boxData.map(d => d.label),
          datasets: [
            {
              label: 'Median',
              data: boxData.map(d => d.median),
              backgroundColor: boxData.map(d => d.color),
              borderColor: boxData.map(d => d.color.replace('0.8', '1')),
              borderWidth: 2
            },
            {
              label: 'Q1-Q3 Range',
              data: boxData.map(d => d.q3 - d.q1),
              backgroundColor: boxData.map(d => d.color.replace('0.8', '0.3')),
              borderColor: boxData.map(d => d.color.replace('0.8', '1')),
              borderWidth: 1,
              type: 'bar'
            }
          ]
        };

      case 'heatmap':
        // Create correlation heatmap between numeric properties
        const numProps = ['removal_rate', 'mwco_da', 'pressure', 'compound_size', 'initial_concentration'];
        const heatmapData = [];

        for (let i = 0; i < numProps.length; i++) {
          for (let j = 0; j < numProps.length; j++) {
            const xVals = filteredData.map(p => +p.originalData[numProps[i]]).filter(v => !isNaN(v));
            const yVals = filteredData.map(p => +p.originalData[numProps[j]]).filter(v => !isNaN(v));

            if (xVals.length > 1 && yVals.length > 1) {
              const correlation = calculateCorrelation(xVals, yVals);
              heatmapData.push({
                x: j,
                y: i,
                v: correlation
              });
            } else {
              heatmapData.push({
                x: j,
                y: i,
                v: 0
              });
            }
          }
        }

        return {
          labels: numProps.map(prop => unitsMap[prop] || prop),
          datasets: [{
            label: 'Correlation',
            data: heatmapData,
            backgroundColor: function(context) {
              const value = context.parsed.v;
              const alpha = Math.abs(value);
              return value >= 0 ? `rgba(54, 162, 235, ${alpha})` : `rgba(255, 99, 132, ${alpha})`;
            },
            borderColor: 'rgba(255, 255, 255, 0.1)',
            borderWidth: 1
          }]
        };

      case 'area':
        // Cumulative area chart by membrane type
        const areaGroups = {};
        filteredData.forEach(point => {
          const membrane = point.originalData.membrane;
          if (!areaGroups[membrane]) {
            areaGroups[membrane] = [];
          }
          areaGroups[membrane].push(point);
        });

        return {
          datasets: Object.keys(areaGroups).map((membrane, index) => ({
            label: membrane,
            data: areaGroups[membrane].sort((a, b) => a.x - b.x),
            backgroundColor: getColor(membrane, 0.3),
            borderColor: getColor(membrane),
            borderWidth: 2,
            fill: 'origin',
            tension: 0.4,
            pointRadius: 3,
            pointHoverRadius: 5
          }))
        };

      case 'scatter3d':
        // Enhanced scatter with third dimension (simulated with varying opacity and size)
        const sizeField = bubbleSizeSelect.value;
        return filteredData.map(point => {
          const sizeValue = +point.originalData[sizeField] || 5;
          const normalizedSize = Math.max(3, Math.min(15, sizeValue / 5));
          const opacity = Math.max(0.3, Math.min(1, sizeValue / 100));

          return {
            ...point,
            r: normalizedSize,
            backgroundColor: point.backgroundColor.replace('0.8', opacity.toString()),
            borderColor: point.borderColor
          };
        });

      default: // scatter and bubble
        return filteredData;
    }
  }

  // Function to show tooltip on click
  function showClickTooltip(event, rawData, originalData) {
    // Create tooltip element if it doesn't exist
    let tooltipEl = document.querySelector('.click-tooltip');
    if (!tooltipEl) {
      tooltipEl = document.createElement('div');
      tooltipEl.className = 'click-tooltip';
      tooltipEl.style.cssText = `
        position: fixed;
        background: rgba(0, 0, 0, 0.95);
        color: white;
        padding: 15px;
        border-radius: 10px;
        font-size: 12px;
        pointer-events: auto;
        z-index: 10000;
        max-width: 320px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        border: 2px solid rgba(255, 255, 255, 0.2);
        opacity: 0;
        transform: scale(0.8);
        transition: all 0.2s ease;
      `;
      document.body.appendChild(tooltipEl);
    }

    const xLabel = unitsMap[xSelect.value];
    const yLabel = unitsMap[ySelect.value];

    let html = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
          <div style="font-weight: bold; color: #87CEEB; font-size: 14px;">${rawData.membrane || 'Unknown'} Membrane</div>
          <div style="color: #FFA07A; font-size: 13px;">PFAS: ${rawData.label || 'N/A'}</div>
        </div>
        <button onclick="hideTooltip()" style="background: rgba(255,255,255,0.2); border: none; color: white; width: 24px; height: 24px; border-radius: 50%; cursor: pointer; font-size: 16px; display: flex; align-items: center; justify-content: center;">×</button>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 11px; margin-bottom: 12px;">
        <div><strong>${xLabel}:</strong></div><div>${rawData.x || 'N/A'}</div>
        <div><strong>${yLabel}:</strong></div><div>${rawData.y || 'N/A'}</div>
    `;

    // Add membrane-specific data if available
    if (originalData) {
      if (originalData.mwco_da && originalData.mwco_da !== rawData.x && originalData.mwco_da !== rawData.y) {
        html += `<div><strong>MWCO:</strong></div><div>${originalData.mwco_da} Da</div>`;
      }
      if (originalData.pressure && originalData.pressure !== rawData.x && originalData.pressure !== rawData.y) {
        html += `<div><strong>Pressure:</strong></div><div>${originalData.pressure} psi</div>`;
      }
      if (originalData.ph) {
        html += `<div><strong>pH:</strong></div><div>${originalData.ph}</div>`;
      }
      if (originalData.removal_rate && originalData.removal_rate !== rawData.y && originalData.removal_rate !== rawData.x) {
        html += `<div><strong>Removal:</strong></div><div>${originalData.removal_rate}%</div>`;
      }
      if (originalData.initial_concentration && originalData.initial_concentration !== rawData.x && originalData.initial_concentration !== rawData.y) {
        html += `<div><strong>Init. Conc:</strong></div><div>${originalData.initial_concentration} ng/L</div>`;
      }
      if (originalData.water_contact_angle && originalData.water_contact_angle !== rawData.x && originalData.water_contact_angle !== rawData.y) {
        html += `<div><strong>Contact Angle:</strong></div><div>${originalData.water_contact_angle}°</div>`;
      }
    }

    html += `</div>`;

    // Add reference and DOI at bottom if available
    if (originalData && (originalData.ref || originalData.doi)) {
      html += `<div style="border-top: 1px solid rgba(255,255,255,0.3); padding-top: 10px; font-size: 10px;">`;
      if (originalData.ref) {
        html += `<div style="margin-bottom: 6px;"><strong>Reference:</strong> ${originalData.ref}</div>`;
      }
      if (originalData.doi) {
        html += `<div><strong>DOI:</strong> <a href="${originalData.doi}" target="_blank" style="color: #87CEEB; text-decoration: underline;">${originalData.doi.length > 50 ? originalData.doi.substring(0, 50) + '...' : originalData.doi}</a></div>`;
      }
      html += `</div>`;
    }

    html += `<div style="margin-top: 12px; font-size: 9px; color: #aaa; text-align: center;">Click outside to close</div>`;

    tooltipEl.innerHTML = html;

    // Use the raw mouse event coordinates
    let left = event.clientX + 15;
    let top = event.clientY - 15;

    // Boundary checking to keep tooltip on screen
    const tooltipWidth = 320;
    const tooltipHeight = 250;

    if (left + tooltipWidth > window.innerWidth) {
      left = event.clientX - tooltipWidth - 15;
    }

    if (top < 0) {
      top = event.clientY + 15;
    }

    if (top + tooltipHeight > window.innerHeight) {
      top = event.clientY - tooltipHeight - 15;
    }

    // Show tooltip with animation
    tooltipEl.style.left = left + 'px';
    tooltipEl.style.top = top + 'px';

    // Trigger animation
    setTimeout(() => {
      tooltipEl.style.opacity = 1;
      tooltipEl.style.transform = 'scale(1)';
    }, 10);
  }

  // Function to hide tooltip
  function hideTooltip() {
    const tooltipEl = document.querySelector('.click-tooltip');
    if (tooltipEl) {
      tooltipEl.style.opacity = 0;
      tooltipEl.style.transform = 'scale(0.8)';
      setTimeout(() => {
        if (tooltipEl.parentNode) {
          tooltipEl.parentNode.removeChild(tooltipEl);
        }
      }, 200);
    }
  }

  // Make hideTooltip globally accessible
  window.hideTooltip = hideTooltip;

  function renderChart() {
    const xField = xSelect.value;
    const yField = ySelect.value;
    const chartType = chartTypeSelect.value;
    const xLabel = unitsMap[xField];
    const yLabel = unitsMap[yField];
    const filteredData = applyFilters(allData);
    const ctx = document.getElementById('pfasChart').getContext('2d');

    if (chartInstance) chartInstance.destroy();

    // Prepare data based on chart type
    const chartData = prepareDataForChartType(filteredData, chartType);

    // Configuration varies by chart type
    let config = {
      type: chartType,
      data: {},
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: `${yLabel} vs ${xLabel}`,
            font: { size: 16, weight: 'bold' }
          },
          legend: {
            display: ['area', 'stackedBar', 'boxplot'].includes(chartType)
          },
          tooltip: {
            enabled: ['bar', 'stackedBar', 'boxplot', 'area', 'heatmap'].includes(chartType)
          }
        }
      }
    };

    // Set up data and specific options for each chart type
    switch (chartType) {
      case 'scatter':
      case 'bubble':
      case 'scatter3d':
        config.data = { datasets: [{
          label: `${yLabel} vs ${xLabel}`,
          data: chartData,
          pointBackgroundColor: chartData.map(p => p.backgroundColor),
          pointBorderColor: chartData.map(p => p.borderColor),
          pointRadius: (chartType === 'bubble' || chartType === 'scatter3d') ? chartData.map(p => p.r || 5) : 5,
          pointHoverRadius: (chartType === 'bubble' || chartType === 'scatter3d') ? chartData.map(p => p.r || 5) : 5,
          pointHitRadius: 15,
          borderWidth: 2,
          showLine: false
        }]};

        // Add trend line if enabled
        if (showTrendLine.checked && chartData.length > 1) {
          const trendData = calculateTrendLine(chartData);
          if (trendData) {
            config.data.datasets.push({
              label: 'Trend Line',
              data: trendData,
              type: 'line',
              borderColor: 'rgba(255, 99, 132, 0.8)',
              backgroundColor: 'transparent',
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 0,
              pointHitRadius: 0,
              borderDash: [5, 5]
            });
          }
        }

        config.options.scales = {
          x: {
            title: { display: true, text: xLabel, font: { size: 14, weight: 'bold' }},
            grid: { display: showGrid },
            ticks: { maxTicksLimit: 10 }
          },
          y: {
            type: logToggle.checked ? 'logarithmic' : 'linear',
            title: { display: true, text: yLabel, font: { size: 14, weight: 'bold' }},
            grid: { display: showGrid },
            ticks: {
              callback: function(value) {
                if (logToggle.checked) {
                  return Number(value).toExponential(1);
                }
                return value;
              },
              maxTicksLimit: 10
            }
          }
        };

        config.options.plugins.zoom = {
          pan: { enabled: true, mode: 'xy' },
          zoom: { wheel: { enabled: true }, mode: 'xy' }
        };

      // Replace the onHover and onClick sections with this:

config.options.onHover = (event, elements) => {
  const canvas = event.native?.target || event.target;
  
  if (elements && elements.length > 0) {
    canvas.style.cursor = 'pointer';
    const element = elements[0];
    const chart = chartInstance || Chart.getChart('pfasChart');
    const dataset = chart.data.datasets[element.datasetIndex];
    const dataPoint = dataset.data[element.index];
    const originalData = dataPoint.originalData;
    
    if (originalData) {
      showClickTooltip(event.native || event, dataPoint, originalData);
    }
  } else {
    canvas.style.cursor = 'default';
    hideTooltip();
  }
};

config.options.onClick = (event, elements) => {
  if (elements && elements.length > 0) {
    const element = elements[0];
    const chart = chartInstance || Chart.getChart('pfasChart');
    const dataset = chart.data.datasets[element.datasetIndex];
    const dataPoint = dataset.data[element.index];
    const originalData = dataPoint.originalData;
    
    // Open DOI link if available
    if (originalData && originalData.doi) {
      window.open(
        originalData.doi.startsWith('http') ?
        originalData.doi :
        `https://doi.org/${originalData.doi}`,
        '_blank'
      );
    }
  }
};

break;

// Remove the onLeave line that was there before

      case 'area':
        config.data = chartData;
        config.options.scales = {
          x: {
            title: { display: true, text: xLabel, font: { size: 14, weight: 'bold' }},
            grid: { display: showGrid }
          },
          y: {
            title: { display: true, text: yLabel, font: { size: 14, weight: 'bold' }},
            grid: { display: showGrid },
            stacked: true
          }
        };
        config.options.elements = {
          line: { tension: 0.4 },
          point: { radius: 3 }
        };
        break;

      case 'bar':
      case 'stackedBar':
      case 'boxplot':
        config.data = chartData;
        config.options.scales = {
          x: {
            title: { display: true, text: 'Membrane Type' },
            grid: { display: showGrid }
          },
          y: {
            title: { display: true, text: chartType === 'boxplot' ? `${yLabel} Distribution` : `Average ${yLabel}` },
            grid: { display: showGrid },
            stacked: chartType === 'stackedBar'
          }
        };
        if (chartType === 'stackedBar') {
          config.options.scales.x.stacked = true;
        }
        break;

      case 'heatmap':
        // Note: Chart.js doesn't have native heatmap, so we'll use a scatter plot with color coding
        config.type = 'scatter';
        config.data = chartData;
        config.options.scales = {
          x: {
            type: 'linear',
            position: 'bottom',
            title: { display: true, text: 'Property Index' },
            grid: { display: showGrid },
            ticks: {
              stepSize: 1,
              callback: function(value, index) {
                const props = ['Removal Rate', 'MWCO', 'Pressure', 'Compound Size', 'Init. Conc.'];
                return props[value] || value;
              }
            }
          },
          y: {
            type: 'linear',
            title: { display: true, text: 'Property Index' },
            grid: { display: showGrid },
            ticks: {
              stepSize: 1,
              callback: function(value, index) {
                const props = ['Removal Rate', 'MWCO', 'Pressure', 'Compound Size', 'Init. Conc.'];
                return props[value] || value;
              }
            }
          }
        };
        config.options.plugins.title.text = 'Property Correlation Heatmap';
        break;
    }

    chartInstance = new Chart(ctx, config);
  }

  async function fetchData() {
    try {
      const res = await fetch('/data', {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (res.status === 401) {
        localStorage.removeItem('token');
        chartError.classList.remove('d-none');
        chartError.innerText = 'Your session has expired. Redirecting to login…';
        return setTimeout(() => location.href = 'login.html', 3000);
      }

      if (!res.ok) throw new Error('Fetch failed');
      allData = await res.json();

      populateCompare(allData);
      populateFilters(allData);
      renderChart();

      const urlParams = new URLSearchParams(window.location.search);
      const compareParam = urlParams.get('compare');
      if (compareParam) {
        compareParam.split(',').forEach(mem => {
          const cb = document.getElementById(`cmp-${mem}`);
          if (cb) cb.checked = true;
        });
        compareContainer.dispatchEvent(new Event('change'));
      }

    } catch (err) {
      console.error(err);
      chartError.style.display = 'block';
      chartError.textContent = 'Error loading chart. Please log in again.';
    }
  }

  // Event Listeners
  [xSelect, ySelect, logToggle, showTrendLine, filterPFAS, filterRemovalRate, filterMWCO_DA]
    .forEach(el => el.addEventListener('change', renderChart));

  // Clear All Button Logic
  document.getElementById('deselectAllBtn').addEventListener('click', () => {
    compareContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.checked = false;
    });
    filterMembrane.disabled = false;
    renderChart();
  });

  chartTypeSelect.addEventListener('change', () => {
    // Show/hide bubble options for bubble and 3D scatter
    bubbleOptions.style.display = ['bubble', 'scatter3d'].includes(chartTypeSelect.value) ? 'block' : 'none';
    renderChart();
  });

  bubbleSizeSelect.addEventListener('change', renderChart);

  filterMembrane.addEventListener('change', () => {
    if (filterMembrane.value) {
      compareContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
    }
    renderChart();
  });

  compareContainer.addEventListener('change', () => {
    const any = getSelectedCompare().length > 0;
    filterMembrane.disabled = any;
    if (any) filterMembrane.value = '';
    renderChart();
  });

  // Chart control button event listeners
  resetZoomBtn.addEventListener('click', () => {
    if (chartInstance) {
      chartInstance.resetZoom();
    }
  });

  toggleGridBtn.addEventListener('click', () => {
    showGrid = !showGrid;
    toggleGridBtn.innerHTML = showGrid ?
      '<i class="bi bi-grid"></i> Hide Grid' :
      '<i class="bi bi-grid"></i> Show Grid';
    renderChart();
  });

  exportBtn.addEventListener('click', () => {
    if (chartInstance) {
      const url = chartInstance.toBase64Image('image/png', 1);
      const link = document.createElement('a');
      link.download = 'pfas-chart.png';
      link.href = url;
      link.click();
    }
  });

  // Initialize
  fetchData();

  // Add this near the end of your DOMContentLoaded event listener, after fetchData()

// Hide tooltip when mouse leaves chart
const canvas = document.getElementById('pfasChart');
if (canvas) {
  canvas.addEventListener('mouseleave', () => {
    hideTooltip();
  });
}

// Also hide tooltip when clicking outside
document.addEventListener('click', (event) => {
  const tooltip = document.querySelector('.click-tooltip');
  const chartCanvas = document.getElementById('pfasChart');
  
  if (tooltip && !tooltip.contains(event.target) && chartCanvas && !chartCanvas.contains(event.target)) {
    hideTooltip();
  }
});
});
