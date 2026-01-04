FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependency dasar
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-setuptools \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/lpwan-proto-sim

# Install package Python
COPY docker/requirements.txt /opt/lpwan-proto-sim/requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy kode simulasi & konfigurasi
COPY sim/ /opt/lpwan-proto-sim/sim/

# Direktori output akan di-bind dari host
CMD ["python3", "sim/run_sim.py", "--help"]
