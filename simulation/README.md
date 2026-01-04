# LPWAN Protocol Simulator

Simulator untuk membandingkan protokol novel "MQTT-like untuk LPWAN" dengan baseline MQTT-SN dan CoAP.

## Fitur Novel Protokol

1. **Micro-Session Token** - Stateless di perangkat (~32 bytes state)
2. **Windowed Bitmap ACK** - 1 ACK untuk 16+ pesan uplink
3. **QoS-D** - Reliability berbasis (Deadline, Probability)
4. **Command Pull Slot** - Memanfaatkan RX window LPWAN
5. **Header Ringkas** - ≤6 bytes overhead
6. **Epoch-Based Commanding** - Idempoten tanpa "exactly once"

## Struktur Proyek

```
lpwan-proto-sim/
├── docker/
│   ├── Dockerfile          # Container untuk simulator
│   └── requirements.txt    # Dependencies Python
├── sim/
│   ├── src/                # Source code simulator
│   │   ├── network.py      # Model jaringan LPWAN
│   │   ├── device.py       # Model perangkat IoT
│   │   ├── gateway.py      # Model gateway
│   │   ├── metrics.py      # Pengumpul metrik
│   │   ├── traffic.py      # Generator trafik
│   │   └── protocols/      # Implementasi protokol
│   │       ├── novel_lpwan.py
│   │       ├── mqtt_sn.py
│   │       └── coap.py
│   ├── configs/
│   │   ├── base.yaml       # Konfigurasi dasar
│   │   └── sweep/          # Konfigurasi parameter sweep
│   └── run_sim.py          # Entry point simulator
├── results/
│   ├── raw/                # Output mentah simulasi
│   ├── agg/                # Data agregat
│   └── logs/               # Log simulasi
├── scripts/
│   ├── gen_configs.py      # Generator konfigurasi
│   └── run_sweep_local.py  # Orkestrasi simulasi paralel
└── analysis/
    └── analyze_results.py  # Analisis dan visualisasi
```

## Quick Start

### 1. Setup Environment

**Opsi A: Menggunakan Docker (Direkomendasikan)**

```powershell
# Build Docker image
docker build -t lpwan-proto-sim -f docker/Dockerfile .
```

**Opsi B: Python Langsung**

```powershell
# Install dependencies
pip install -r docker/requirements.txt
```

### 2. Generate Konfigurasi

```powershell
# Quick sweep (untuk testing)
python scripts/gen_configs.py --mode quick

# Full sweep (semua kombinasi)
python scripts/gen_configs.py --mode full

# Focused sweep (aspek tertentu)
python scripts/gen_configs.py --mode focus --focus energy
```

### 3. Jalankan Simulasi

**Single run:**

```powershell
# Dengan Docker
docker run --rm -v ${PWD}:/opt/lpwan-proto-sim lpwan-proto-sim `
    python3 sim/run_sim.py `
    --config sim/configs/base.yaml `
    --output-dir results/raw/test_run

# Langsung Python
python sim/run_sim.py --config sim/configs/base.yaml --output-dir results/raw/test_run
```

**Parameter sweep (paralel):**

```powershell
# Dengan Docker
python scripts/run_sweep_local.py --parallel 4

# Tanpa Docker
python scripts/run_sweep_local.py --no-docker --parallel 4
```

### 4. Analisis Hasil

```powershell
python analysis/analyze_results.py --sweep-dir results/raw/sweep_XXXXXXXX
```

## Parameter Konfigurasi

### Network
- `network.type`: `lorawan` | `nbiot` | `sigfox`
- `network.num_devices`: Jumlah perangkat (10-500)
- `network.lorawan.duty_cycle`: Duty cycle (0.01 = 1%)

### Traffic
- `traffic.uplink.interval_s`: Interval uplink (detik)
- `traffic.uplink.pattern`: `periodic` | `poisson` | `event_driven`
- `traffic.downlink.mean_rate_per_hour`: Rate command per jam

### Novel Protocol
- `protocols.novel_lpwan.ack_window_size`: Ukuran bitmap ACK (8-64)
- `protocols.novel_lpwan.token_size_bytes`: Ukuran token sesi (8-16)

### QoS Classes
```yaml
qos_classes:
  - name: "critical"
    probability: 0.99
    deadline_s: 600      # 10 menit
  - name: "normal"
    probability: 0.90
    deadline_s: 3600     # 1 jam
  - name: "best_effort"
    probability: 0.50
    deadline_s: 86400    # 1 hari
```

## Metrik Output

| Metrik | Deskripsi |
|--------|-----------|
| `delivery_rate` | Rasio pesan terkirim sukses |
| `avg_cmd_latency_ms` | Rata-rata latensi command |
| `energy_per_msg_mj` | Energi per pesan (mJ) |
| `total_airtime_ms` | Total waktu transmisi |
| `ack_efficiency` | Pesan per ACK (novel protocol) |
| `commands_applied` | Jumlah command berhasil |

## Kontribusi Ilmiah

Protokol ini dirancang untuk mengisi gap riset:
- MQTT/TCP terlalu berat untuk LPWAN
- MQTT-SN masih stateful di perangkat
- CoAP tidak optimal untuk command & control bilateral

Target paper:
- Model formal state perangkat minimal
- Analisis trade-off QoS-D vs overhead
- Evaluasi bitmap ACK efficiency
- Perbandingan empiris dengan MQTT-SN/CoAP

## Lisensi

Untuk keperluan riset disertasi.
