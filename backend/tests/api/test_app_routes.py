from app.api.AppRoutes import router
from app.main import health_check


def test_health_check_returns_ok():
    assert health_check() == "ok"


def test_router_contains_startup_kit_endpoint():
    paths = {route.path for route in router.routes}
    assert "/clients/content/startup-kit" in paths
    assert "/projects/list" in paths
    assert "/functions/supported_functions" in paths
    assert "/nvflare/jobs/results_context" in paths
    assert "/landing/home" in paths
    assert "/landing/project" in paths
