// FINRA doesn't publish a trading day's short-volume file until roughly
// mid-afternoon Pacific time -- shared by any page that needs to know
// whether "today" is safe to default to or allow selecting.
function isTodayPublished() {
    var pacificHour = parseInt(
        new Date().toLocaleString('en-US', {timeZone: 'America/Los_Angeles', hour: 'numeric', hour12: false}),
        10
    );
    return pacificHour >= 15;
}

// Pacific calendar date, `daysAgo` days back from now, as YYYY-MM-DD --
// the format <input type="date"> requires for its min/max/value.
function pacificDateISO(daysAgo) {
    daysAgo = daysAgo || 0;
    var d = new Date(Date.now() - daysAgo * 86400000);
    var parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Los_Angeles',
        year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(d);
    var map = {};
    parts.forEach(function(p) { map[p.type] = p.value; });
    return map.year + '-' + map.month + '-' + map.day;
}
