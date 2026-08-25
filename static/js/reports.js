(function() {
    var activeKey = null;

    function buildForm(key) {
        var report = REPORTS[key];
        activeKey = key;
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
            input.type = param.input; // 'date', 'number', or 'text'
            input.required = true;
            if (param.default !== undefined) input.value = param.default;
            if (param.step !== undefined) input.step = param.step;
            if (param.min !== undefined) input.min = param.min;
            if (param.max !== undefined) input.max = param.max;
            if (param.input === 'text') input.placeholder = 'e.g. AAPL';
            field.appendChild(input);

            fieldsContainer.appendChild(field);
        });

        document.querySelectorAll('.report-tab').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.report === key);
        });

        document.getElementById('report-table').innerHTML = '';
        document.getElementById('report-status').textContent = '';
    }

    function renderTable(columns, rows) {
        var table = document.getElementById('report-table');
        table.innerHTML = '';

        if (rows.length === 0) {
            document.getElementById('report-status').textContent = 'No rows returned.';
            return;
        }
        document.getElementById('report-status').textContent =
            rows.length + ' row' + (rows.length === 1 ? '' : 's');

        var thead = document.createElement('thead');
        var headRow = document.createElement('tr');
        columns.forEach(function(col) {
            var th = document.createElement('th');
            th.textContent = col;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        rows.forEach(function(row) {
            var tr = document.createElement('tr');
            row.forEach(function(value) {
                var td = document.createElement('td');
                td.textContent = (value === null || value === undefined) ? '—' : value;
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

        var params = new URLSearchParams(new FormData(e.target));

        document.getElementById('report-status').textContent = 'Running…';
        document.getElementById('report-table').innerHTML = '';

        fetch('/reports/run/' + activeKey + '?' + params.toString())
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.error) {
                    document.getElementById('report-status').textContent = 'Error: ' + data.error;
                    return;
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
