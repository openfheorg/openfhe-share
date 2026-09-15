# client_utils/client.Dockerfile
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

# Where we create the venv inside the container
ENV NVFLARE_VENV_DIR=/opt/nvflare/.venv

# EC2-style workspace base path inside the container
ENV NVFLARE_SERVER_BASE=/home/ubuntu/nvflare/workspace/duality_nvflare/prod_00

# The client startup kit tar is mounted by compose to this path
ENV NVFLARE_SERVER_TAR_PATH=/kits/client_startup_kit.tar

# The launcher stages selected local datasource json files into the build context before build
COPY injected_datasources/ /data/client/

WORKDIR /opt/nvflare
RUN mkdir -p /kits ${NVFLARE_SERVER_BASE} /data/client /opt/duality/local_wheels

# Start sequence:
# - create venv, install deps (no torch/vision)
# - unpack client kit tar into ${NVFLARE_SERVER_BASE}
# - normalize *.sh and run startup
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
    "matplotlib==3.10.7" && \
  LOCAL_WHEEL="$(find /opt/duality/local_wheels -maxdepth 1 -type f -name "duality_nvflare_lib-*.whl" | sort | tail -n 1)" && \
  if [ -n "$LOCAL_WHEEL" ]; then \
    echo "Installing local duality_nvflare_lib wheel: $LOCAL_WHEEL"; \
    pip install --no-cache-dir --no-index --no-deps "$LOCAL_WHEEL"; \
  else \
    echo "ERROR: required local duality_nvflare_lib wheel is missing."; exit 20; \
  fi && \
  mkdir -p "$NVFLARE_SERVER_BASE" && \
  rm -rf "$NVFLARE_SERVER_BASE"/* && \
  tar -xf "$NVFLARE_SERVER_TAR_PATH" -C "$NVFLARE_SERVER_BASE" && \
  find "$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST" -type f -name "*.sh" -exec chmod +x {} \; && \
  find "$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST" -type f -name "*.sh" -exec sed -i "s/\r$//" {} \; && \
  if [ "${DUALITY_ENABLE_JOB_RESULTS_SYMLINK:-false}" = "true" ]; then \
    mkdir -p /job-results && \
    rm -rf "$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST/job-results" && \
    ln -s /job-results "$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST/job-results"; \
  fi && \
  cd "$NVFLARE_SERVER_BASE/$DUALITY_NVFLARE_HOST/startup" && \
  chmod +x start.sh && \
  ./start.sh || true && \
  tail -f /dev/null \
'
