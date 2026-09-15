from pydantic import BaseModel
from typing import List


class JobInfo(BaseModel):
    job_id: str
    path: str
    modified_epoch: float


class JobsResponse(BaseModel):
    workspace: str
    jobs: List[JobInfo]


class JobResultsDirResponse(BaseModel):
    workspace: str
    job_results_dir: str
    exists: bool
