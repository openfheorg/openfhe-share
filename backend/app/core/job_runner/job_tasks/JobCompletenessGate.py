'''
Verifies that a finished NVFlare job actually produced every result it promised.

NVFlare reports FINISHED:COMPLETED for a run whose server process died part way through the
workflow list, and the results page enumerates the result directories that exist -- so a
computation that never ran silently disappears from the page instead of being reported. This
module compares the workflows the stager bound to each selected function config against the
result directories those functions actually produced.
'''

from typing import Dict, Iterable, List, Set, Tuple

from app.core.mysql.SupportedFunction import SupportedFunction

# Written to nvflare_jobs.status when a run finished without producing every bound result.
# Keeps the "FINISHED:" prefix (the monitor treats that as terminal) and deliberately avoids
# the substring "COMPLETED", which several UI predicates test for with includes().
PARTIAL_STATUS = "FINISHED:PARTIAL"


def group_bindings_by_function(bindings: Iterable[Tuple[str, str]]) -> Dict[str, Set[str]]:
    """``[(function, workflow_id), ...]`` -> ``{function: {workflow_id, ...}}``."""
    grouped: Dict[str, Set[str]] = {}
    for function_name, workflow_id in bindings:
        if not function_name or not workflow_id:
            continue
        grouped.setdefault(str(function_name).strip().upper(), set()).add(str(workflow_id).strip())
    return grouped


def missing_workflow_results(
    expected: Dict[str, Set[str]],
    produced: Dict[str, Set[str]],
) -> List[Tuple[str, str]]:
    """Return the ``(function, workflow_id)`` pairs that were promised but produced nothing.

    Sorted so the reported message is stable. Extra produced workflows are not a problem:
    a function's directory can legitimately hold more than the bound terminal workflow.
    """
    gaps: List[Tuple[str, str]] = []
    for function_name in sorted(expected):
        produced_ids = produced.get(function_name, set())
        for workflow_id in sorted(expected[function_name]):
            if workflow_id not in produced_ids:
                gaps.append((function_name, workflow_id))
    return gaps


def collect_produced_workflows(nvflare_job_id: str, function_names: Iterable[str]) -> Dict[str, Set[str]]:
    """Return ``{function: {workflow_id, ...}}`` for the result dirs each function produced.

    One ``list_workflow_dirs()`` call per function -- a directory listing, local or over SSH
    depending on the environment. A function whose listing fails (or whose name has no
    computation-type mapping) is reported as producing nothing, which is the honest reading:
    we could not confirm its results exist.
    """
    # Imported here so the comparison helpers above stay importable (and unit-testable)
    # without the DB driver stack the retriever pulls in.
    from app.core.mysql.job_tracking.NVFlareJobsDataRetriever import NVFlareJobsDataRetriever

    produced: Dict[str, Set[str]] = {}
    for raw_name in function_names:
        function_name = str(raw_name).strip().upper()
        function_enum = SupportedFunction.from_name(function_name)
        if function_enum is None:
            produced[function_name] = set()
            continue
        try:
            retriever = NVFlareJobsDataRetriever(
                nvflare_job_id=nvflare_job_id,
                function=function_enum,
            )
            produced[function_name] = {str(d).strip() for d in retriever.list_workflow_dirs()}
        except Exception:
            produced[function_name] = set()
    return produced
