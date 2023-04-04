from flask import Flask, render_template, request, redirect, jsonify, make_response
import json
import csv
from finra import get_ssdata

# Initiate Flask Application
app = Flask(__name__)

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
    get_ssdata("20230403", "20230403")
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    get_ssdata("20230403", "20230403")
    return render_template('index.html')

@app.route('/dataset/<start_date>/<end_date>')
def dataset(start_date=0, end_date=0):
    if start_date:
        # fetching data for selected date range from FINRA
        return get_ssdata(start_date, end_date)
        # return render_template('index.html')
        # return jsonify({"success": "Data loaded for "+ start_date})
    else:
        return jsonify({"error": "Could not load data for " + start_date})


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
    # Threaded option to enable multiple instances for multiple user access support
    app.run(debug=True, port=5000)



