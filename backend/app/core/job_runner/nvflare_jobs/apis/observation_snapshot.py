import json, os
from typing import Any, Dict, List

# This script builds a single "Observation snapshot" from FHIR JSON.
# It walks one file or a directory of files, pulls out Observation resources,
# strips IDs and subject references, and merges all fields into one object.
# For each field:
#   - nested objects are merged by key
#   - lists of objects are merged by key
#   - lists of primitives are collected into a unique set under "__values__"
#   - primitive values are collected into a unique set
# At the end, sets are turned into sorted lists so the output is valid JSON.

def is_primitive(x: Any) -> bool:
    # True if value is JSON-primitive-like (we also treat None as a value)
    return isinstance(x, (str, int, float, bool)) or x is None

def strip_fields_top(o: dict) -> dict:
    # Remove fields we don't want to aggregate at the top level
    out = dict(o)
    out.pop("id", None)  # we don't want individual resource IDs
    subj = out.get("subject")
    if isinstance(subj, dict):
        # drop just the reference; keep any other subject fields if present
        subj.pop("reference", None)
        if not subj:
            out.pop("subject", None)
    return out

def merge(a: Any, b: Any) -> Any:
    # Merge value b into accumulator a, returning the accumulator.
    # Dicts: deep-merge by key
    # Lists: merge list items (dicts by key; primitives collected under "__values__")
    # Primitives: collect unique primitives in a set
    if isinstance(b, dict):
        if not isinstance(a, dict):
            a = {}
        for k, v in b.items():
            a[k] = merge(a.get(k), v)
        return a

    if isinstance(b, list):
        # We store merged list content in a dict:
        # - dict elements merged by their keys
        # - primitive elements collected under "__values__"
        if not isinstance(a, dict):
            a = {}
        for el in b:
            if isinstance(el, dict):
                for k, v in el.items():
                    a[k] = merge(a.get(k), v)
            elif isinstance(el, list):
                # Nested lists collapse into "__values__" as unique primitives later
                a["__values__"] = merge(a.get("__values__"), el)
            else:
                s = a.get("__values__")
                if not isinstance(s, set):
                    s = set()
                s.add(el)
                a["__values__"] = s
        return a

    if is_primitive(b):
        # Collect unique primitive values
        if not isinstance(a, set):
            a = set()
        a.add(b)
        return a

    # Unknown types pass through unchanged
    return a

def finalize(node: Any) -> Any:
    # Convert sets to sorted lists and recurse into dicts/lists
    if isinstance(node, dict):
        return {k: finalize(v) for k, v in node.items()}
    if isinstance(node, set):
        try:
            return sorted(list(node), key=lambda x: (type(x).__name__, str(x)))
        except Exception:
            return list(node)
    if isinstance(node, list):
        return [finalize(x) for x in node]
    return node

def iter_bundle_resources(obj: Any):
    # Yield resources from a FHIR Bundle
    if not isinstance(obj, dict):
        return
    if obj.get("resourceType") == "Bundle":
        for e in obj.get("entry") or []:
            r = e.get("resource")
            if isinstance(r, dict):
                yield r

def parse_json_bytes(buf: bytes) -> List[dict]:
    # Accepts:
    #   - a single JSON object (returns [obj])
    #   - a JSON array (returns array)
    #   - NDJSON (returns list of parsed lines)
    txt = buf.decode("utf-8", errors="replace")
    try:
        data = json.loads(txt)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
    except Exception:
        pass
    out = []
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out

def collect_observations(path: str) -> List[dict]:
    # Read a file or walk a directory; collect Observation resources only
    obs: List[dict] = []
    if os.path.isdir(path):
        files = []
        for root, _, fs in os.walk(path):
            for f in fs:
                if f.lower().endswith(".json"):
                    files.append(os.path.join(root, f))
    else:
        files = [path]

    for p in files:
        with open(p, "rb") as fh:
            for obj in parse_json_bytes(fh.read()):
                if isinstance(obj, dict) and obj.get("resourceType") == "Bundle":
                    for r in iter_bundle_resources(obj):
                        if r.get("resourceType") == "Observation":
                            obs.append(strip_fields_top(r))
                elif isinstance(obj, dict) and obj.get("resourceType") == "Observation":
                    obs.append(strip_fields_top(obj))
    return obs

def build_global_snapshot(observations: List[dict]) -> dict:
    # Merge all Observations into one snapshot object
    acc: Dict[str, Any] = {}
    for ob in observations:
        acc = merge(acc, ob)
    return finalize(acc)

def run(input_path: str, out_path: str):
    # Orchestrate: read input, build snapshot, write JSON
    observations = collect_observations(input_path)
    snapshot = build_global_snapshot(observations)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    # CLI: python observation_snapshot.py <input_json_or_dir> [out_json]
    import sys
    if len(sys.argv) not in (2, 3):
        print("usage: python observation_snapshot.py <input_json_or_dir> [out_json]")
        sys.exit(2)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else "observation_snapshot_global.json"
    run(inp, out)
