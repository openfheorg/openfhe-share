'''
MySQL instance is protected by SecretsManager with a rotating password. 
This class establishes the password to the database without exposing it in raw code.
It fetches the credentials securely from AWS Secrets Manager, caches them in memory 
for reuse, and makes sure we fail fast if anything goes wrong.
'''

import os
import boto3
import json
import time
from dataclasses import dataclass

from app.core.EnvironmentManager import EnvironmentProvider


@dataclass
class MySQLSecret:
    # Simple dataclass container for MySQL credentials.
    # Populated either from local config or AWS Secrets Manager.
    username: str
    password: str
    host: str
    port: int
    dbname: str

class SecretsManager:
    # Central class for retrieving secrets from AWS.
    # Wraps boto3's Secrets Manager client, handles caching,
    # and normalizes secrets into our dataclasses.
    _client = boto3.client(
        "secretsmanager",
        region_name=os.getenv("AWS_REGION", "us-east-1")
    )
    _cached_mysql_secret = None

    @classmethod
    def get_mysql_secret(cls, secret_name, check_cached=True) -> MySQLSecret:
        env = EnvironmentProvider.get_env()
        print(f"[SecretsManager] Starting secret retrieval for environment: {env}", flush=True)

        if not secret_name:
            msg = f"[SecretsManager] ERROR: No secret_name supplied in environment {env}. Can't perform MySQL secret lookup!"
            print(msg, flush=True)
            raise ValueError(msg)

        if check_cached and cls._cached_mysql_secret:
            print(f"[SecretsManager] Returning cached MySQL secret for environment: {env}", flush=True)
            return cls._cached_mysql_secret

        last_exception = None
        for attempt in range(3):
            try:
                response = cls._client.get_secret_value(SecretId=secret_name)
                print("[SecretsManager] Successfully retrieved secret string from Secrets Manager", flush=True)

                secret_string = response.get("SecretString")
                if not secret_string:
                    raise RuntimeError(f"SecretString is empty for secret {secret_name}")

                secret_dict = json.loads(secret_string)

                cls._cached_mysql_secret = MySQLSecret(
                    username=secret_dict["username"],
                    password=secret_dict["password"],
                    host=secret_dict.get("host", ""),
                    port=int(secret_dict.get("port", 3306)),
                    dbname=secret_dict.get("dbname", "duality_dev"),
                )

                print(f"[SecretsManager] Loaded MySQL secret successfully for environment: {env}", flush=True)
                return cls._cached_mysql_secret

            except Exception as e:
                last_exception = e
                print(f"[SecretsManager] Attempt {attempt+1} failed to retrieve secret '{secret_name}': {e}", flush=True)
                time.sleep(2 ** attempt)  # exponential backoff (2s, 4s, 8s)

        raise RuntimeError(f"[SecretsManager] ERROR: Failed to retrieve secret '{secret_name}' after 3 attempts") from last_exception
