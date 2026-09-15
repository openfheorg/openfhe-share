# Linux-only execution environment for the NVFlare simulator regression sweeps.
# The application source and FHIR data are mounted at runtime; neither is baked
# into this image.
#
# OpenFHE's CPython extension currently requires GLIBCXX_3.4.32. Debian
# Bookworm's libstdc++ is too old, so use the Debian Trixie Python image.
#
# This image also preinstalls liboqs. The NVFlare client processes import
# liboqs-python during PQC key generation. Without the native liboqs library,
# each simulated client tries to clone/build liboqs dynamically at test runtime.

FROM python:3.12-slim-trixie

ARG NVFLARE_VERSION=2.7.2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    OQS_INSTALL_PATH=/usr/local \
    LD_LIBRARY_PATH=/usr/local/lib

# Mirror the standalone NVFlare client image's liboqs build prerequisites and
# shared-library installation. Build liboqs once into the image; simulator
# child processes then only load it rather than independently auto-installing it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libgomp1 \
        libssl-dev \
        libstdc++6 \
        ninja-build \
        python3-dev \
    && git clone --depth=1 https://github.com/open-quantum-safe/liboqs /tmp/liboqs \
    && cmake -S /tmp/liboqs -B /tmp/liboqs/build \
        -GNinja \
        -DBUILD_SHARED_LIBS=ON \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
    && cmake --build /tmp/liboqs/build --parallel 8 \
    && cmake --install /tmp/liboqs/build \
    && ldconfig \
    && rm -rf /tmp/liboqs \
    && rm -rf /var/lib/apt/lists/*

# Keep this list aligned with wheels/APIWheelBuilderCI.py. Installing it at
# image-build time means each disposable test container only needs to build and
# install the local duality wheel with --no-deps.
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install \
        "nvflare[he]==${NVFLARE_VERSION}" \
        "numpy==2.2.6" \
        "python-dateutil>=2.8.2" \
        "pandas==2.3.3" \
        "scipy==1.15.3" \
        "requests>=2.32.5,<=2.33.1" \
        "openfhe>=1.5" \
        "cryptography>=43.0.3" \
        "liboqs-python>=0.14.0" \
        "boto3==1.41.1" \
        "matplotlib==3.10.7" \
        "statsmodels==0.14.4" \
        "pytest==9.0.3" \
        "pytest-xdist==3.6.1"

# Fail the image build before a sweep starts if either native extension cannot
# load. This validates both the modern C++ runtime needed by OpenFHE and the
# preinstalled liboqs shared library needed by liboqs-python.
RUN python -c "import openfhe; print('OpenFHE native extension import: OK')" \
    && python -c "import oqs; print('liboqs-python native library import: OK')"

COPY container_entrypoint.py /usr/local/bin/run-nvflare-simulator-sweep
RUN chmod 0755 /usr/local/bin/run-nvflare-simulator-sweep \
    && mkdir -p /work /results /source-models/datasource_group_1

ENTRYPOINT ["/usr/local/bin/run-nvflare-simulator-sweep"]
