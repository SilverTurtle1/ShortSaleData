(function() {
    var activeKey = null;
    var currentColumns = null;
    var currentRows = null;
    var sortColumnIndex = null; // index into the raw `columns` array from the server
    var sortDir = 1; // 1 = ascending, -1 = descending
    var EXTREME_MULTIPLIER = 3; // highlight ratio columns at or above this

    function buildForm(key) {
        var report = REPORTS[key];
        activeKey = key;
        sortColumnIndex = null;
        sortDir = 1;
        document.getElementById('report-description').textContent = report.description;

        var fieldsContainer = document.getElementById('report-form-fields');
        fieldsContainer.innerHTML = '';

        report.params.forEach(function(param) {
            var field = document.createElement('div');
            field.className = 'filter-field';

            var label = document.createElement('span');
            label.className = 'field-label';
            label.textContent = param.label;
            field.appendChild(label);

            var input = document.createElement('input');
            input.name = param.name;
            input.required = true;
            if (param.input === 'text') input.placeholder = 'e.g. AAPL';

            if (param.format === 'number') {
                // A plain type=number input can't display digit grouping
                // at all (browsers reject the commas outright), so this
                // uses text + a live reformat-as-you-type instead.
                input.type = 'text';
                input.inputMode = 'numeric';
                if (param.default !== undefined) input.value = Number(param.default).toLocaleString('en');
                input.addEventListener('input', function() {
                    var raw = input.value.replace(/,/g, '');
                    if (raw === '' || isNaN(raw)) return;
                    input.value = Number(raw).toLocaleString('en');
                });
            } else {
                input.type = param.input; // 'date', 'number', or 'text'
                if (param.default !== undefined) input.value = param.default;
                if (param.step !== undefined) input.step = param.step;
                if (param.min !== undefined) input.min = param.min;
                if (param.max !== undefined) input.max = param.max;
            }

            if (param.today_aware) {
                // Defaults to today once FINRA has actually published that
                // day's file (roughly mid-afternoon Pacific); before that,
                // defaults to (and caps at) yesterday, same rule as the
                // main treemap page's date picker.
                var latestAllowed = pacificDateISO(isTodayPublished() ? 0 : 1);
                input.max = latestAllowed;
                input.value = latestAllowed;
            }
            field.appendChild(input);

            fieldsContainer.appendChild(field);
        });

        document.querySelectorAll('.report-tab').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.report === key);
        });

        document.getElementById('report-table').innerHTML = '';
        document.getElementById('report-status').textContent = '';
    }

    // yyyymmdd -> MM/DD/YYYY, for display only -- the report itself still
    // sends/receives the raw bigint form.
    function formatDate(value) {
        var s = String(value);
        if (s.length !== 8) return s;
        return s.slice(4, 6) + '/' + s.slice(6, 8) + '/' + s.slice(0, 4);
    }

    function formatValue(value, format) {
        if (value === null || value === undefined) return '—';
        switch (format) {
            case 'date': return formatDate(value);
            case 'percent': return value + '%';
            case 'multiplier': return Number(value).toFixed(1) + 'x';
            case 'number': return Number(value).toLocaleString('en');
            default: return value;
        }
    }

    // Nulls sort last regardless of direction; numbers compare
    // numerically, everything else falls back to string comparison.
    function compareValues(a, b) {
        var aNull = (a === null || a === undefined);
        var bNull = (b === null || b === undefined);
        if (aNull && bNull) return 0;
        if (aNull) return 1;
        if (bNull) return -1;
        if (typeof a === 'number' && typeof b === 'number') return a - b;
        return String(a).localeCompare(String(b));
    }

    function sortByColumn(index) {
        if (sortColumnIndex === index) {
            sortDir = -sortDir;
        } else {
            sortColumnIndex = index;
            sortDir = -1; // first click on a column shows the extremes first
        }
        currentRows.sort(function(a, b) {
            return sortDir * compareValues(a[index], b[index]);
        });
        renderTable(currentColumns, currentRows);
    }

    function renderTable(columns, rows) {
        currentColumns = columns;
        currentRows = rows;

        var table = document.getElementById('report-table');
        table.innerHTML = '';

        if (rows.length === 0) {
            document.getElementById('report-status').textContent = 'No rows returned.';
            return;
        }
        document.getElementById('report-status').textContent =
            rows.length + ' row' + (rows.length === 1 ? '' : 's');

        // A report can define "columns" to control display order, labels,
        // and value formatting; otherwise fall back to whatever order/
        // names the SQL function itself returned, unformatted.
        var columnMeta = REPORTS[activeKey].columns;
        var displayColumns = columnMeta
            ? columnMeta.map(function(c) {
                return {index: columns.indexOf(c.name), label: c.label, format: c.format};
            })
            : columns.map(function(c, i) {
                return {index: i, label: c, format: null};
            });

        var thead = document.createElement('thead');
        var headRow = document.createElement('tr');
        displayColumns.forEach(function(dc) {
            var th = document.createElement('th');
            // Any formatted column is a number/percent/ratio -- right-align
            // it so values compare cleanly down the column; the (unformatted)
            // symbol/text columns stay left-aligned.
            if (dc.format) th.classList.add('numeric');
            th.appendChild(document.createTextNode(dc.label));
            if (sortColumnIndex === dc.index) {
                var indicator = document.createElement('span');
                indicator.className = 'sort-indicator';
                indicator.textContent = ' ' + (sortDir === 1 ? '▲' : '▼');
                th.appendChild(indicator);
            }
            th.addEventListener('click', function() { sortByColumn(dc.index); });
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        rows.forEach(function(row) {
            var tr = document.createElement('tr');
            displayColumns.forEach(function(dc) {
                var td = document.createElement('td');
                var value = row[dc.index];
                if (dc.format) td.classList.add('numeric');
                // Flags a ratio column as notably extreme so it's visible
                // at a glance instead of requiring a sort/scan to spot.
                if (dc.format === 'multiplier' && typeof value === 'number' && value >= EXTREME_MULTIPLIER) {
                    td.classList.add('value-extreme');
                }
                td.textContent = formatValue(value, dc.format);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
    }

    document.getElementById('report-tabs').addEventListener('click', function(e) {
        if (e.target.classList.contains('report-tab')) {
            buildForm(e.target.dataset.report);
        }
    });

    document.getElementById('report-form').addEventListener('submit', function(e) {
        e.preventDefault();
        if (!activeKey) return;

        // Comma-formatted number fields display grouped digits (e.g.
        // "5,000,000") for readability -- strip them back out before
        // sending, since no param here ever legitimately contains a comma.
        var rawParams = new URLSearchParams(new FormData(e.target));
        var params = new URLSearchParams();
        rawParams.forEach(function(value, key) {
            params.append(key, value.replace(/,/g, ''));
        });

        document.getElementById('report-status').textContent = 'Running…';
        document.getElementById('report-table').innerHTML = '';
        sortColumnIndex = null;
        sortDir = 1;

        fetch('/reports/run/' + activeKey + '?' + params.toString())
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.error) {
                    document.getElementById('report-status').textContent = 'Error: ' + data.error;
                    return;
                }
                // Applied once, right after a fresh run, so the most
                // notable rows are visible without needing a header click.
                var defaultSort = REPORTS[activeKey].default_sort;
                if (defaultSort) {
                    var idx = data.columns.indexOf(defaultSort.column);
                    if (idx !== -1) {
                        sortColumnIndex = idx;
                        sortDir = defaultSort.dir || -1;
                        data.rows.sort(function(a, b) {
                            return sortDir * compareValues(a[idx], b[idx]);
                        });
                    }
                }
                renderTable(data.columns, data.rows);
            })
            .catch(function(err) {
                document.getElementById('report-status').textContent = 'Error: ' + err.message;
            });
    });

    var firstKey = Object.keys(REPORTS)[0];
    if (firstKey) buildForm(firstKey);
})();
