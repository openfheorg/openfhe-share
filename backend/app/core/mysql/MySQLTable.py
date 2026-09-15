from enum import Enum

class MySQLTable(str, Enum):
    # Enum of table names we touch directly in MySQL.
    # Centralizes naming so queries don’t hardcode strings everywhere.
    PROJECTS = "defined_projects"

    USER_ROLES = "defined_roles"
    JOB_RUNNER_LOG = "job_runner_log"

    FUNCTIONS = "defined_functions"
    FUNCTION_CONFIG_PROPERTIES = "defined_function_config_properties"
    FUNCTION_CONFIG_SETS = "defined_function_config_sets"
    FUNCTION_CONFIG_SET_MEMBERS = "defined_function_config_set_members"

    FHIR_FILTERS = "defined_fhir_filters"
    FHIR_FILTER_CONDITIONS = "defined_fhir_filter_conditions"

    NVFLARE_JOBS = "nvflare_jobs"
    NVFLARE_JOB_FUNCTIONS = "nvflare_job_functions"
    NVFLARE_JOB_FUNCTION_CONFIGS = "nvflare_job_function_configs"
    NVFLARE_JOB_CRYPTO_AUDIT = "nvflare_job_crypto_audit"

    USERS = "users"
    CLIENTS = "nvflare_clients"
    PROJECT_CLIENT_EXCLUSIONS = "nvflare_project_client_exclusions"

    PARTICIPATION = "nvflare_client_participation"
    PARTICIPATION_FUNCTIONS = "nvflare_client_participation_functions"
    PARTICIPATION_FUNCTION_CONFIGS = "nvflare_client_participation_function_configs"

    THRESHOLD_CONFIGS = "threshold_configs"

    def __str__(self):
        return self.value
