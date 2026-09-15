# docker_stage/nvflare.Dockerfile
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV OQS_INSTALL_PATH=/usr/local
ENV LD_LIBRARY_PATH=/usr/local/lib

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-venv \
       python3-pip \
       bash \
       tar \
       curl \
       netcat-openbsd \
       ca-certificates \
       libgomp1 \
       git \
       cmake \
       ninja-build \
       build-essential \
       libssl-dev \
    && git clone --depth=1 https://github.com/open-quantum-safe/liboqs /tmp/liboqs \
    && cmake -S /tmp/liboqs -B /tmp/liboqs/build -GNinja -DBUILD_SHARED_LIBS=ON -DCMAKE_INSTALL_PREFIX=/usr/local \
    && cmake --build /tmp/liboqs/build --parallel 8 \
    && cmake --install /tmp/liboqs/build \
    && rm -rf /tmp/liboqs \
    && rm -rf /var/lib/apt/lists/*

ENV NVFLARE_VENV_DIR=/opt/nvflare/.venv
ENV NVFLARE_SERVER_BASE=/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00

WORKDIR /opt/nvflare
RUN mkdir -p ${NVFLARE_SERVER_BASE} /opt/duality/local_wheels

EXPOSE 8002 8003 8004

# Start sequence:
# - install runtime dependencies required by NVFLARE and submitted jobs
# - locate and start NVFLARE server stop, then startup
CMD bash -lc '\
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}/usr/local/lib" && \
  export OQS_INSTALL_PATH="${OQS_INSTALL_PATH:-/usr/local}" && \
  python3 -m venv "$NVFLARE_VENV_DIR" && \
  . "$NVFLARE_VENV_DIR/bin/activate" && \
  pip install --no-cache-dir --upgrade pip && \
  pip install --no-cache-dir \
    "numpy==2.2.6" \
    "python-dateutil>=2.8.2" \
    "pandas==2.3.3" \
    "scipy==1.15.3" \
    "requests>=2.32.5,<=2.33.1" \
    "nvflare==2.7.2" \
    "openfhe>=1.5" \
    "cryptography>=43.0.3" \
    "liboqs-python>=0.14.0" \
    "boto3==1.41.1" \
    "matplotlib==3.10.7" \
    "statsmodels==0.14.4" && \
  LOCAL_WHEEL="$(find /opt/duality/local_wheels -maxdepth 1 -type f -name "duality_nvflare_lib-*.whl" | sort | tail -n 1)" && \
  if [ -n "$LOCAL_WHEEL" ]; then \
    echo "Installing local duality_nvflare_lib wheel: $LOCAL_WHEEL"; \
    pip install --no-cache-dir --no-index --no-deps "$LOCAL_WHEEL"; \
  else \
    echo "ERROR: required local duality_nvflare_lib wheel is missing."; exit 20; \
  fi && \
  mkdir -p "$NVFLARE_SERVER_BASE" && \
  if [ -n "$DUALITY_NVFLARE_HOST" ] && [ -d "$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST/startup" ]; then \
    STARTDIR="$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST/startup"; \
  else \
    STARTDIR="$(find "$NVFLARE_SERVER_BASE" -maxdepth 3 -type d -name startup | head -n 1)"; \
  fi && \
  if [ -z "$STARTDIR" ] || [ ! -d "$STARTDIR" ]; then \
    echo "ERROR: Could not find server startup dir under $NVFLARE_SERVER_BASE"; exit 2; \
  fi && \
  cd "$STARTDIR" && \
  WORKSPACE_DIR="$(cd .. && pwd)" && \
  if [ -f "$WORKSPACE_DIR/daemon_pid.fl" ]; then \
    PID="$(cat "$WORKSPACE_DIR/daemon_pid.fl")"; \
    if kill -0 "$PID" 2>/dev/null; then \
      kill -9 "$PID" || true; \
    fi; \
    rm -f "$WORKSPACE_DIR/daemon_pid.fl"; \
  fi && \
  if [ -f daemon_pid.fl ]; then rm -f daemon_pid.fl; fi && \
  if [ -f stop_fl.sh ]; then \
    chmod +x stop_fl.sh; \
    ./stop_fl.sh >/dev/null 2>&1 || true; \
    echo "Ensuring NVFlare server starts normally. Please wait..."; \
    sleep 10; \
  fi; \
  chmod +x start.sh && \
  ./start.sh && \
  tail -f /dev/null \
'
