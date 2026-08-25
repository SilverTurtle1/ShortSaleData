import csv
import json
import os

import pandas as pd
from flask import Flask, render_template, jsonify, session

from finra import fetch_ssdata_raw, build_ssdata, get_company_name
from flask_session import Session

# Initiate Flask Application
app = Flask(__name__)
# Required for signed session cookies; without this Flask-Session issues
# unsigned session IDs that can be guessed or swapped by a client.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
# Flask-Session's filesystem backend does not sign the session-id cookie by
# default (use_signer=False) even with a secret_key set, which leaves the
# raw session ID guessable/swappable. This turns signing on.
app.config["SESSION_USE_SIGNER"] = True
Session(app)

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


@app.route('/treemap/<start_date>/<end_date>/<min_vol>/<perc_short>/<etfs>')
def treemap(start_date=0, end_date=0, min_vol=5000000, perc_short=50, etfs=0):
    if not start_date:
        return jsonify({"error": "Could not load data for " + start_date})

    try:
        # The FINRA/Polygon fetch is only re-run when the date range changes;
        # min_vol/perc_short (the slider) are applied as a cheap in-memory
        # filter below on every request, so moving the slider never re-hits
        # the network or the database.
        if (session.get('rawdata') is None
                or session.get('startdate') != start_date
                or session.get('enddate') != end_date):
            raw_df = fetch_ssdata_raw(start_date, end_date)
            session['startdate'] = start_date
            session['enddate'] = end_date
            session['rawdata'] = raw_df.to_json(orient='records')
        else:
            raw_df = pd.read_json(session['rawdata'])

        finraList = build_ssdata(raw_df, min_vol, perc_short, etfs)
        finra_df, finra_detail = finraList
        session['dataDetail'] = finra_detail

        # No symbols matched the current filter -- a normal outcome for a
        # strict min_vol/perc_short combination, not an error. Return a
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
    finra_detail = session['dataDetail']
    temp_df = pd.read_json(finra_detail)
    temp_df = temp_df.loc[temp_df['Symbol'] == symbol]
    temp_df["Date"] = pd.to_datetime(temp_df["Date"], format='%Y%m%d').dt.strftime('%m-%d-%Y')
    temp_df['Date'] = temp_df['Date'].astype(str)
    temp_df['CompanyName'] = get_company_name(symbol)
    finra_detail = temp_df.to_json(orient='records')
    return finra_detail


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
