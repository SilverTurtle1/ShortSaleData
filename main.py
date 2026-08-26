import csv
import json
import os

import pandas as pd
from flask import Flask, render_template, jsonify, request

from finra import fetch_ssdata_raw, build_ssdata, get_company_name
from reports import REPORTS, run_report

# Initiate Flask Application
app = Flask(__name__)

# Caches the most recently fetched raw date range and the most recently
# built detail view, in process memory rather than in a per-session,
# JSON-serialized cookie/file. The old approach (Flask-Session, filesystem
# backend) meant every single /treemap request -- even just toggling a
# checkbox with the exact same date range already cached -- paid the cost
# of a full JSON serialize or deserialize of the whole raw dataset, and a
# disk write, every time. For a wide date range that redundant churn was
# enough on its own to push the web service (512MB) into repeated
# out-of-memory crashes under real use.
#
# This trades strict per-visitor isolation for that: two people using the
# app at the same moment with different date ranges could momentarily
# clobber each other's cached view. Acceptable here -- this is a
# personal/small-group tool, not a public multi-tenant app -- but worth
# knowing if that ever changes.
_cache = {
    "start_date": None,
    "end_date": None,
    "raw_df": None,
    "detail_json": None,
}

# Import DataFrame
# PATH_IN = r'static\data\miserables.json'
CSV_IN = r'flare-2.csv'
JSON_OUT = r'SSData.json'


def csv_to_json(csvFilePath, jsonFilePath):
    jsonArray = []

    # read csv file
    with open(csvFilePath, encoding='utf-8') as csvf:
        # load csv file data using csv library's dictionary reader
        csvReader = csv.DictReader(csvf)

        # convert each csv row into python dict
        for row in csvReader:
            # add this python dict to json array
            jsonArray.append(row)

    # convert python jsonArray to JSON String and write to file
    with open(jsonFilePath, 'w', encoding='utf-8') as jsonf:
        jsonString = json.dumps(jsonArray, indent=4)
        jsonf.write(jsonString)


# Routing do define url
@app.route('/')
def index():
    # get_ssdata("20230404", "20230404")
    return render_template('index.html')


@app.route('/treemap/<start_date>/<end_date>/<min_vol>/<perc_buckets>/<etfs>')
def treemap(start_date=0, end_date=0, min_vol=5000000, perc_buckets="50plus,40to50,30to40,under30", etfs=0):
    if not start_date:
        return jsonify({"error": "Could not load data for " + start_date})

    try:
        # The FINRA/Polygon fetch is only re-run when the date range changes;
        # min_vol/perc_buckets (the filter toggles) are applied as a cheap
        # in-memory filter below on every request, so toggling them never
        # re-hits the network or the database.
        if (_cache["raw_df"] is None
                or _cache["start_date"] != start_date
                or _cache["end_date"] != end_date):
            _cache["raw_df"] = fetch_ssdata_raw(start_date, end_date)
            _cache["start_date"] = start_date
            _cache["end_date"] = end_date
        raw_df = _cache["raw_df"]

        finraList = build_ssdata(raw_df, min_vol, perc_buckets, etfs)
        finra_df, finra_detail = finraList
        _cache["detail_json"] = finra_detail

        # No symbols matched the current filter -- a normal outcome for a
        # strict min_vol/perc_buckets combination, not an error. Return a
        # valid empty array rather than an {"error": ...} object, since the
        # latter crashes the treemap renderer (it expects an array) and
        # triggers the frontend's retry-with-a-different-date-range fallback.
        if finraList == ['[]', '[]']:
            return '[]'

        temp_df = pd.read_json(finra_df)
        temp_df = temp_df[temp_df["Fund"].isin(list(etfs.split(",")))]
        finra_df = temp_df.to_json(orient='records')
        return finra_df

    except Exception as e:
        print(e)
        return jsonify({"error": str(e)})


@app.route('/barchart/<symbol>')
def barchart(symbol):
    finra_detail = _cache["detail_json"]
    temp_df = pd.read_json(finra_detail)
    temp_df = temp_df.loc[temp_df['Symbol'] == symbol]
    temp_df["Date"] = pd.to_datetime(temp_df["Date"], format='%Y%m%d').dt.strftime('%m-%d-%Y')
    temp_df['Date'] = temp_df['Date'].astype(str)
    temp_df['CompanyName'] = get_company_name(symbol)
    finra_detail = temp_df.to_json(orient='records')
    return finra_detail


@app.route('/reports')
def reports_page():
    return render_template('reports.html', reports=REPORTS)


@app.route('/reports/run/<report_key>')
def reports_run(report_key):
    if report_key not in REPORTS:
        return jsonify({"error": "Unknown report"}), 404

    try:
        param_names = [p["name"] for p in REPORTS[report_key]["params"]]
        raw_params = {name: request.args.get(name) for name in param_names}
        columns, rows = run_report(report_key, raw_params)
        return jsonify({"columns": columns, "rows": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/get-json', methods=['GET', 'POST'])
def get_json():
    ''' Send JSON data to Javascript '''
    # Import Data
    csv_to_json(CSV_IN, JSON_OUT)
    with open(JSON_OUT) as f:
        json_to = json.load(f)
    return jsonify(json_to)


# @app.route('/update-data', methods=['GET', 'POST'])
# def update_data():
#     get_ssdata("2022/12/08")


if __name__ == '__main__':
    # threaded=True allows multiple instances for multiple user access support
    app.run(debug=True, port=5000, threaded=True)
