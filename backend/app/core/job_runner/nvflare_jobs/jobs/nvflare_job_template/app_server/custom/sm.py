import os
import boto3
import json

class ParticipationSecretsManager:
    # Created on first use: importing this module must not reach for AWS
    # credentials (the simulator and local stack never call Secrets Manager).
    _client = None

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            cls._client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
        return cls._client

    @classmethod
    def get_mysql_password(cls, secret_name: str) -> str:
        if not secret_name:
            raise ValueError("No secret_name provided for MySQL secret lookup")

        response = cls._get_client().get_secret_value(SecretId=secret_name)
        secret_string = response.get("SecretString")

        if not secret_string:
            raise RuntimeError(f"SecretString is empty for secret {secret_name}")

        secret_dict = json.loads(secret_string)

        if "password" not in secret_dict:
            raise KeyError(f"No 'password' field found in secret {secret_name}")

        return secret_dict["password"]
