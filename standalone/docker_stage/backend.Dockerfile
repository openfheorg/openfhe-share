FROM python:3.12-slim

# system dependencies (mysqlclient, git, curl, certs, + bash for fl_admin.sh)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    git \
    curl \
    ca-certificates \
    # libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Add extra libs needed by jobs/utilities
RUN pip install --no-cache-dir boto3

# Provide the NVFLARE admin startup kit inside the image
RUN mkdir -p /kits
COPY standalone/dist/admin_startup_kit.tar /kits/admin_startup_kit.tar
ENV DUALITY_ADMIN_TAR=/kits/admin_startup_kit.tar

# App source
COPY backend/ .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
