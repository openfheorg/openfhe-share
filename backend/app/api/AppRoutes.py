from fastapi import APIRouter
from app.api.routes import ClientContentRoutes, ClientRoutes, FilterRoutes, FunctionRoutes, JobRunnerRoutes, LandingPageRoutes, NVFlareRoutes, ProjectRoutes, UserRoutes

router = APIRouter()
router.include_router(FilterRoutes.router)
router.include_router(FunctionRoutes.router)
router.include_router(NVFlareRoutes.router)
router.include_router(JobRunnerRoutes.router)
router.include_router(LandingPageRoutes.router)
router.include_router(ClientRoutes.router)
router.include_router(ClientContentRoutes.router)
router.include_router(ProjectRoutes.router)
router.include_router(UserRoutes.router)
