import json
from pathlib import Path

from app.core.job_runner.nvflare_jobs.apis import observation_snapshot as module


def test_strip_fields_top_removes_id_and_subject_reference_only():
    value = {
        "id": "o1",
        "subject": {"reference": "Patient/1", "display": "Patient"},
        "status": "final",
    }
    assert module.strip_fields_top(value) == {
        "subject": {"display": "Patient"},
        "status": "final",
    }


def test_merge_and_finalize_collect_unique_values_and_nested_keys():
    accumulator = module.merge(None, {"code": {"text": "A"}, "values": [1, 2, 1]})
    accumulator = module.merge(accumulator, {"code": {"text": "B"}, "values": [2, 3]})
    result = module.finalize(accumulator)
    assert result["code"]["text"] == ["A", "B"]
    assert result["values"]["__values__"] == [1, 2, 3]


def test_parse_json_bytes_accepts_object_array_and_ndjson():
    assert module.parse_json_bytes(b'{"a":1}') == [{"a": 1}]
    assert module.parse_json_bytes(b'[{"a":1}]') == [{"a": 1}]
    assert module.parse_json_bytes(b'{"a":1}\ninvalid\n{"b":2}\n') == [{"a": 1}, {"b": 2}]


def test_collect_observations_reads_bundle_and_standalone_files(tmp_path):
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Observation", "id": "o1", "status": "final"}},
            {"resource": {"resourceType": "Patient", "id": "p1"}},
        ],
    }
    (tmp_path / "bundle.json").write_text(json.dumps(bundle))
    (tmp_path / "obs.json").write_text(
        json.dumps({"resourceType": "Observation", "id": "o2", "valueString": "x"})
    )
    observations = module.collect_observations(str(tmp_path))
    assert observations == [
        {"resourceType": "Observation", "status": "final"},
        {"resourceType": "Observation", "valueString": "x"},
    ]


def test_run_writes_global_snapshot(tmp_path):
    source = tmp_path / "obs.json"
    source.write_text(json.dumps({"resourceType": "Observation", "id": "o1", "status": "final"}))
    output = tmp_path / "out.json"
    module.run(str(source), str(output))
    result = json.loads(output.read_text())
    assert result["resourceType"] == ["Observation"]
    assert result["status"] == ["final"]
