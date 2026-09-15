# duality_py
Python code for duality FastAPI container

# index
1. POST /clients/connection/status — list_clients_status [app/api/routes/ClientRoutes.py:22]

2. POST /clients/participation/status — list_clients_status [app/api/routes/ClientRoutes.py:108]

3. POST /filters/fetch_filters — fetch_filters [app/api/routes/FilterRoutes.py:53]

4. POST /filters/fetch_single_filter — fetch_single_filter [app/api/routes/FilterRoutes.py:19]

5. POST /functions/jobs/submit — submit_survivability [app/api/routes/FunctionRoutes.py:104]

6. POST /functions/participation/submit — submit_participation [app/api/routes/FunctionRoutes.py:140]

7. POST /functions/supported_functions — fetch_supported_functions [app/api/routes/FunctionRoutes.py:82]

8. POST /jobs/job_results — get_job_results_by_nvflare_id [app/api/routes/JobRoutes.py:50]

9. POST /jobs/job_status — job_status [app/api/routes/JobRoutes.py:16]

10. POST /nvflare/client/emit_progress — submit_participation [app/api/routes/NVFlareRoutes.py:58]

11. POST /nvflare/job_history — fetch_nvflare_job_history [app/api/routes/NVFlareRoutes.py:20]

# B. Endpoints

## 1) POST /clients/connection/status — list_clients_status (app/api/routes/ClientRoutes.py:22)

```python

@router.post("/clients/connection/status", include_in_schema=False)

async def list_clients_status(request: Request):

    try:

        body = await request.json()

    except Exception:

        body = {}

    try:

        # Always get current connection snapshot

        clients_snapshot = NVFlareClientSnapshot().get_clients()

        print(f"NVFlareRoutes: Snapshot clients returned: {clients_snapshot}", flush=True)

        participation_status = body.get("participation_status")

        # If participation payload is not present or malformed, return connection-only snapshot

        if not isinstance(participation_status, dict):

            print("NVFlareRoutes: No participation_status provided; returning connection status only.", flush=True)

            return JSONResponse({"clients": clients_snapshot})

        filters = participation_status.get("filters")

        funcs_raw = participation_status.get("functions")

        # Validate functions map; if invalid or empty, return connection-only snapshot

        if not isinstance(funcs_raw, dict) or len(funcs_raw) == 0:

            print("NVFlareRoutes: participation_status.functions missing/invalid; returning connection status only.", flush=True)

            return JSONResponse({"clients": clients_snapshot})

        # Sanitize to UPPER function ids and stringified arg values

        functions_map: Dict[str, Dict[str, str]] = {}

        for k, v in funcs_raw.items():

            fn_id = str(k).strip().upper()

            if not fn_id:

                continue

            arg_map: Dict[str, str] = {}

            if isinstance(v, dict):

                for ak, av in v.items():

                    arg_map[str(ak)] = "" if av is None else str(av)

            functions_map[fn_id] = arg_map

        if not functions_map:

            print("NVFlareRoutes: participation_status.functions empty after sanitize; returning connection status only.", flush=True)

            return JSONResponse({"clients": clients_snapshot})

        # Resolve filter id (do not persist new filters here)

        filters_manager = FiltersManager(filters=filters)

        filter_id = filters_manager.get_id_by_filters()

        print(f"NVFlareRoutes: Resolved filter_id={filter_id}", flush=True)

        # If a filter id exists, enrich snapshot with participation confirmation

        if filter_id:

            db = ParticipationManager()

            try:

                participation_rows = db.list_client_participation_status(

                    functions=functions_map,

                    filter_id=filter_id,

                    clients_snapshot=clients_snapshot,

                )

                print(f"NVFlareRoutes: Participation rows fetched from DB: {participation_rows}", flush=True)

                participation_map = {}

                for row in participation_rows:

                    name = row.get("client_name")

                    if name:

                        participation_map[name.strip()] = row["confirmation"]

FiltersManager.get_id_by_filters — Lookup a filter_id by hash (function-agnostic).
Returns the ID if found, or None if not. Does not create new rows. — see FiltersManager

                print(f"NVFlareRoutes: Participation map built: {participation_map}", flush=True)

                for c in clients_snapshot:

                    name = c.get("client_name", "").strip()

                    c["participation"] = participation_map.get(name, None)

                    print(f"NVFlareRoutes: Updated client entry: {c}", flush=True)

            finally:

ParticipationManager.list_client_participation_status — retrieves data — see ParticipationManager

                db.complete()

                print("NVFlareRoutes: ParticipationManager connection closed.", flush=True)

        print(f"NVFlareRoutes: Final clients list returned: {clients_snapshot}", flush=True)

        return JSONResponse({"clients": clients_snapshot})

    except Exception:

        return JSONResponse(

            content={"error": f"Failed to fetch client status: {traceback.format_exc().splitlines()}"},

            status_code=500,

        )

```

## 2) POST /clients/participation/status — list_clients_status (app/api/routes/ClientRoutes.py:108)

```python

@router.post("/clients/participation/status", include_in_schema=False)

async def list_clients_status(request: Request):

    body = await request.json()

    filters = body.get("filters")

    if not filters:

        return JSONResponse(content={"error": "filters are required."}, status_code=400)

    # REQUIRE new map structure: { "<FUNCTION_ID>": { ...args... }, ... }

    funcs_raw = body.get("functions")

    if not isinstance(funcs_raw, dict):

        return JSONResponse(

            content={"status": "functions must be an object mapping function_id -> { args }"},

            status_code=400,

        )

    # Sanitize to UPPER function ids and stringified arg values

    functions_map: Dict[str, Dict[str, str]] = {}

    for k, v in funcs_raw.items():

        fn_id = str(k).strip().upper()

        if not fn_id:

            continue

        arg_map: Dict[str, str] = {}

        if isinstance(v, dict):

            for ak, av in v.items():

                # Keep property names as provided; values stringified

                arg_map[str(ak)] = "" if av is None else str(av)

        functions_map[fn_id] = arg_map

    if not functions_map:

        return JSONResponse(

            content={"status": "functions must contain at least one function"},

            status_code=400,

        )

    try:

        clients = _list_clients_status_for_functions(functions_map, filters)

        return JSONResponse({"clients": clients})

    except Exception:

        return JSONResponse(

            content={"error": f"Failed to fetch client status: {traceback.format_exc().splitlines()}"},

            status_code=500,

        )

```

## 3) POST /filters/fetch_filters — fetch_filters (app/api/routes/FilterRoutes.py:53)

```python

@router.post("/filters/fetch_filters", include_in_schema=False)

async def fetch_filters():

    print(f"NVFlareRoutes: fetch_filters called", flush=True)

    try:

        retriever = MySQLRetriever()

        try:

            filters = retriever.get_all_filters()

            print(f"NVFlareRoutes: fetch_filters retrieved {len(filters)} filters", flush=True)

        finally:

            retriever.complete()

        return JSONResponse(content={"status": "SUCCESS", "filters": filters}, status_code=200)

    except HTTPException:

        raise

    except Exception as e:

        logging.exception("Error while fetching filters")

        print(f"NVFlareRoutes: fetch_filters hit exception {traceback.format_exc().splitlines()}", flush=True)

        return JSONResponse(content={"status": "FAILURE", "error": str(e)}, status_code=500)

```

## 4) POST /filters/fetch_single_filter — fetch_single_filter (app/api/routes/FilterRoutes.py:19)

```python

@router.post("/filters/fetch_single_filter", include_in_schema=False)

async def fetch_single_filter(request: Request):

    print("NVFlareRoutes: fetch_single_filter called", flush=True)

    # Submits a survivability analysis job. Expects a filters object in the body.

    body = await request.json()

    filter_id = body.get("filter_id", "")

    if not filter_id:

        print("NVFlareRoutes: fetch_single_filter missing filter_id in body", flush=True)

        return JSONResponse(content={"status": "Submission must include filter_id"}, status_code=400)

    try:

        filter_id = int(filter_id)   # ensure it's an int

    except (TypeError, ValueError):

        return JSONResponse(content={"status": "filter_id must be an integer"}, status_code=400)

    print(f"NVFlareRoutes: fetch_single_filter called with payload={body}", flush=True)

    try:

        retriever = MySQLRetriever()

        try:

            single_filter = retriever.get_single_filter(filter_id)

            print(f"NVFlareRoutes: fetch_single_filter retrieved {single_filter}", flush=True)

        finally:

            retriever.complete()

        return JSONResponse(content={"status": "SUCCESS", "filter": single_filter}, status_code=200)

    except HTTPException:

        raise

    except Exception as e:

        logging.exception(f"Error while fetching single filter for {filter_id}")

        print(f"NVFlareRoutes: fetch_single_filter hit exception {traceback.format_exc().splitlines()}", flush=True)

        return JSONResponse(content={"status": "FAILURE", "error": str(e)}, status_code=500)

```

## 5) POST /functions/jobs/submit — submit_survivability (app/api/routes/FunctionRoutes.py:104)

```python

@router.post("/functions/jobs/submit", include_in_schema=False)

async def submit_survivability(request: Request):

    print("NVFlareRoutes: submit_survivability called", flush=True)

    # Submits a job with filters + selected functions (as a map of functionId -> args).

    body = await request.json()

    filters = body.get("filters", "")

    if not filters:

        print("NVFlareRoutes: submit_survivability missing filters in payload", flush=True)

        return JSONResponse(content={"status": "Submission must include filters"}, status_code=400)

    functions_raw = body.get("functions_map")

    if functions_raw is None:

        return JSONResponse(content={"status": "Please provide functions"}, status_code=400)

    # Require the new map structure; default/validate lightly.

    if not isinstance(functions_raw, dict):

        return JSONResponse(content={"status": "functions must be an object mapping function_id -> { args }"}, status_code=400)

    try:

        functions_map = _normalize_functions_map(functions_raw)

    except Exception:

        logging.exception("Failed to normalize functions map")

        return JSONResponse(content={"status": "Invalid functions payload"}, status_code=400)

    if not any(str(fid).strip() for fid in functions_map.keys()):

        return JSONResponse(content={"status": "functions must contain at least one function"}, status_code=400)

    service = JobRunnerService.get_instance()

    # Pass the full functions map so configs can be persisted with the job.

    job_id = service.request_job_run(functions_map, filters)

    print(f"NVFlareRoutes: submit_survivability enqueued job {job_id}", flush=True)

    return JSONResponse(content={"job_id": job_id, "status": "QUEUED"}, status_code=200)

```

## 6) POST /functions/participation/submit — submit_participation (app/api/routes/FunctionRoutes.py:140)

```python

@router.post("/functions/participation/submit", include_in_schema=False)

async def submit_participation(request: Request):

    print(f"NVFlareRoutes: submit_participation request recieved: {request}", flush=True)

    body = await request.json()

    # Password protection for non-local builds.

    env = EnvironmentProvider.get_env()

    if env != Environment.LOCAL:

        pw = body.get("$pw", "")

        mysql_config = ResourceConfigProvider.get_mysql_config()

        password_string = mysql_config.password

        if pw != password_string:

            mysql_config = ResourceConfigProvider.get_mysql_config(check_cached=False)

            if pw != mysql_config.password:

                print(f"NVFlareRoutes: submit_participation request recieved a bad password: {pw}", flush=True)

                raise HTTPException(status_code=401, detail="Unauthorized")

    required_fields = ["client_name", "functions_map", "filter_id", "confirmation"]

    for field in required_fields:

        if body.get(field) in (None, "", []):

            print(f"NVFlareRoutes: submit_participation recieved missing request data: {field}", flush=True)

            return JSONResponse(content={"status": f"Please provide {field}"}, status_code=400)

    # Require the new map structure; derive normalized map for persistence.

    funcs_raw = body.get("functions_map")

    if not isinstance(funcs_raw, dict):

        return JSONResponse(content={"status": "functions must be an object mapping function_id -> { args }"}, status_code=400)

    try:

      functions_map = _normalize_functions_map(funcs_raw)

    except Exception:

      logging.exception("Failed to normalize functions map (participation)")

      return JSONResponse(content={"status": "Invalid functions payload"}, status_code=400)

    if not any(str(fid).strip() for fid in functions_map.keys()):

        return JSONResponse(content={"status": "functions must contain at least one function"}, status_code=400)

    conf_raw = str(body["confirmation"]).upper()

    if conf_raw not in Confirmation.__members__.keys():

        print(f"NVFlareRoutes: submit_participation recieved abnormal confirmation string: {conf_raw}", flush=True)

        return JSONResponse(content={"status": "Confirmation must be ACCEPT or REJECT"}, status_code=400)

    conf_enum = Confirmation[conf_raw]

    participation_manager = ParticipationManager()

    try:

        recorded_id = participation_manager.record_participation(

            body["client_name"],

            int(body["filter_id"]),

            functions_map,  # pass full map so configs are captured

            conf_enum,

        )

        if recorded_id is None:

            print("NVFlareRoutes: Failed to persist confirmation.", flush=True)

            return JSONResponse(content={"status": "Failed to persist confirmation."}, status_code=500)

        print(f"NVFlareRoutes: Participation successfully recorded with id {recorded_id}.", flush=True)

        return JSONResponse(content={"status": "Participation recorded", "id": recorded_id}, status_code=200)

    except Exception:

        print(f"NVFlareRoutes: submit_participation hit exception {traceback.format_exc().splitlines()}.", flush=True)

        return JSONResponse(

            content={"status": "Exception occurred while recording participation", "log": traceback.format_exc().splitlines()},

            status_code=400

        )

    finally:

        participation_manager.complete()

```

## 7) POST /functions/supported_functions — fetch_supported_functions (app/api/routes/FunctionRoutes.py:82)

```python

@router.post("/functions/supported_functions", include_in_schema=False)

async def fetch_supported_functions(_request: Request):

    print("NVFlareRoutes: fetch_supported_functions called", flush=True)

    # Returns the list of functions the system currently supports.

    try:

        functions_manager = FunctionsManager()

        try:

            functions = functions_manager.get_supported_functions()

            print(f"NVFlareRoutes: fetch_supported_functions found {len(functions)} functions", flush=True)

        finally:

            functions_manager.complete()

        return JSONResponse(content={"status": "SUCCESS", "functions": functions}, status_code=200)

    except HTTPException:

        raise

    except Exception:

        logging.exception("Error while fetching supported functions")

        print(f"NVFlareRoutes: fetch_supported_functions hit exception {traceback.format_exc().splitlines()}", flush=True)

        return JSONResponse(content={"status": "FAILURE", "error": "Internal error"}, status_code=500)

```

## 8) POST /jobs/job_results — get_job_results_by_nvflare_id (app/api/routes/JobRoutes.py:50)

```python

@router.post("/jobs/job_results", include_in_schema=False)

async def get_job_results_by_nvflare_id(request: Request):

    body = await request.json()

    nvflare_job_id = body.get("nvflare_job_id")

    if not nvflare_job_id:

        return JSONResponse(content={"error": "nvflare_job_id is required."}, status_code=400)

    try:

        jobs_data = NVFlareJobsDataRetriever().retrieve_job_data(nvflare_job_id)

        return JSONResponse({"jobs_data": jobs_data})

    except Exception:

        return JSONResponse(

            content={"error": f"Failed to fetch client status: {traceback.format_exc().splitlines()}"},

            status_code=500,

        )

```

## 9) POST /jobs/job_status — job_status (app/api/routes/JobRoutes.py:16)

```python

@router.post("/jobs/job_status", include_in_schema=False)

async def job_status(request: Request):

    # Fetches the current status and log for a given job_id from job_runner_log.

    body = await request.json()

    job_id = body.get("job_id")

    sql_status_retriever = JobStatusRetriever()

    try:

        status_obj = sql_status_retriever.get_status_by_uuid(job_id)

        response_body = {

            "job_id": job_id,

            "status": status_obj["status"],

            "log": str(status_obj["log"]).splitlines() if status_obj.get("log") else [],

            "last_update": status_obj["update_date"].isoformat() if status_obj.get("update_date") else "None"

        }

        # Only include referenced_by if present and non-empty

        if "referenced_by" in status_obj and status_obj["referenced_by"]:

            response_body["referenced_by"] = status_obj["referenced_by"]

        return JSONResponse(content=response_body, status_code=200)

JobStatusRetriever.get_status_by_uuid — retrieves data — see JobStatusRetriever

    except Exception:

        print(f"NVFlareRoutes: job_status hit exception {traceback.format_exc().splitlines()}", flush=True)

        return JSONResponse(content={

            "job_id": job_id,

            "status": "Exception occured while retrieving job status",

            "log": traceback.format_exc().splitlines()

        }, status_code=400)

    finally:

        sql_status_retriever.complete()

```

## 10) POST /nvflare/client/emit_progress — submit_participation (app/api/routes/NVFlareRoutes.py:58)

```python

@router.post("/nvflare/client/emit_progress", include_in_schema=False)

async def submit_participation(request: Request):

    try:

        body = await request.json()

    except Exception:

        body = await request.body()

    # Password protection for non-local builds

    env = EnvironmentProvider.get_env()

    if env != Environment.LOCAL:

        pw = body.get("$pw", "")

        mysql_config = ResourceConfigProvider.get_mysql_config()

        password_string = mysql_config.password

        if pw != password_string:

            mysql_config = ResourceConfigProvider.get_mysql_config(check_cached=False)

            if pw != mysql_config.password:

                print(f"Bad password received: {pw}", flush=True)

                raise HTTPException(status_code=401, detail="Unauthorized")

    # build manager from NVFlare job_id sent by the webhook

    nvflare_job_id = body.get("job_id")

    mgr = NVFlareClientEmitManager(nvflare_job_id)

    try:

        # log a human-friendly message mapped from numeric codes

        mgr.log_progress_from_payload(body)

        return JSONResponse(content={"status": "ok"})

    finally:

        mgr.complete()

```

## 11) POST /nvflare/job_history — fetch_nvflare_job_history (app/api/routes/NVFlareRoutes.py:20)

```python

@router.post("/nvflare/job_history", include_in_schema=False)

async def fetch_nvflare_job_history(payload: Request):

    print(f"NVFlareRoutes: /nvflare/job_history called with payload={payload}", flush=True)

    # # Normalize: prefer payload.functions; fall back to payload.function; allow missing

    # functions = getattr(payload, "functions", None)

    # if functions is None:

    #     function = getattr(payload, "function", None)

    #     if not function:

    #         print("NVFlareRoutes: No function specified in payload, returning all job history items", flush=True)

    #         functions_list = []

    #     else:

    #         functions_list = [function]

    # else:

    #     functions_list = functions if isinstance(functions, list) else [functions]

    # Optional lower bound on job create_date (ISO string or MySQL-compatible)

    create_date = getattr(payload, "create_date", None)

    try:

        nvflare_jobs_manager = NVFlareJobsManager(None, None, None, create_date)

        try:

            nvflare_jobs = nvflare_jobs_manager.get_nvflare_jobs()

            print(f"NVFlareRoutes: /nvflare/job_history retrieved {len(nvflare_jobs)} jobs", flush=True)

        finally:

            nvflare_jobs_manager.complete()

        return JSONResponse(content={"status": "SUCCESS", "nvflare_jobs": nvflare_jobs}, status_code=200)

    except HTTPException:

        raise

    except Exception:

        logging.exception("Error while fetching NVFlare job history")

        print(f"NVFlareRoutes: /nvflare/job_history hit exception {traceback.format_exc().splitlines()}", flush=True)

        return JSONResponse(content={"status": "FAILURE", "error": "Internal error"}, status_code=500)

```

# C. Common Components

## FiltersManager

Defined at: app/core/mysql/managers/FiltersManager.py

```sql

class FiltersManager:

    def __init__(self, filters: dict | None, status_writer: JobStatusWriter | None = None):

        self.status_writer = status_writer

        safe_status_update(

            self.status_writer,

            JobRunnerStatus.FILTERS_PROCESSING,

            "FiltersManager: Processing filters"

        )

        # Name and normalized conditions derived from the incoming filters payload.

        self.filters_name: str | None = None

        self.conditions: List[Dict[str, str]] = []

        if filters:

            f = filters or {}

            self.filters_name = f.get("name")

            raw_conditions = f.get("conditions")

            # Validate + normalize up front; raises ValueError on any issue

            self.conditions = self._validate_and_normalize_conditions(self.filters_name, raw_conditions)

        # Open a connection/cursor for subsequent lookups and writes.

        self.connection = MySQLConnectionProvider.get_instance().get_connection()

        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):

        # Ensure DB resources are closed from the caller (try/finally around this).

        try:

            self.cursor.close()

        finally:

            self.connection.close()

    def save_or_get_filter_id(self) -> int:

        """
        Resolves filter_id if it exists (by hash),
        otherwise creates a new header + conditions and returns the new id.
        """

        Resolves filter_id if it exists (by hash),

        otherwise creates a new header + conditions and returns the new id.

        """

        filter_id = self.get_id_by_filters()

        if filter_id:

            safe_status_update(

                self.status_writer,

                JobRunnerStatus.FILTERS_PROCESSING,

                "FiltersManager: Existing filters found"

            )

            return filter_id

        # Insert a new filter header + conditions

        hash_val = self._compute_hash(self.conditions)

        new_id = self._insert_filter(self.filters_name, hash_val)

        self._insert_conditions(new_id, self.conditions)

        safe_status_update(

            self.status_writer,

            JobRunnerStatus.FILTERS_PROCESSING,

            "FiltersManager: Filters saved"

        )

        return new_id

    def get_id_by_filters(self) -> int | None:

        """
        Lookup a filter_id by hash (function-agnostic).
        Returns the ID if found, or None if not. Does not create new rows.
        """

        Lookup a filter_id by hash (function-agnostic).

        Returns the ID if found, or None if not. Does not create new rows.

        """

        hash_val = self._compute_hash(self.conditions)

        self.cursor.execute(

            """
            SELECT id
            FROM defined_fhir_filters
            WHERE filter_hash = %s
            """

            SELECT id

            FROM defined_fhir_filters

            WHERE filter_hash = %s

            """,

            (hash_val,),

        )

        row = self.cursor.fetchone()

        return row["id"] if row else None

    def get_filters_by_id(self, filter_id: int) -> Dict[str, Any]:

        """
        Look up a filter and reconstruct its definition by ID.
        Returns a dict like:
        {
            "name": <filter_name>,
            "filter_id": <filter_id>,
            "conditions": [ {filter_type, column_name, operator, value, values?}, ... ]
        }
        """

        Look up a filter and reconstruct its definition by ID.

        Returns a dict like:

        {

            "name": <filter_name>,

            "filter_id": <filter_id>,

            "conditions": [ {filter_type, column_name, operator, value, values?}, ... ]

        }

        """

        self.cursor.execute(

            """
            SELECT id, name
            FROM defined_fhir_filters
            WHERE id = %s
            """

            SELECT id, name

            FROM defined_fhir_filters

FiltersManager.__init__

            WHERE id = %s

            """,

            (filter_id,),

        )

        row = self.cursor.fetchone()

        if not row:

            raise ValueError(f"Filter {filter_id} not found")

        conditions = self._fetch_filter_conditions(filter_id)

        return {

            "filter_id": row["id"],

            "name": row["name"],

            "conditions": conditions,

        }

    def _csv_encode(self, items: List[Any]) -> str:

        """
        Internal helper to serialize lists of values into a safe comma separated value string.
        Escapes commas and backslashes, deduplicates (caller should pre-clean), and joins.
        This gives deterministic, comparable strings for storage in the DB.
        """

        Internal helper to serialize lists of values into a safe comma separated value string.

        Escapes commas and backslashes, deduplicates (caller should pre-clean), and joins.

        This gives deterministic, comparable strings for storage in the DB.

        """

        items = ["" if v is None else str(v) for v in (items or [])]

        items = [s.replace("\\", "\\\\").replace(",", "\\,") for s in items]

FiltersManager.complete

        return ",".join(items)

    def _csv_decode(self, s: str) -> List[str]:

        """
        Reverses _csv_encode, turning escaped CSV back into a list of values.
        Used when fetching conditions back out of the DB so comparisons can be made properly.
        """

        Reverses _csv_encode, turning escaped CSV back into a list of values.

        Used when fetching conditions back out of the DB so comparisons can be made properly.

        """

FiltersManager.save_or_get_filter_id — Resolves filter_id if it exists (by hash),
otherwise creates a new header + conditions and returns the new id.

        out, cur, esc = [], [], False

        for ch in s or "":

            if esc:

                cur.append(ch)

                esc = False

            elif ch == "\\":

                esc = True

            elif ch == ",":

                out.append("".join(cur))

                cur = []

            else:

                cur.append(ch)

        out.append("".join(cur))

        return out

    def _canonicalize_operator(self, op_in: Any) -> Operator:

        """
        Normalizes a raw operator string into one of the Operator enum values.
        Handles odd spellings like "==" or "NOT IN" so the rest of the system
        only ever deals with a single canonical form.
        """

        Normalizes a raw operator string into one of the Operator enum values.

        Handles odd spellings like "==" or "NOT IN" so the rest of the system

        only ever deals with a single canonical form.

        """

        op_raw = str(op_in or "").strip().upper()

        if op_raw in _CANON_OPS:

            return _CANON_OPS[op_raw]

        op_try = op_raw.replace("_", " ")

        if op_try in _CANON_OPS:

FiltersManager.get_id_by_filters — Lookup a filter_id by hash (function-agnostic).
Returns the ID if found, or None if not. Does not create new rows.

            return _CANON_OPS[op_try]

        raise ValueError(f"Unsupported operator: {op_in}")

    def _validate_and_normalize_conditions(self, name: Any, conditions: Any) -> List[Dict[str, str]]:

        """
        Runs up-front validation of the provided filters.
        Checks for required fields, ensures types are correct, normalizes operators,
        encodes values properly, and sorts everything. Raises ValueError on bad input.
        The return is a list of consistently structured condition dicts.
        """

        Runs up-front validation of the provided filters.

        Checks for required fields, ensures types are correct, normalizes operators,

        encodes values properly, and sorts everything. Raises ValueError on bad input.

        The return is a list of consistently structured condition dicts.

        """

        if not name or not isinstance(name, str):

            raise ValueError("filters.name is required and must be a string")

        # Allow no conditions, treat None or [] as "no filters"

        if conditions is None:

            return []

        if not isinstance(conditions, list):

FiltersManager.get_filters_by_id — Look up a filter and reconstruct its definition by ID.
Returns a dict like:
{
    "name": <filter_name>,
    "filter_id": <filter_id>,
    "conditions": [ {filter_type, column_name, operator, value, values?}, ... ]
}

            raise ValueError("filters.conditions must be an array")

        if len(conditions) == 0:

            return []

        valid_types = {t.value for t in FilterType}

        norm: List[Dict[str, str]] = []

        for idx, c in enumerate(conditions):

            if not isinstance(c, dict):

                raise ValueError(f"conditions[{idx}] must be an object")

            ft = str(c.get("filter_type") or "").strip().upper()

            if ft not in valid_types:

                raise ValueError(f"conditions[{idx}].filter_type invalid: {ft}")

            col = str(c.get("column_name") or "").strip()

            if not col:

                raise ValueError(f"conditions[{idx}].column_name is required")

            op = self._canonicalize_operator(c.get("operator"))

            if op in (Operator.IN, Operator.NOT_IN, Operator.IN_ALL):

                # Operators that expect an array; we accept single "value" for convenience and coerce to [value]

                vals = c.get("values")

                if vals is None and "value" in c:

                    vals = [c.get("value")]

                if not isinstance(vals, list) or not vals:

                    raise ValueError(f"conditions[{idx}]: operator {op.value} requires a non-empty 'values' array")

                csv_val = self._csv_encode(vals)

                norm.append({"filter_type": ft, "column_name": col, "operator": op.value, "value": csv_val})

FiltersManager._csv_encode — Internal helper to serialize lists of values into a safe comma separated value string.
Escapes commas and backslashes, deduplicates (caller should pre-clean), and joins.
This gives deterministic, comparable strings for storage in the DB.

            elif op == Operator.BETWEEN:

                # BETWEEN must have exactly two values (lower, upper)

                vals = c.get("values")

                if not isinstance(vals, list) or len(vals) != 2:

                    raise ValueError(f"conditions[{idx}]: operator BETWEEN requires 'values' with exactly 2 entries")

                csv_val = self._csv_encode(vals)

                norm.append({"filter_type": ft, "column_name": col, "operator": op.value, "value": csv_val})

            else:

FiltersManager._csv_decode — Reverses _csv_encode, turning escaped CSV back into a list of values.
Used when fetching conditions back out of the DB so comparisons can be made properly.

                # Simple operators expect a scalar "value"

                if "value" not in c:

                    raise ValueError(f"conditions[{idx}]: operator {op.value} requires 'value'")

                v = "" if c.get("value") is None else str(c.get("value"))

                norm.append({"filter_type": ft, "column_name": col, "operator": op.value, "value": v})

        # Sort to make the signature stable and equality comparisons deterministic

        norm.sort(key=lambda x: (x["filter_type"], x["column_name"], x["operator"], x["value"]))

        return norm

    def _fetch_filter_conditions(self, filter_id: int) -> List[Dict[str, Any]]:

        """
        Pulls all conditions from the DB for a given filter_id and reconstructs them
        into the normalized format used throughout this class. Values are decoded
        if they were stored as CSV, and the list is sorted for comparison.
        """

        Pulls all conditions from the DB for a given filter_id and reconstructs them

        into the normalized format used throughout this class. Values are decoded

        if they were stored as CSV, and the list is sorted for comparison.

        """

        self.cursor.execute(

            """
            SELECT filter_type, column_name, operator, value
            FROM defined_fhir_filter_conditions
            WHERE filter_id = %s
            """

            SELECT filter_type, column_name, operator, value

            FROM defined_fhir_filter_conditions

FiltersManager._canonicalize_operator — Normalizes a raw operator string into one of the Operator enum values.
Handles odd spellings like "==" or "NOT IN" so the rest of the system
only ever deals with a single canonical form.

            WHERE filter_id = %s

            """,

            (filter_id,),

        )

        rows = self.cursor.fetchall()

        got: List[Dict[str, Any]] = []

        for r in rows:

            op = str(r["operator"] or "").upper()

            val = r["value"] or ""

            cond: Dict[str, Any] = {

                "filter_type": r["filter_type"],

                "column_name": r["column_name"],

                "operator": op,

FiltersManager._validate_and_normalize_conditions — Runs up-front validation of the provided filters.
Checks for required fields, ensures types are correct, normalizes operators,
encodes values properly, and sorts everything. Raises ValueError on bad input.
The return is a list of consistently structured condition dicts.

                "value": val,

            }

            # For set-like operators, also provide a decoded "values" array alongside the raw "value" CSV

            if op in {Operator.IN.value, Operator.NOT_IN.value, Operator.BETWEEN.value, Operator.IN_ALL.value}:

                cond["values"] = self._csv_decode(val)

            got.append(cond)

        got.sort(key=lambda x: (x["filter_type"], x["column_name"], x["operator"], x["value"]))

        return got

    def _conditions_equal(self, a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:

        """
        Compares two lists of conditions for equality. Special logic is applied
        for IN, NOT_IN, IN_ALL, and BETWEEN to compare sets instead of exact CSV strings.
        Used to decide whether a new filter definition matches an existing one.
        """

        Compares two lists of conditions for equality. Special logic is applied

        for IN, NOT_IN, IN_ALL, and BETWEEN to compare sets instead of exact CSV strings.

        Used to decide whether a new filter definition matches an existing one.

        """

        if len(a) != len(b):

            return False

        for i in range(len(a)):

            ai, bi = a[i], b[i]

            if ai["filter_type"] != bi["filter_type"]:

                return False

            if ai["column_name"] != bi["column_name"]:

                return False

            if ai["operator"] != bi["operator"]:

                return False

            op = ai["operator"]

            if op in {Operator.IN.value, Operator.NOT_IN.value, Operator.BETWEEN.value, Operator.IN_ALL.value}:

                if set(self._csv_decode(ai["value"])) != set(self._csv_decode(bi["value"])):  # compare sets

                    return False

            else:

                if ai["value"] != bi["value"]:

                    return False

        return True

    # Hash signature of the conditions allows us to enforce a unique_key and avoid duplicate filter sets

    def _build_signature(self, conditions: List[Dict[str, str]]) -> str:

        return "".join(

            f"[{c['filter_type']}|{c['column_name']}|{c['operator']}|{c['value']}]"

            for c in conditions

        )

    def _compute_hash(self, conditions: List[Dict[str, str]]) -> str:

        """
        Computes a deterministic SHA-256 over the normalized conditions. Any semantically
        identical filter set should hash to the same value, enabling deduplication.
        """

        Computes a deterministic SHA-256 over the normalized conditions. Any semantically

        identical filter set should hash to the same value, enabling deduplication.

        """

        signature = self._build_signature(conditions)

        return hashlib.sha256(signature.encode("utf-8")).hexdigest()

    def _insert_filter(self, name: str | None, hash_val: str) -> int:

        """
        Inserts a new filter header row into defined_fhir_filters (function-agnostic).
        Returns the auto-incremented filter ID.
        """

        Inserts a new filter header row into defined_fhir_filters (function-agnostic).

        Returns the auto-incremented filter ID.

        """

        self.cursor.execute(

            "INSERT INTO defined_fhir_filters (name, filter_hash) VALUES (%s, %s)",

            (name, hash_val),

        )

        self.connection.commit()

        return self.cursor.lastrowid

    def _insert_conditions(self, filter_id: int, conditions: List[Dict[str, str]]):

FiltersManager._fetch_filter_conditions — Pulls all conditions from the DB for a given filter_id and reconstructs them
into the normalized format used throughout this class. Values are decoded
if they were stored as CSV, and the list is sorted for comparison.

        """
        Inserts all normalized conditions for a given filter in one batch.
        If conditions is empty it just exits. Commits immediately.
        """

        Inserts all normalized conditions for a given filter in one batch.

        If conditions is empty it just exits. Commits immediately.

        """

        if not conditions:

            return

        self.cursor.executemany(

            """
            INSERT INTO defined_fhir_filter_conditions
            (filter_id, filter_type, column_name, operator, value)
            VALUES (%s, %s, %s, %s, %s)
            """

            INSERT INTO defined_fhir_filter_conditions

            (filter_id, filter_type, column_name, operator, value)

            VALUES (%s, %s, %s, %s, %s)

            """,

            [(filter_id, c["filter_type"], c["column_name"], c["operator"], c["value"]) for c in conditions],

        )

        self.connection.commit()

```

## FunctionsManager

Defined at: app/core/mysql/managers/FunctionsManager.py

```sql

class FunctionsManager:

    _function_id_cache: dict[str, int] = {}

    def __init__(self):

        self.connection = MySQLConnectionProvider.get_instance().get_connection()

        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):

        try:

            self.cursor.close()

        finally:

            self.connection.close()

    def get_function_id(self, function: SupportedFunction) -> int:

        if function in self._function_id_cache:

            return self._function_id_cache[function]

        self.cursor.execute(

            f"""
            SELECT id
            FROM {MySQLTable.FUNCTIONS}
            WHERE name=%s
            LIMIT 1
            """"

            SELECT id

            FROM {MySQLTable.FUNCTIONS}

            WHERE name=%s

            LIMIT 1

FunctionsManager.__init__

            """,

            (function,),

        )

        row = self.cursor.fetchone()

FunctionsManager.complete

        if row:

            function_id = row["id"]

            self._function_id_cache[function] = function_id

            return function_id

    def get_supported_functions(self):

FunctionsManager.get_function_id

        self.cursor.execute(

            f"""
            SELECT id, name, description, create_date, update_date
            FROM {MySQLTable.FUNCTIONS}
            ORDER BY name
            """"

            SELECT id, name, description, create_date, update_date

            FROM {MySQLTable.FUNCTIONS}

            ORDER BY name

            """

        )

        rows = self.cursor.fetchall()

        for r in rows:

            if r.get("create_date"):

                r["create_date"] = r["create_date"].isoformat()

            if r.get("update_date"):

                r["update_date"] = r["update_date"].isoformat()

        return rows

    def get_function_ids_by_names(self, names: list[str]) -> dict[str, int]:

        clean = sorted({n for n in (names or []) if n})

        if not clean:

FunctionsManager.get_supported_functions

            return {}

        placeholders = ",".join(["%s"] * len(clean))

        self.cursor.execute(

            f"SELECT id, name FROM {MySQLTable.FUNCTIONS} WHERE name IN ({placeholders})",

            clean,

        )

        rows = self.cursor.fetchall()

        return {r["name"]: int(r["id"]) for r in rows}

    def get_or_create_function_config_id(self, function_id: int, prop: str, val: str) -> int:

        self.cursor.execute(

            f"""
            SELECT id
            FROM defined_function_configs
            WHERE function_id = %s AND property_name = %s AND property_value = %s
            LIMIT 1
            """"

            SELECT id

            FROM defined_function_configs

            WHERE function_id = %s AND property_name = %s AND property_value = %s

            LIMIT 1

FunctionsManager.get_function_ids_by_names

            """,

            (function_id, prop, val),

        )

        row = self.cursor.fetchone()

        if row:

            return int(row["id"])

        try:

            self.cursor.execute(

                f"""
                INSERT INTO defined_function_configs
                    (function_id, property_name, property_value)
                VALUES (%s, %s, %s)
                """"

                INSERT INTO defined_function_configs

                    (function_id, property_name, property_value)

                VALUES (%s, %s, %s)

FunctionsManager.get_or_create_function_config_id

                """,

                (function_id, prop, val),

            )

            return int(self.cursor.lastrowid)

        except MySQLdb.IntegrityError:

            self.cursor.execute(

                f"""
                SELECT id
                FROM defined_function_configs
                WHERE function_id = %s AND property_name = %s AND property_value = %s
                LIMIT 1
                """"

                SELECT id

                FROM defined_function_configs

                WHERE function_id = %s AND property_name = %s AND property_value = %s

                LIMIT 1

                """,

                (function_id, prop, val),

            )

            row = self.cursor.fetchone()

            if row:

                return int(row["id"])

            raise

    def get_function_config_id(self, function_id: int, prop: str, val: str) -> int:

        self.cursor.execute(

            """
            SELECT id
            FROM defined_function_configs
            WHERE function_id = %s AND property_name = %s AND property_value = %s
            LIMIT 1
            """

            SELECT id

            FROM defined_function_configs

            WHERE function_id = %s AND property_name = %s AND property_value = %s

            LIMIT 1

            """,

            (function_id, prop, val),

        )

        row = self.cursor.fetchone()

        if not row:

            raise ValueError(f"Config not found for function_id={function_id}: {prop}={val}")

        return int(row["id"])

```

## JobStatusRetriever

Defined at: app/core/mysql/job_tracking/JobStatusRetriever.py

```sql

class JobStatusRetriever:

    def __init__(self, max_retries: int = 3, base_delay: float = 0.2):

        self.max_retries = max_retries

        self.base_delay = base_delay

        self.connection = MySQLConnectionProvider.get_instance().get_connection()

        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def _exec(self, query: str, params: tuple, fetch: str = "one"):

        delay = self.base_delay

        for attempt in range(1, self.max_retries + 1):

JobStatusRetriever.__init__

            try:

                self.cursor.execute(query, params)

                return self.cursor.fetchone() if fetch == "one" else self.cursor.fetchall()

            except Exception:

                if attempt == self.max_retries:

                    raise

JobStatusRetriever._exec

                time.sleep(delay)

                delay *= 2

    def get_status_by_uuid(self, uuid: str):

        row = self._exec(

            f"SELECT * FROM {MySQLTable.JOB_RUNNER_LOG} WHERE uuid = %s",

            (uuid,),

            fetch="one",

        )

        if row:

            referenced = self._exec(

                f"SELECT nvflare_assigned_id FROM {MySQLTable.NVFLARE_JOBS} WHERE job_runner_id = %s",

JobStatusRetriever.get_status_by_uuid

                (uuid,),

                fetch="all",

            )

            row["referenced_by"] = [r["nvflare_assigned_id"] for r in referenced]

        return row

    def complete(self):

        try:

            self.cursor.close()

        finally:

            self.connection.close()

```

## MySQLRetriever

Defined at: app/core/mysql/MySQLRetriever.py

Summary: Lifecycle:
  - Grabs a pooled connection from MySQLConnectionProvider.
  - Exposes read-only helper methods for common queries.
  - Call .complete() when finished to release cursor/connection.

```sql

class MySQLRetriever:

    '''
    Lifecycle:
      - Grabs a pooled connection from MySQLConnectionProvider.
      - Exposes read-only helper methods for common queries.
      - Call .complete() when finished to release cursor/connection.
    '''

    Lifecycle:

      - Grabs a pooled connection from MySQLConnectionProvider.

      - Exposes read-only helper methods for common queries.

      - Call .complete() when finished to release cursor/connection.

    '''

    def __init__(self):

        self.connection = MySQLConnectionProvider.get_instance().get_connection()

        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):

        try:

            self.cursor.close()

        finally:

            self.connection.close()

    def get_supported_functions(self):

        self.cursor.execute(f"""
            SELECT id, name, description, create_date, update_date
            FROM {MySQLTable.FUNCTIONS}
            ORDER BY name
        """f.cursor.execute(f"""

MySQLRetriever.__init__

            SELECT id, name, description, create_date, update_date

            FROM {MySQLTable.FUNCTIONS}

            ORDER BY name

        """)

MySQLRetriever.complete

        rows = self.cursor.fetchall()

        for r in rows:

            if r.get("create_date"): r["create_date"] = r["create_date"].isoformat()

            if r.get("update_date"): r["update_date"] = r["update_date"].isoformat()

        return rows

MySQLRetriever.get_supported_functions

    def get_all_filters(self):

        # Fetch all filters defined in defined_fhir_filters table

        # Sorted by create_date DESC (then id DESC), and with create/update dates normalized to ISO8601

        self.cursor.execute(

            """
            SELECT f.id, f.name, f.create_date, f.update_date
            FROM defined_fhir_filters f
            ORDER BY f.create_date DESC, f.id DESC
            """

            SELECT f.id, f.name, f.create_date, f.update_date

            FROM defined_fhir_filters f

            ORDER BY f.create_date DESC, f.id DESC

            """

        )

        filters = self.cursor.fetchall()

MySQLRetriever.get_all_filters

        # fetch conditions

        out = []

        for f in filters:

            self.cursor.execute(

                """
                SELECT filter_type, column_name, operator, value
                FROM defined_fhir_filter_conditions
                WHERE filter_id = %s
                """

                SELECT filter_type, column_name, operator, value

                FROM defined_fhir_filter_conditions

                WHERE filter_id = %s

                """,

                (f["id"],),

            )

            conds = self.cursor.fetchall()

            out.append({

                "id": f["id"],

                "name": f["name"],

                "conditions": conds,

                "create_date": f["create_date"].isoformat() if f.get("create_date") else None,

                "update_date": f["update_date"].isoformat() if f.get("update_date") else None,

            })

        return out

    def get_single_filter(self, filter_id: int):

        self.cursor.execute(

            """
            SELECT
                id   AS filter_id,
                name AS filter_name,
                create_date,
                update_date
            FROM defined_fhir_filters
            WHERE id = %s
            """

            SELECT

                id   AS filter_id,

                name AS filter_name,

                create_date,

                update_date

            FROM defined_fhir_filters

            WHERE id = %s

            """,

            (filter_id,),

MySQLRetriever.get_single_filter

        )

        f = self.cursor.fetchone()

        if not f:

            return None

        self.cursor.execute(

            """
            SELECT filter_type, column_name, operator, value
            FROM defined_fhir_filter_conditions
            WHERE filter_id = %s
            """

            SELECT filter_type, column_name, operator, value

            FROM defined_fhir_filter_conditions

            WHERE filter_id = %s

            """,

            (f["filter_id"],),

        )

        conds = self.cursor.fetchall()

        return {

            "id": f["filter_id"],

            "name": f["filter_name"],

            "conditions": conds,

            "create_date": f["create_date"].isoformat() if f.get("create_date") else None,

            "update_date": f["update_date"].isoformat() if f.get("update_date") else None,

        }

```

## NVFlareClientEmitManager

Defined at: app/core/mysql/managers/NVFlareClientEmitManager.py

Summary: Resolves job_runner_id from an NVFLARE job_id and logs webhook progress.

```sql

class NVFlareClientEmitManager:

    """Resolves job_runner_id from an NVFLARE job_id and logs webhook progress."""

    def __init__(self, nvflare_assigned_id: str):

        """
        nvflare_assigned_id: The job_id coming from NVFlare (what the webhook sends).
        """

        nvflare_assigned_id: The job_id coming from NVFlare (what the webhook sends).

        """

        self.nvflare_assigned_id = nvflare_assigned_id

        self.connection = MySQLConnectionProvider.get_instance().get_connection()

        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

        self.job_runner_id: Optional[str] = self._lookup_job_runner_id(nvflare_assigned_id)

        self.writer: Optional[JobStatusWriter] = JobStatusWriter(self.job_runner_id) if self.job_runner_id else None

    def complete(self):

        try:

            if self.writer:

                self.writer.complete()

        finally:

            try:

                self.cursor.close()

            finally:

                self.connection.close()

    def _lookup_job_runner_id(self, nvflare_assigned_id: str) -> Optional[str]:

        """Find job_runner_id by NVFlare-assigned job id."""

        sql = f"""
            SELECT job_runner_id
            FROM {MySQLTable.NVFLARE_JOBS}
            WHERE nvflare_assigned_id = %s
            LIMIT 1
        """ = f"""

            SELECT job_runner_id

            FROM {MySQLTable.NVFLARE_JOBS}

            WHERE nvflare_assigned_id = %s

            LIMIT 1

        """

        self.cursor.execute(sql, (nvflare_assigned_id,))

        row = self.cursor.fetchone()

        return (row or {}).get("job_runner_id")

    def log_progress_from_payload(self, payload: Dict[str, Any]) -> None:

        """
        Accepts the JSON body the webhook receiver constructed, e.g.:

        {
            "job_id": "...",               # NVFlare id (nvflare_assigned_id)
            "client_name": "site1",
            "phase": 2,
            "round": 0,
            "origin": "site1",
            "timestamp": 1234567890.0,
            "tag": "job_progress",
            "step": 0,                     # mirrors global_step
            "scalars": { "code": 400, "phase_id": 2, "round": 0 }
        }
        """

        Accepts the JSON body the webhook receiver constructed, e.g.:

        {

            "job_id": "...",               # NVFlare id (nvflare_assigned_id)

            "client_name": "site1",

            "phase": 2,

            "round": 0,

            "origin": "site1",

            "timestamp": 1234567890.0,

            "tag": "job_progress",

            "step": 0,                     # mirrors global_step

            "scalars": { "code": 400, "phase_id": 2, "round": 0 }

        }

        """

        scalars = (payload.get("scalars") or {}) if isinstance(payload.get("scalars"), dict) else {}

        code = _to_int(scalars.get("code"))

        rnd = _to_int(scalars.get("round"))  # may be None for code 100

        client = payload.get("origin")

        self.log_progress(

            code=code,

            round_num=rnd,

            client_name=client,

        )

    def log_progress(

        self,

        *,

        code: Optional[int],

        round_num: Optional[int],

        client_name: Optional[str],

    ) -> None:

        # De-dupe key: use -1 when round is missing (e.g., code 100)

        if self.job_runner_id and client_name and code is not None:

            round_key = int(round_num) if round_num is not None else -1

            k = (self.job_runner_id, client_name, int(code), round_key)

            now = time.time()

            last = _RECENT_KEYS.get(k)

            if last is not None and (now - last) < _DEDUPE_TTL_SEC:

                return

            _RECENT_KEYS[k] = now

        label = HUMAN_MAP.get(code) or f"Event code {code}"

        raw_client = (client_name or "").strip()

        is_initiator = raw_client.lower() == "initiator"

NVFlareClientEmitManager.__init__ — nvflare_assigned_id: The job_id coming from NVFlare (what the webhook sends).

        # Display prefix

        if is_initiator:

            prefix = "Initiator"

        else:

            client_disp = raw_client or "?"

            prefix = f"Client {client_disp}"

        # Message formatting: omit round when not provided

        if round_num is None:

            msg = f"{prefix}: {label}"

NVFlareClientEmitManager.complete

        else:

            try:

                round_disp = int(round_num) + 1  # 1-indexed for humans

            except Exception:

                round_disp = "?"

            msg = f"{prefix}: {label} (round {round_disp})"

        status = CODE_STATUS.get(code, JobRunnerStatus.PROCESSING)

        safe_status_update(self.writer, status, msg)

```

## NVFlareJobsManager

Defined at: app/core/mysql/managers/NVFlareJobsManager.py

```sql

class NVFlareJobsManager:

    def __init__(

        self,

        filter_id: str,

        functions_map: Mapping[str, Mapping[str, str]],

        status_writer: Optional[JobStatusWriter] = None,

        create_date: Optional[str] = None,  # optional lower bound for history queries

    ):

        # Current nvflare_jobs.id for the row being created/managed (set in establish_job_entry_id)

        self.nvflare_job_mysql_id: Optional[int] = None

        # Store function config map (function ids as keys)

        self.functions_map: Dict[str, Dict[str, str]] = self._normalize_functions_map(functions_map or {})

        # Optional logger used by the higher-level job runner

        self.status_writer = status_writer

        self.filter_id = filter_id

        self.job_id = self.status_writer.get_job_id() if self.status_writer else None

        # Optional: limit history results to rows with create_date >= this value (ISO/MySQL string)

        self.create_date = create_date

        print(f"NVFlareJobsManager initiated, functions_map keys: {list(self.functions_map.keys())}", flush=True)

        self.connection = MySQLConnectionProvider.get_instance().get_connection()

        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):

        try:

            self.cursor.close()

        finally:

            self.connection.close()

    def _normalize_functions_map(self, functions_map: Mapping[str, Mapping[str, str]]) -> Dict[str, Dict[str, str]]:

        if functions_map is None:

            return

        out: Dict[str, Dict[str, str]] = {}

        for fn_key, args in (functions_map or {}).items():

            fn = str(fn_key).strip().upper()

            if not fn:

                continue

            args_map: Dict[str, str] = {}

            if isinstance(args, dict):

                for k, v in args.items():

                    key = str(k).strip()

                    if not key:

                        continue

NVFlareJobsManager.__init__

                    args_map[key] = "" if v is None else str(v)

            out[fn] = args_map

        return out

    def establish_job_entry_id(self) -> Optional[int]:

        """
        Creates a nvflare_jobs row, links functions, ensures config rows exist, and links configs to the job.
        """

        Creates a nvflare_jobs row, links functions, ensures config rows exist, and links configs to the job.

        """

        if self.nvflare_job_mysql_id:

            return self.nvflare_job_mysql_id

        if not self.filter_id:

            return None

        if not self.functions_map:

            raise ValueError("At least one function must be specified to create an NVFlare job.")

        try:

            # Step 1: Insert base nvflare_jobs row.

            sql_job = """
                INSERT INTO nvflare_jobs (
                    nvflare_assigned_id,
                    filter_id,
                    status,
                    job_path,
                    output_path,
                    job_runner_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """_job = """

                INSERT INTO nvflare_jobs (

                    nvflare_assigned_id,

                    filter_id,

                    status,

                    job_path,

NVFlareJobsManager.complete

                    output_path,

                    job_runner_id

                )

                VALUES (%s, %s, %s, %s, %s, %s)

            """

            params_job = (

                None,                         # nvflare_assigned_id unknown at submission

NVFlareJobsManager._normalize_functions_map

                self.filter_id,               # filter mapping

                NVFlareStatus.PROCESSING,     # initial NVFlare status

                None,                         # job_path (unknown at submission)

                None,                         # output_path (unknown at submission)

                self.job_id                   # internal job runner UUID (if any)

            )

            self.cursor.execute(sql_job, params_job)

            self.nvflare_job_mysql_id = int(self.cursor.lastrowid)

            # Step 2: Resolve function ids (keys are expected uppercase).

            fm = FunctionsManager()

            fn_names = list(self.functions_map.keys())

            fn_ids_by_name = fm.get_function_ids_by_names(fn_names)

            if len(fn_ids_by_name) != len(self.functions_map):

                unknown = sorted(set(self.functions_map.keys()) - set(fn_ids_by_name.keys()))

                raise ValueError(f"Unknown function(s): {', '.join(unknown)}")

            # Step 3: Link job -> functions.

NVFlareJobsManager.establish_job_entry_id — Creates a nvflare_jobs row, links functions, ensures config rows exist, and links configs to the job.

            if fn_names:

                ph = ",".join(["%s"] * len(fn_names))

                self.cursor.execute(

                    f"""
                    INSERT IGNORE INTO nvflare_job_functions (job_id, function_id)
                    SELECT %s AS job_id, df.id
                    FROM defined_functions df
                    WHERE df.name IN ({ph})
                    """"

                    INSERT IGNORE INTO nvflare_job_functions (job_id, function_id)

                    SELECT %s AS job_id, df.id

                    FROM defined_functions df

                    WHERE df.name IN ({ph})

                    """,

                    [self.nvflare_job_mysql_id] + fn_names,

                )

            # Step 4: Ensure config rows exist and link job -> function -> config.

            # Insert mappings in batches to minimize roundtrips.

            triples: List[int] = []  # (job_id, function_id, config_id) flattened

            for fn_name, kv in self.functions_map.items():

                fn_id = fn_ids_by_name[fn_name]

                for prop, raw_val in (kv or {}).items():

                    cfg_id = fm.get_or_create_function_config_id(fn_id, prop, raw_val)

                    triples.extend([self.nvflare_job_mysql_id, fn_id, cfg_id])

            if triples:

                values_clause = ",".join(["(%s,%s,%s)"] * (len(triples) // 3))

                self.cursor.execute(

                    f"""
                    INSERT IGNORE INTO nvflare_job_function_configs (job_id, function_id, config_id)
                    VALUES {values_clause}
                    """"

                    INSERT IGNORE INTO nvflare_job_function_configs (job_id, function_id, config_id)

                    VALUES {values_clause}

                    """,

                    triples,

                )

            self.connection.commit()

            safe_status_update(

                self.status_writer,

                JobRunnerStatus.JOB_DEFINING,

                f"NVFlareJobsManager: Logged NVFlare job {self.nvflare_job_mysql_id} "

                f"linked to functions {fn_names} with configs"

            )

            return self.nvflare_job_mysql_id

        except Exception as e:

            self.connection.rollback()

            safe_status_update(

                self.status_writer,

                JobRunnerStatus.FAILURE,

                f"NVFlareJobsManager: Failed to create NVFlare job for job_runner_id={self.job_id} - {e}"

            )

            raise

        finally:

            fm.complete()

    def set_nvflare_job_status(self, status: str):

        sql = "UPDATE nvflare_jobs SET status=%s WHERE id=%s"

        self.cursor.execute(sql, (status, self.nvflare_job_mysql_id))

        self.connection.commit()

    def set_nvflare_assigned_id(self, assigned_id: str):

        sql = "UPDATE nvflare_jobs SET nvflare_assigned_id=%s WHERE id=%s"

        self.cursor.execute(sql, (assigned_id, self.nvflare_job_mysql_id))

        self.connection.commit()

    def set_nvflare_job_path(self, job_path: str):

        sql = "UPDATE nvflare_jobs SET job_path=%s WHERE id=%s"

        self.cursor.execute(sql, (job_path, self.nvflare_job_mysql_id))

        self.connection.commit()

    def set_nvflare_output_path(self, output_path: str):

        sql = "UPDATE nvflare_jobs SET output_path=%s WHERE id=%s"

        self.cursor.execute(sql, (output_path, self.nvflare_job_mysql_id))

        self.connection.commit()

    def set_submission_timing(self, submit_time, run_duration: str):

        sql = "UPDATE nvflare_jobs SET submit_time=%s, run_duration=%s WHERE id=%s"

        self.cursor.execute(sql, (submit_time, run_duration, self.nvflare_job_mysql_id))

        self.connection.commit()

    def get_nvflare_jobs(self):

        """
        Returns nvflare_jobs rows as a JSON-friendly list of dicts.
        Optional filters:
        - functions_map: if non-empty, include only jobs linked to any of those function names.
        - create_date: if provided, include only jobs with j.create_date >= create_date.

        Each returned job dict includes:
        - functions: [function_name, ...]
        - functions_map: { function_name: { property_name: property_value, ... }, ... }
        """

        Returns nvflare_jobs rows as a JSON-friendly list of dicts.

        Optional filters:

        - functions_map: if non-empty, include only jobs linked to any of those function names.

        - create_date: if provided, include only jobs with j.create_date >= create_date.

        Each returned job dict includes:

        - functions: [function_name, ...]

        - functions_map: { function_name: { property_name: property_value, ... }, ... }

        """

        try:

            names = sorted((self.functions_map or {}).keys()) if hasattr(self, "functions_map") and self.functions_map else []

            since = self.create_date

            # Base selection (optionally filter by function names and/or create_date)

            if names:

                placeholders = ",".join(["%s"] * len(names))

                sql = f"""
                    SELECT DISTINCT j.*
                    FROM nvflare_jobs j
                    JOIN nvflare_job_functions njf ON njf.job_id = j.id
                    JOIN defined_functions df ON df.id = njf.function_id
                    WHERE df.name IN ({placeholders})
                """ = f"""

                    SELECT DISTINCT j.*

                    FROM nvflare_jobs j

                    JOIN nvflare_job_functions njf ON njf.job_id = j.id

NVFlareJobsManager.set_nvflare_job_status

                    JOIN defined_functions df ON df.id = njf.function_id

                    WHERE df.name IN ({placeholders})

                """

                params = list(names)

                if since:

NVFlareJobsManager.set_nvflare_assigned_id

                    sql += " AND j.create_date >= %s"

                    params.append(since)

                sql += " ORDER BY j.create_date DESC"

                self.cursor.execute(sql, params)

            else:

NVFlareJobsManager.set_nvflare_job_path

                if since:

                    sql = """
                        SELECT *
                        FROM nvflare_jobs
                        WHERE create_date >= %s
                        ORDER BY create_date DESC
                    """ = """

                        SELECT *

                        FROM nvflare_jobs

                        WHERE create_date >= %s

NVFlareJobsManager.set_nvflare_output_path

                        ORDER BY create_date DESC

                    """

                    self.cursor.execute(sql, (since,))

                else:

                    sql = """
                        SELECT *
                        FROM nvflare_jobs
                        ORDER BY create_date DESC
                    """ = """

NVFlareJobsManager.set_submission_timing

                        SELECT *

                        FROM nvflare_jobs

                        ORDER BY create_date DESC

                    """

                    self.cursor.execute(sql)

NVFlareJobsManager.get_nvflare_jobs — Returns nvflare_jobs rows as a JSON-friendly list of dicts.
Optional filters:
- functions_map: if non-empty, include only jobs linked to any of those function names.
- create_date: if provided, include only jobs with j.create_date >= create_date.

Each returned job dict includes:
- functions: [function_name, ...]
- functions_map: { function_name: { property_name: property_value, ... }, ... }

            rows = self.cursor.fetchall()

            if not rows:

                print(

                    "NVFlareJobsManager: Retrieved 0 job(s){}{}".format(

                        f" for functions {names}" if names else "",

                        f" since {since}" if since else ""

                    ),

                    flush=True

                )

                return []

            job_ids = [r["id"] for r in rows]

            # Map job_id -> set(function_name)

            fn_by_job: dict[int, set[str]] = {jid: set() for jid in job_ids}

            ph = ",".join(["%s"] * len(job_ids))

            self.cursor.execute(

                f"""
                SELECT njf.job_id, df.name AS function_name
                FROM nvflare_job_functions njf
                JOIN defined_functions df ON df.id = njf.function_id
                WHERE njf.job_id IN ({ph})
                """"

                SELECT njf.job_id, df.name AS function_name

                FROM nvflare_job_functions njf

                JOIN defined_functions df ON df.id = njf.function_id

                WHERE njf.job_id IN ({ph})

                """,

                job_ids,

            )

            for fr in self.cursor.fetchall():

                fn_by_job.setdefault(fr["job_id"], set()).add(fr["function_name"])

            # Map job_id -> function_name -> {prop: value}

            fm_by_job: dict[int, dict[str, dict[str, str]]] = {jid: {} for jid in job_ids}

            self.cursor.execute(

                f"""
                SELECT njfc.job_id,
                    df.name AS function_name,
                    dfc.property_name,
                    dfc.property_value
                FROM nvflare_job_function_configs njfc
                JOIN defined_functions df ON df.id = njfc.function_id
                JOIN defined_function_configs dfc ON dfc.id = njfc.config_id
                WHERE njfc.job_id IN ({ph})
                """"

                SELECT njfc.job_id,

                    df.name AS function_name,

                    dfc.property_name,

                    dfc.property_value

                FROM nvflare_job_function_configs njfc

                JOIN defined_functions df ON df.id = njfc.function_id

                JOIN defined_function_configs dfc ON dfc.id = njfc.config_id

                WHERE njfc.job_id IN ({ph})

                """,

                job_ids,

            )

            for cr in self.cursor.fetchall():

                j = cr["job_id"]

                fn = cr["function_name"]

                pn = cr["property_name"]

                pv = cr["property_value"]

                fm_by_job.setdefault(j, {}).setdefault(fn, {})[pn] = pv

            out = []

            for r in rows:

                jid = r["id"]

                job_dict = {

                    "id": r["id"],

                    "nvflare_assigned_id": r["nvflare_assigned_id"],

                    "filter_id": r["filter_id"],

                    "status": r["status"],

                    "job_path": r["job_path"],

                    "output_path": r["output_path"],

                    "job_runner_id": r["job_runner_id"],

                    "submit_time": r["submit_time"].isoformat() if r.get("submit_time") else None,

                    "run_duration": r["run_duration"],

                    "create_date": r["create_date"].isoformat() if r.get("create_date") else None,

                    "update_date": r["update_date"].isoformat() if r.get("update_date") else None,

                    "functions": sorted(fn_by_job.get(jid, set())),

                    "functions_map": fm_by_job.get(jid, {}),

                }

                out.append(job_dict)

            print(

                "NVFlareJobsManager: Retrieved {} job(s){}{}".format(

                    len(out),

                    f" for functions {names}" if names else "",

                    f" since {since}" if since else ""

                ),

                flush=True

            )

            return out

        except Exception as e:

            print(

                f"NVFlareJobsManager: Failed to fetch jobs "

                f"(functions={names if 'names' in locals() else '[]'}, since={since if 'since' in locals() else None}) - {e}",

                flush=True

            )

            raise

```

## ParticipationManager

Defined at: app/core/mysql/managers/ParticipationManager.py

```sql

class ParticipationManager:

    def __init__(self):

        self.connection = MySQLConnectionProvider.get_instance().get_connection()

        self.cursor = self.connection.cursor(MySQLdb.cursors.DictCursor)

    def complete(self):

        try:

            self.cursor.close()

        finally:

            self.connection.close()

    def clients_list(self):

        self.cursor.execute(

            f"SELECT client_name FROM {MySQLTable.CLIENTS} ORDER BY client_name"

        )

        return self.cursor.fetchall()

    def resolve_client_id(self, client_name: str) -> int | None:

        self.cursor.execute(

            f"""
            SELECT id
            FROM {MySQLTable.CLIENTS}
            WHERE client_name = %s
            LIMIT 1
            """"

            SELECT id

            FROM {MySQLTable.CLIENTS}

            WHERE client_name = %s

            LIMIT 1

            """,

            (client_name,),

        )

        row = self.cursor.fetchone()

        return row["id"] if row else None

    def _normalize_functions_map(

        self, functions: Mapping[str, Mapping[str, str]]

    ) -> Dict[str, Dict[str, str]]:

        out: Dict[str, Dict[str, str]] = {}

        for fn, args in (functions or {}).items():

            fn_name = str(fn).strip()

            if not fn_name:

                continue

            args_map: Dict[str, str] = {}

            if isinstance(args, dict):

                for k, v in args.items():

                    key = str(k).strip()

                    if not key:

                        continue

                    args_map[key] = "" if v is None else str(v)

            out[fn_name] = args_map

        return out

ParticipationManager.__init__

    def record_participation(

        self,

        client_name: str,

        filter_id: int,

ParticipationManager.complete

        functions_map: Mapping[str, Mapping[str, str]],

        confirmation: Confirmation,

    ) -> int:

        client_id = self.resolve_client_id(client_name)

        if not client_id:

            raise ValueError(f"Unknown client_name: {client_name}")

ParticipationManager.clients_list

        fn_map = self._normalize_functions_map(functions_map)

        if not fn_map:

            raise ValueError("functions must contain at least one function")

        fm = FunctionsManager()

ParticipationManager.resolve_client_id

        try:

            self.cursor.execute(

                f"""
                INSERT INTO {MySQLTable.PARTICIPATION} (client_id, filter_id, confirmation)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    confirmation = VALUES(confirmation),
                    id = LAST_INSERT_ID(id)
                """"

                INSERT INTO {MySQLTable.PARTICIPATION} (client_id, filter_id, confirmation)

                VALUES (%s, %s, %s)

                ON DUPLICATE KEY UPDATE

                    confirmation = VALUES(confirmation),

                    id = LAST_INSERT_ID(id)

                """,

                (client_id, filter_id, confirmation.value),

            )

            participation_id = self.cursor.lastrowid

ParticipationManager._normalize_functions_map

            fn_ids_by_name = fm.get_function_ids_by_names(list(fn_map.keys()))

            if len(fn_ids_by_name) != len(fn_map):

                unknown = sorted(set(fn_map.keys()) - set(fn_ids_by_name.keys()))

                raise ValueError(f"Unknown function(s): {', '.join(unknown)}")

            desired_fn_ids = sorted(fn_ids_by_name.values())

            if desired_fn_ids:

                placeholders = ",".join(["%s"] * len(desired_fn_ids))

                self.cursor.execute(

                    f"""
                    DELETE pf FROM  nvflare_client_participation_functions pf
                    WHERE pf.participation_id = %s
                      AND pf.function_id NOT IN ({placeholders})
                    """"

                    DELETE pf FROM  nvflare_client_participation_functions pf

                    WHERE pf.participation_id = %s

                      AND pf.function_id NOT IN ({placeholders})

                    """,

                    [participation_id] + desired_fn_ids,

                )

                self.cursor.execute(

                    f"""
                    INSERT IGNORE INTO  nvflare_client_participation_functions (participation_id, function_id)
                    SELECT %s AS participation_id, df.id
                    FROM  defined_functions df
                    WHERE df.id IN ({placeholders})
                    """"

ParticipationManager.record_participation

                    INSERT IGNORE INTO  nvflare_client_participation_functions (participation_id, function_id)

                    SELECT %s AS participation_id, df.id

                    FROM  defined_functions df

                    WHERE df.id IN ({placeholders})

                    """,

                    [participation_id] + desired_fn_ids,

                )

            else:

                self.cursor.execute(

                    f"DELETE FROM  nvflare_client_participation_functions WHERE participation_id = %s",

                    (participation_id,),

                )

            for fn_name, args in fn_map.items():

                fn_id = fn_ids_by_name[fn_name]

                desired_cfg_ids: List[int] = []

                for prop, val in (args or {}).items():

                    cfg_id = fm.get_or_create_function_config_id(fn_id, prop, val)

                    desired_cfg_ids.append(cfg_id)

                if desired_cfg_ids:

                    ph = ",".join(["%s"] * len(desired_cfg_ids))

                    self.cursor.execute(

                        f"""
                        DELETE pfc FROM nvflare_participation_function_configs pfc
                        WHERE pfc.participation_id = %s
                          AND pfc.function_id = %s
                          AND pfc.config_id NOT IN ({ph})
                        """"

                        DELETE pfc FROM nvflare_participation_function_configs pfc

                        WHERE pfc.participation_id = %s

                          AND pfc.function_id = %s

                          AND pfc.config_id NOT IN ({ph})

                        """,

                        [participation_id, fn_id] + desired_cfg_ids,

                    )

                    insert_vals = []

                    for cid in desired_cfg_ids:

                        insert_vals.extend([participation_id, fn_id, cid])

                    values_clause = ",".join(["(%s,%s,%s)"] * len(desired_cfg_ids))

                    self.cursor.execute(

                        f"""
                        INSERT IGNORE INTO nvflare_participation_function_configs
                            (participation_id, function_id, config_id)
                        VALUES {values_clause}
                        """"

                        INSERT IGNORE INTO nvflare_participation_function_configs

                            (participation_id, function_id, config_id)

                        VALUES {values_clause}

                        """,

                        insert_vals,

                    )

                else:

                    self.cursor.execute(

                        f"""
                        DELETE FROM nvflare_participation_function_configs
                        WHERE participation_id = %s AND function_id = %s
                        """"

                        DELETE FROM nvflare_participation_function_configs

                        WHERE participation_id = %s AND function_id = %s

                        """,

                        (participation_id, fn_id),

                    )

            self.connection.commit()

            return participation_id

        except Exception:

            self.connection.rollback()

            raise

        finally:

            fm.complete()

    def _candidates_by_functions_only(

        self,

        fn_names: Iterable[str],

        filter_id: int,

        confirmation: Confirmation | None,

        exclude_names: Iterable[str] | None,

    ) -> List[dict]:

        names = sorted({str(n) for n in (fn_names or []) if str(n)})

        if not names:

            return []

        n = len(names)

        params: list = [filter_id]

        placeholders = ",".join(["%s"] * n)

        sql = f"""
            SELECT c.client_name, p.id AS participation_id, p.confirmation
            FROM {MySQLTable.CLIENTS} c
            JOIN {MySQLTable.PARTICIPATION} p
              ON p.client_id = c.id AND p.filter_id = %s
            JOIN  nvflare_client_participation_functions pf
              ON pf.participation_id = p.id
            JOIN  defined_functions df
              ON df.id = pf.function_id
        """ = f"""

            SELECT c.client_name, p.id AS participation_id, p.confirmation

            FROM {MySQLTable.CLIENTS} c

            JOIN {MySQLTable.PARTICIPATION} p

              ON p.client_id = c.id AND p.filter_id = %s

            JOIN  nvflare_client_participation_functions pf

              ON pf.participation_id = p.id

            JOIN  defined_functions df

              ON df.id = pf.function_id

        """

        where = []

        if confirmation:

            where.append("p.confirmation = %s")

            params.append(confirmation.value)

        if exclude_names:

            ex = sorted({n for n in exclude_names if n})

            if ex:

                where.append(f"c.client_name NOT IN ({','.join(['%s']*len(ex))})")

                params.extend(ex)

        if where:

            sql += " WHERE " + " AND ".join(where)

        sql += f"""
            GROUP BY c.client_name, p.id, p.confirmation
            HAVING COUNT(DISTINCT CASE WHEN df.name IN ({placeholders}) THEN df.name END) = %s
            ORDER BY c.client_name
        """ += f"""

            GROUP BY c.client_name, p.id, p.confirmation

            HAVING COUNT(DISTINCT CASE WHEN df.name IN ({placeholders}) THEN df.name END) = %s

            ORDER BY c.client_name

        """

        params.extend(names + [n])

ParticipationManager._candidates_by_functions_only

        self.cursor.execute(sql, tuple(params))

        return self.cursor.fetchall()

    def _configs_match_for_participation(

        self,

        participation_id: int,

        fn_name: str,

        required_pairs: Mapping[str, str] | dict,

    ) -> bool:

        pairs = [(str(k), str(v)) for k, v in (required_pairs or {}).items()]

        if not pairs:

            return True

        conditions = []

        params: list = [participation_id, fn_name]

        for (prop, val) in pairs:

            conditions.append("(dfc.property_name = %s AND dfc.property_value = %s)")

            params.extend([prop, val])

        sql = f"""
            SELECT COUNT(*) AS matched
            FROM nvflare_participation_function_configs pfc
            JOIN  defined_functions df ON df.id = pfc.function_id
            JOIN defined_function_configs dfc ON dfc.id = pfc.config_id AND dfc.function_id = df.id
            WHERE pfc.participation_id = %s
              AND df.name = %s
              AND ({' OR '.join(conditions)})
        """ = f"""

            SELECT COUNT(*) AS matched

            FROM nvflare_participation_function_configs pfc

            JOIN  defined_functions df ON df.id = pfc.function_id

            JOIN defined_function_configs dfc ON dfc.id = pfc.config_id AND dfc.function_id = df.id

            WHERE pfc.participation_id = %s

              AND df.name = %s

              AND ({' OR '.join(conditions)})

        """

        self.cursor.execute(sql, tuple(params))

        row = self.cursor.fetchone()

        matched = int(row["matched"]) if row and "matched" in row else 0

        return matched >= len(pairs)

    def list_client_participation_status(

        self,

        functions: Mapping[str, Mapping[str, str]],

        filter_id: int,

        confirmation: Confirmation | None = None,

        clients_snapshot: list[dict] | None = None,

    ) -> list[dict]:

        fn_map = self._normalize_functions_map(functions)

        if not fn_map:

            return []

        exclude = set()

        if clients_snapshot:

            for e in clients_snapshot:

                name = (e.get("client_name") or e.get("name") or "").strip()

                lo = e.get("last_online", e.get("last_connect_time", e.get("lastConnect")))

                if name and (lo == 0 or (isinstance(lo, str) and lo.strip() == "0")):

ParticipationManager._configs_match_for_participation

                    exclude.add(name)

        candidates = self._candidates_by_functions_only(

            fn_names=fn_map.keys(),

            filter_id=filter_id,

            confirmation=confirmation,

            exclude_names=exclude,

        )

        if not candidates:

            return []

        out: list[dict] = []

        for row in candidates:

            pid = int(row["participation_id"])

            ok = True

            for fn_name, pairs in fn_map.items():

                if not self._configs_match_for_participation(pid, fn_name, pairs):

                    ok = False

                    break

            if ok:

                out.append({"client_name": row["client_name"], "confirmation": row["confirmation"]})

        return out

    def list_clients_with_accepted_participation_csv(

        self,

        functions: Mapping[str, Mapping[str, str]],

        filter_id: int,

        clients_snapshot,

    ) -> str:

        rows = self.list_client_participation_status(

ParticipationManager.list_client_participation_status

            functions=functions,

            filter_id=filter_id,

            confirmation=Confirmation.ACCEPT,

            clients_snapshot=clients_snapshot,

        )

        return ",".join([row["client_name"] for row in rows])

    def list_clients_without_participation_csv(

        self,

        functions: Mapping[str, Mapping[str, str]],

        filter_id: int,

        clients_snapshot,

    ) -> str:

        snapshot_names = {

            c["client_name"]

            for c in (clients_snapshot or [])

            if c.get("last_connect_time") and str(c["last_connect_time"]).strip() != "0"

        }

        satisfied = {

            r["client_name"]

            for r in self.list_client_participation_status(

                functions=functions, filter_id=filter_id, confirmation=None, clients_snapshot=None

            )

        }

        missing = sorted(snapshot_names - satisfied)

        return ",".join(missing)

```