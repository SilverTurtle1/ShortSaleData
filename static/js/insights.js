// "Unusual activity" panel under the treemap: per-symbol volume surges
// and short-% jumps/drops on the latest trading day in the selected range,
// each measured against that symbol's own trailing 20 days (computed
// server-side, see get_insights in finra.py).
(function() {
    var lastKey = null;

    function formatDate(yyyymmdd) {
        var s = String(yyyymmdd);
        return s.slice(4, 6) + '/' + s.slice(6, 8) + '/' + s.slice(0, 4);
    }

    function formatVolume(n) {
        return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : (n / 1e3).toFixed(0) + 'K';
    }

    function signed(n) {
        return (n > 0 ? '+' : '') + n.toFixed(1);
    }

    // One ranked list. `metric`/`detail` return the right-hand headline
    // number and the muted line under it for a row.
    function buildList(title, subtitle, rows, metric, detail, date) {
        var section = document.createElement('div');
        section.className = 'insights-list';

        var h = document.createElement('h4');
        h.textContent = title;
        section.appendChild(h);
        var sub = document.createElement('p');
        sub.className = 'insights-subtitle';
        sub.textContent = subtitle;
        section.appendChild(sub);

        if (!rows.length) {
            var empty = document.createElement('p');
            empty.className = 'insights-empty';
            empty.textContent = 'Nothing notable.';
            section.appendChild(empty);
            return section;
        }

        rows.forEach(function(row) {
            var item = document.createElement('div');
            item.className = 'insights-row';

            var left = document.createElement('div');
            var link = document.createElement('a');
            link.href = '#';
            link.className = 'report-symbol-link';
            link.textContent = row.symbol;
            link.addEventListener('click', function(e) {
                e.preventDefault();
                loadModal();
                populateBarChart(row.symbol, date);
            });
            left.appendChild(link);
            var company = document.createElement('div');
            company.className = 'insights-company';
            company.textContent = row.company || '';
            left.appendChild(company);

            var right = document.createElement('div');
            right.className = 'insights-metric';
            var main = document.createElement('div');
            main.className = 'insights-metric-main';
            main.textContent = metric(row);
            right.appendChild(main);
            var small = document.createElement('div');
            small.className = 'insights-metric-detail';
            small.textContent = detail(row);
            right.appendChild(small);

            item.appendChild(left);
            item.appendChild(right);
            section.appendChild(item);
        });
        return section;
    }

    var STRIP_COUNT = 5;
    var surgeFlags = {};
    var surgeRatio = 2;
    var asOfDate = null;

    // Badges treemap tiles whose volume is at/above the flag ratio vs
    // their own trailing average -- the same signal as the "Volume
    // surges" row, but visible where the eye already is. Called after
    // both the treemap renders and the insights arrive (either can land
    // first), so it has to be safe to re-run: it clears its own badges.
    window.applyTileBadges = function() {
        var svg = document.querySelector('#svg_container svg');
        if (!svg) return;
        svg.querySelectorAll('.tile-badge').forEach(function(el) { el.remove(); });

        svg.querySelectorAll('rect[symbol]').forEach(function(rect) {
            var ratio = surgeFlags[rect.getAttribute('symbol')];
            var title = rect.parentNode.querySelector('title');
            if (title) {
                if (title.dataset.base === undefined) title.dataset.base = title.textContent;
                title.textContent = title.dataset.base + (ratio === undefined ? '' :
                    '\nVolume: ' + ratio.toFixed(1) + 'x trailing ' + surgeRatio + '-day avg' + (asOfDate ? ' (' + formatDate(asOfDate) + ')' : ''));
            }
            if (ratio === undefined) return;

            var w = Number(rect.getAttribute('width'));
            var ns = 'http://www.w3.org/2000/svg';
            var g = document.createElementNS(ns, 'g');
            g.setAttribute('class', 'tile-badge');
            g.style.pointerEvents = 'none'; // clicks still reach the tile underneath

            var label = ratio.toFixed(1) + 'x';
            var h = Number(rect.getAttribute('height'));
            if (w >= 52 && h >= 30) {
                var bw = 8 + label.length * 6.5;
                var pill = document.createElementNS(ns, 'rect');
                pill.setAttribute('x', w - bw - 4); pill.setAttribute('y', 4);
                pill.setAttribute('width', bw); pill.setAttribute('height', 16);
                pill.setAttribute('rx', 8);
                pill.style.fill = 'var(--accent)';
                var txt = document.createElementNS(ns, 'text');
                txt.setAttribute('x', w - 4 - bw / 2); txt.setAttribute('y', 15.5);
                txt.setAttribute('text-anchor', 'middle');
                txt.setAttribute('font-size', 10); txt.setAttribute('font-weight', 500);
                txt.style.fill = '#fff';
                txt.textContent = label;
                g.appendChild(pill); g.appendChild(txt);
            } else if (w >= 12 && h >= 12) {
                // Too small for a label -- a dot still says "look here".
                var dot = document.createElementNS(ns, 'circle');
                dot.setAttribute('cx', w - 6); dot.setAttribute('cy', 6); dot.setAttribute('r', 3.5);
                dot.style.fill = 'var(--accent)';
                g.appendChild(dot);
            }
            rect.parentNode.appendChild(g);
        });
    };

    // One compact line: a label, then the top few symbols as chips. The
    // full detail (company, volume, price, short % vs avg) is in the chip
    // tooltip and the expandable lists below.
    function buildStripRow(label, rows, chipText, tooltip, date) {
        var row = document.createElement('div');
        row.className = 'insights-strip-row';

        var name = document.createElement('span');
        name.className = 'insights-strip-label';
        name.textContent = label;
        row.appendChild(name);

        var chips = document.createElement('span');
        chips.className = 'insights-chips';
        if (!rows.length) {
            var none = document.createElement('span');
            none.className = 'insights-empty';
            none.textContent = 'Nothing notable';
            chips.appendChild(none);
        }
        rows.slice(0, STRIP_COUNT).forEach(function(r) {
            var chip = document.createElement('a');
            chip.href = '#';
            chip.className = 'insights-chip';
            chip.title = tooltip(r);
            var sym = document.createElement('strong');
            sym.textContent = r.symbol;
            chip.appendChild(sym);
            chip.appendChild(document.createTextNode(' ' + chipText(r)));
            chip.addEventListener('click', function(e) {
                e.preventDefault();
                loadModal();
                populateBarChart(r.symbol, date);
            });
            chips.appendChild(chip);
        });
        row.appendChild(chips);
        return row;
    }

    function fullTooltip(r) {
        var parts = [(r.company || r.symbol),
            r.volume_ratio.toFixed(1) + 'x avg volume (' + formatVolume(r.volume) + ')',
            'Short ' + r.short_pct.toFixed(1) + '% vs ' + r.avg_short_pct.toFixed(1) + '% avg'];
        if (r.price_change_pct !== null) parts.push(signed(r.price_change_pct) + '% price');
        return parts.join('\n');
    }

    window.renderInsights = function(data) {
        var panel = document.getElementById('insights-panel');
        var strip = document.getElementById('insights-strip');
        var body = document.getElementById('insights-body');
        strip.innerHTML = '';
        body.innerHTML = '';

        panel.classList.remove('hidden');
        surgeFlags = (data && data.surge_flags) || {};
        surgeRatio = (data && data.lookback_days) || 20;
        asOfDate = data && data.as_of;
        window.applyTileBadges();
        // Say what's wrong rather than vanishing -- a silently missing
        // panel is indistinguishable from "nothing unusual today".
        function showMessage(text) {
            document.getElementById('insights-asof').textContent = '';
            var p = document.createElement('p');
            p.className = 'insights-empty';
            p.textContent = text;
            strip.appendChild(p);
            document.getElementById('insights-toggle').classList.add('hidden');
        }
        if (!data || data.error) {
            showMessage('Couldn\u2019t load unusual activity' + (data && data.error ? ': ' + data.error : '.'));
            return;
        }
        if (!data.as_of) {
            showMessage('No data on or before this date.');
            return;
        }
        if (!data.compared) {
            showMessage('Not enough trading history before ' + formatDate(data.as_of) +
                ' to compare against (needs at least 10 prior days per symbol).');
            return;
        }
        document.getElementById('insights-toggle').classList.remove('hidden');
        document.getElementById('insights-asof').textContent =
            'As of ' + formatDate(data.as_of) + ' · each symbol vs. its own trailing ' +
            data.lookback_days + '-day average';

        strip.appendChild(buildStripRow('Volume surges', data.volume_surges,
            function(r) { return r.volume_ratio.toFixed(1) + 'x'; }, fullTooltip, data.as_of));
        strip.appendChild(buildStripRow('Short % jumps', data.short_jumps,
            function(r) { return '\u25b2' + r.short_change_pts.toFixed(0) + ' pts'; }, fullTooltip, data.as_of));
        strip.appendChild(buildStripRow('Short % drops', data.short_drops,
            function(r) { return '\u25bc' + Math.abs(r.short_change_pts).toFixed(0) + ' pts'; }, fullTooltip, data.as_of));

        body.appendChild(buildList('Volume surges', 'Today’s volume vs. average', data.volume_surges,
            function(r) { return r.volume_ratio.toFixed(1) + 'x'; },
            function(r) {
                var text = formatVolume(r.volume) + ' shares';
                return r.price_change_pct === null ? text : text + ' \u00b7 ' + signed(r.price_change_pct) + '% price';
            }, data.as_of));
        body.appendChild(buildList('Short % jumps', 'Biggest rise vs. own average', data.short_jumps,
            function(r) { return signed(r.short_change_pts) + ' pts'; },
            function(r) { return r.short_pct.toFixed(1) + '% vs ' + r.avg_short_pct.toFixed(1) + '% avg'; }, data.as_of));
        body.appendChild(buildList('Short % drops', 'Biggest fall vs. own average', data.short_drops,
            function(r) { return signed(r.short_change_pts) + ' pts'; },
            function(r) { return r.short_pct.toFixed(1) + '% vs ' + r.avg_short_pct.toFixed(1) + '% avg'; }, data.as_of));
    };

    // Only depends on the end date, volume floor and ETF selection -- not
    // on the % buckets or start date -- so skip the round trip when none
    // of those changed (e.g. toggling a bucket checkbox).
    window.loadInsights = function(endDate, minVol, funds) {
        var key = [endDate, minVol, funds.join(',')].join('|');
        if (key === lastKey) return;
        lastKey = key;
        fetch('/insights/' + endDate + '/' + minVol + '/' + funds.join(','))
            .then(function(res) { return res.json(); })
            .then(function(data) { if (key === lastKey) window.renderInsights(data); })
            .catch(function(err) {
                console.error('Failed to load insights:', err);
                lastKey = null;
                window.renderInsights({error: err.message});
            });
    };

    var KEY = 'insightsExpanded';
    function setExpanded(open) {
        document.getElementById('insights-details').classList.toggle('hidden', !open);
        var t = document.getElementById('insights-toggle');
        t.setAttribute('aria-expanded', open);
        t.textContent = open ? 'Hide details' : 'Details';
        try { localStorage.setItem(KEY, open ? '1' : '0'); } catch (e) {}
    }
    document.addEventListener('DOMContentLoaded', function() {
        var open = false;
        try { open = localStorage.getItem(KEY) === '1'; } catch (e) {}
        setExpanded(open);
        document.getElementById('insights-toggle').addEventListener('click', function() {
            setExpanded(document.getElementById('insights-details').classList.contains('hidden'));
        });
    });
})();
