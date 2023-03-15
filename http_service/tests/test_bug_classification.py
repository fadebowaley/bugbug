# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import gzip
import json
import time

import orjson

from bugbug_http.app import API_TOKEN


def retrieve_compressed_reponse(response):
    # Response is of type "<class 'flask.wrappers.Response'>" -  Flask Client's  Response
    # Not applicable for "<class 'requests.models.Response'> "
    if response.headers["Content-Encoding"] == "gzip":
        return orjson.loads(gzip.decompress(response.data))
    return response.json


def test_model_predict_id(client, jobs, add_result, responses):
    bug_id = "123456"
    result = {
        "class": "Core::Layout",
        "extra_data": {"index": 0, "prob": [0.0032219779677689075]},
    }

    responses.add(
        responses.GET,
        f"https://bugzilla.mozilla.org/rest/bug?id={bug_id}&include_fields=last_change_time&include_fields=id",
        status=200,
        json={
            "bugs": [{"id": bug_id, "last_change_time": time.time()}],
        },
    )

    def do_request():
        return client.get(
            "/component/predict/123456",
            headers={API_TOKEN: "test"},
        )

    rv = do_request()
    assert rv.status_code == 202
    assert retrieve_compressed_reponse(rv) == {"ready": False}

    # request still not ready
    rv = do_request()
    assert rv.status_code == 202
    assert retrieve_compressed_reponse(rv) == {"ready": False}
    assert len(jobs) == 1

    # now it's ready
    keys = next(iter(jobs.values()))
    add_result(keys[0], result)

    rv = do_request()
    assert rv.status_code == 200
    assert retrieve_compressed_reponse(rv) == result


def test_model_predict_id_github(client, jobs, add_result, responses):
    issue_id = "12345"
    result = {
        "prob": [0.11845558881759644, 0.8815444111824036],
        "index": 1,
        "class": 1,
        "extra_data": {},
    }

    responses.add(
        responses.GET,
        f"https://api.github.com/repos/webcompat/web-bugs/issues/{issue_id}",
        status=200,
        json={"number": issue_id, "updated_at": time.time()},
    )

    def do_request():
        return client.get(
            "/needsdiagnosis/predict/github/webcompat/web-bugs/12345",
            headers={API_TOKEN: "test"},
        )

    rv = do_request()
    assert rv.status_code == 202
    assert retrieve_compressed_reponse(rv) == {"ready": False}

    # request still not ready
    rv = do_request()
    assert rv.status_code == 202
    assert retrieve_compressed_reponse(rv) == {"ready": False}
    assert len(jobs) == 1

    # now it's ready
    keys = next(iter(jobs.values()))
    add_result(keys[0], result)

    rv = do_request()
    assert rv.status_code == 200
    assert retrieve_compressed_reponse(rv) == result


def test_model_predict_batch(client, jobs, add_result, add_change_time, responses):
    bug_ids = [123, 456]
    result = {
        "class": "Core::Layout",
        "extra_data": {"index": 0, "prob": [0.0032219779677689075]},
    }
    change_time = str(time.time())

    responses.add(
        responses.GET,
        "https://bugzilla.mozilla.org/rest/bug?id=123,456&include_fields=id&include_fields=last_change_time",
        status=200,
        json={
            "bugs": [
                {"id": bug_id, "last_change_time": change_time} for bug_id in bug_ids
            ],
        },
    )

    def do_request():
        return client.post(
            "/component/predict/batch",
            data=json.dumps({"bugs": bug_ids}),
            headers={API_TOKEN: "test"},
        )

    rv = do_request()
    assert rv.status_code == 202
    assert retrieve_compressed_reponse(rv) == {
        "bugs": {str(bug_id): {"ready": False} for bug_id in bug_ids}
    }
    assert len(jobs) == 1

    # one of the bugs is ready
    keys = next(iter(jobs.values()))
    for key in keys:
        # Need to set change times in redis or results will be invalidated.
        add_change_time(key, change_time)

    add_result(keys[0], result, change_time=change_time)

    rv = do_request()
    assert rv.status_code == 202
    assert retrieve_compressed_reponse(rv) == {
        "bugs": {str(bug_ids[0]): result, str(bug_ids[1]): {"ready": False}}
    }

    # now they're both ready
    add_result(keys[1], result, change_time=change_time)

    rv = do_request()
    assert rv.status_code == 200
    assert retrieve_compressed_reponse(rv) == {
        "bugs": {str(bug_id): result for bug_id in bug_ids}
    }


def test_empty_batch(client):
    """Start with a blank database."""

    rv = client.post(
        "/component/predict/batch",
        data=json.dumps({"bugs": []}),
        headers={API_TOKEN: "test"},
    )

    assert rv.status_code == 400
    assert rv.json == {"errors": {"bugs": ["min length is 1"]}}


def test_non_int_batch(client):
    """Start with a blank database."""

    bugs = ["1", "2", "3"]

    rv = client.post(
        "/component/predict/batch",
        data=json.dumps({"bugs": bugs}),
        headers={API_TOKEN: "test"},
    )

    assert rv.status_code == 400
    assert rv.json == {
        "errors": {
            "bugs": [
                {
                    "0": ["must be of integer type"],
                    "1": ["must be of integer type"],
                    "2": ["must be of integer type"],
                }
            ]
        }
    }


def test_unknown_model(client):
    """Start with  a blank database,"""
    bugs = [1, 2, 3]
    unknown_model = "unknown_model"

    rv = client.post(
        f"/{unknown_model}/predict/batch",
        data=json.dumps({"bugs": bugs}),
        headers={API_TOKEN: "test"},
    )

    assert rv.status_code == 404
    assert rv.json == {"error": f"Model {unknown_model} doesn't exist"}


def test_no_api_key(client):
    """Start with an empty database,"""

    bugs = [1, 2, 3]

    rv = client.post(
        "/component/predict/batch",
        data=json.dumps({"bugs": bugs}),
        headers={},
    )

    assert rv.status_code == 401
    assert rv.json == {"message": "Error, missing X-API-KEY"}

# Add The new Test Model for predicting_id_missing Bug
def test_model_predict_id_missing_bug(client, responses):
    bug_id = "7890231"

    responses.add(
        responses.GET,
        f"https://bugzilla.mozilla.org/rest/bug?id={bug_id}&include_fields=last_change_time&include_fields=id",
        status=404, )    
    def do_request():
        return client.get(
            "/component/predict/7890231",
            headers={API_TOKEN: "test"},
        )

    rv = do_request()
    assert rv.status_code == 404
    assert rv.json == {"message": f"Bug {bug_id} not found"}

