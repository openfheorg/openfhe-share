'''
Environment manager used to enforce a dev/test/prod environment variable on the running FastAPI container.
Provides access to the current environment (dev/test/prod/local) via the SHARE_ENV variable
'''

from enum import Enum
import os

class Environment(Enum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"
    LOCAL = "local"
    def __str__(self):
        return self.value


class EnvironmentProvider:
    ENV_VAR_NAME = "SHARE_ENV"
    _cached_env = None

    @classmethod
    def get_env(cls) -> Environment:
        if cls._cached_env is not None:
            return cls._cached_env

        raw = os.environ.get(cls.ENV_VAR_NAME)
        valid_values = [e.value for e in Environment]

        if raw is None:
            print(f"Error: Environment variable '{cls.ENV_VAR_NAME}' is not set. Valid values: {valid_values}")
            os._exit(1)
        try:
            cls._cached_env = Environment(raw)
            print(f"EnvironmentProvider initialized successfully for: {raw}")
            return cls._cached_env
        except ValueError:
            print(f"Error: Invalid value '{raw}' for '{cls.ENV_VAR_NAME}'. Valid values: {valid_values}")
            os._exit(1)
