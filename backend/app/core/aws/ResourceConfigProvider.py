'''
Simple file for returning connection information based on environment variable.
This acts as the central place where we decide which credentials/hosts to use
for MySQL and SSH depending on whether we’re running locally or in DEV.
It hides the environment switching logic so other code can just call
AWSResourceConfigProvider and not worry about the details.
'''

from dataclasses import dataclass
import os
from app.core.EnvironmentManager import Environment, EnvironmentProvider
from app.core.aws.SecretsManager import MySQLSecret, SecretsManager

@dataclass
class SSHSecret:
    # Similar to MySQLSecret, but for SSH connections.
    # Holds host/user/port plus either a path to a private key file
    # or the raw private key content in memory.
    host: str
    username: str
    port: int
    private_key_path: str = None
    private_key_content: str = None

class ResourceConfigProvider:
    @staticmethod
    def get_mysql_config(env: Environment = None, check_cached=True) -> MySQLSecret:
        # Returns a MySQLSecret object for the current environment.
        # Local just hardcodes root access with no password to a local db.
        # DEV fetches credentials from AWS Secrets Manager, prints a trace message,
        # and returns a connection pointing at the dev Aurora cluster.
        # check_cached lets you force a fresh read of the secret if needed.
        if env is None:
            env = EnvironmentProvider.get_env()

        if env == Environment.LOCAL:
            host = os.getenv("DUALITY_MYSQL_HOST", "127.0.0.1")
            port = int(os.getenv("DUALITY_MYSQL_PORT", "3306"))
            user = os.getenv("DUALITY_MYSQL_USER", "root")
            pwd  = os.getenv("DUALITY_MYSQL_PASSWORD", "duality_mysql_pass")
            db   = os.getenv("DUALITY_MYSQL_DB", "duality_local")
            return MySQLSecret(username=user, password=pwd, host=host, port=port, dbname=db)

        else:
            if env == Environment.DEV:
                secret_name = "example-database-secret"
                mysql_secret: MySQLSecret = SecretsManager.get_mysql_secret(secret_name=secret_name, check_cached=check_cached)
                print(f"[EndpointURLProvider] Assembled MySQL config for {env}.", flush=True)
                return MySQLSecret(
                    username=mysql_secret.username,
                    password=mysql_secret.password,
                    host="database.example.org",
                    port=3306,
                    dbname="duality_dev"
                )

    @staticmethod
    def get_nvflare_ec2_ssh_config(env: Environment = None, check_cached=True) -> SSHSecret:
        # Returns an SSHSecret for general EC2 connections. Local is blank.
        # DEV returns a fixed EC2 host with ubuntu user and a pem key path
        # so we can connect to the dev box directly.
        if env is None:
            env = EnvironmentProvider.get_env()

        if env == Environment.LOCAL:
            return SSHSecret(
                host="",
                username="",
                port=22,
                private_key_path=""
            )
        elif env == Environment.DEV:
            return SSHSecret(
                host="nvflare.example.org",
                username="ubuntu",
                port=22,
                private_key_path="/app/keys/nvflare.pem"
            )
