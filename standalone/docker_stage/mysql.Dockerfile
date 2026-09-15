# Base image pinned to match host version exactly
FROM mysql:8.0.41

# Defaults can be overridden by docker-compose.yml environment:
# - MYSQL_ROOT_PASSWORD: root password for administrative tasks
# - MYSQL_DATABASE: database to auto-create on first run
# - MYSQL_USER / MYSQL_PASSWORD: application user to auto-create
ENV MYSQL_ROOT_PASSWORD=rootpass \
    MYSQL_DATABASE=duality_local \
    MYSQL_USER=duality \
    MYSQL_PASSWORD=dualitypass

# Minimal MySQL server config:
# - utf8mb4 everywhere (full Unicode, incl. emoji/code points)
# - modern default collation for MySQL 8.0
# - safe/strict SQL modes for predictable behavior
RUN printf "[mysqld]\n\
character-set-server=utf8mb4\n\
collation-server=utf8mb4_0900_ai_ci\n\
sql_mode=STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION\n" \
> /etc/mysql/conf.d/charset.cnf

# Liveness probe; compose can override or add its own if desired
HEALTHCHECK --interval=10s --timeout=5s --retries=5 CMD mysqladmin ping -h 127.0.0.1 || exit 1

# Expose the container port (compose will map to a host port like 3307 to avoid conflicts)
EXPOSE 3306

# Note:
# We do NOT COPY init SQL here because the build context is usually docker_stage/.
# Mount init scripts at runtime via docker-compose:
#   volumes:
#     - ../mysql_stage/init:/docker-entrypoint-initdb.d
