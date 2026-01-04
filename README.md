# Novel LPWAN Protocol: Lightweight MQTT-like Protocol for Bidirectional Command and Control

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![SimPy](https://img.shields.io/badge/SimPy-4.0-green.svg)](https://simpy.readthedocs.io/)

## Overview

This repository contains the simulation code, analysis scripts, and experimental results for the paper:

**"Novel Lightweight MQTT-like Protocol for Bidirectional Command and Control in LPWAN Networks"**

Published in Journal of Robotics and Control (JRC), 2026.

## Abstract

Low Power Wide Area Networks (LPWAN) have emerged as a fundamental technology for IoT applications requiring long-range communication with minimal energy consumption. This work presents a novel lightweight MQTT-like protocol specifically designed for bidirectional command and control in LPWAN networks, with applications in robotics and industrial control systems.

### Key Innovations

1. **Micro-Session Token**: Stateless device operation with 12-byte session tokens
2. **Windowed Bitmap ACK**: Single downlink acknowledges up to 16 uplinks (14.7x efficiency)
3. **QoS-D (Deadline + Probability)**: LPWAN-native QoS with configurable reliability
4. **Command Pull Slot**: Piggybacked command retrieval on uplink transmissions
5. **Compact 5-byte Header**: 40% overhead reduction vs. MQTT-SN/CoAP
6. **Epoch-Based Idempotent Commanding**: Eliminates duplicate command processing

## Repository Structure

```
novel-lpwan-protocol/
├── README.md                    # This file
├── paper/
│   ├── Novel_LPWAN_Protocol_JRC.tex     # LaTeX source (JRC format)
│   ├── Novel_LPWAN_Protocol_JRC.pdf     # Published paper
│   └── IEEEtran.cls                     # Document class
├── simulation/
│   ├── run_sim.py               # Main simulation entry point
│   ├── README.md                # Simulation documentation
│   ├── src/
│   │   ├── __init__.py
│   │   ├── device.py            # End device model
│   │   ├── gateway.py           # Gateway model
│   │   ├── metrics.py           # Metrics collection
│   │   ├── network.py           # LoRaWAN/NB-IoT channel models
│   │   ├── traffic.py           # Traffic generation
│   │   └── protocols/
│   │       ├── __init__.py
│   │       ├── novel_lpwan.py   # Novel protocol implementation
│   │       ├── mqtt_sn.py       # MQTT-SN baseline
│   │       └── coap.py          # CoAP baseline
│   ├── configs/
│   │   ├── base.yaml            # Base configuration
│   │   └── base_ieee.yaml       # Standard base config
│   └── scripts/
│       ├── gen_configs.py       # Configuration generator
│       ├── gen_ieee_configs.py  # Experiment configs
│       └── run_sweep_local.py   # Local sweep runner
├── analysis/
│   ├── analyze_results.py       # Results analysis
│   └── ieee_analysis.py         # Statistical analysis
├── results/
│   ├── sample_raw/              # Sample raw results (3 runs)
│   │   ├── cfg_0001_run01/
│   │   ├── cfg_0002_run02/
│   │   ├── cfg_0003_run03/
│   │   └── _sweep_meta.json
│   └── [aggregated analysis CSVs]
└── docker/
    ├── Dockerfile               # Docker container definition
    └── requirements.txt         # Python dependencies
```

## Quick Start

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Installation

```bash
# Clone the repository
git clone https://github.com/[username]/novel-lpwan-protocol.git
cd novel-lpwan-protocol

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r docker/requirements.txt
```

### Running a Single Simulation

```bash
cd simulation
python run_sim.py --config configs/base_ieee.yaml --output ../results/test_run
```

### Running Experiments

```bash
# Generate experiment configurations
python scripts/gen_ieee_configs.py --output configs/ieee_experiments

# Run parameter sweep (requires significant time)
python scripts/run_sweep_local.py --config-dir configs/ieee_experiments --output ../results/raw
```

### Analyzing Results

```bash
cd analysis
python ieee_analysis.py --input ../results/raw --output ../results/analysis
```

## Experimental Configuration

### Reproducibility Standards

All experiments follow rigorous reproducibility standards:
- **3 independent runs** per configuration (seeds: 42, 123, 456)
- **Documented random seeds** for full reproducibility
- **Statistical analysis** with variance reporting

### Experiments

| Experiment | Configs | Description |
|------------|---------|-------------|
| Command Control Timing | 210 | Downlink command delivery performance |
| Network Scalability | 270 | 10-100 devices scaling analysis |
| Duty Cycle Compliance | 270 | 0.1%, 1%, 10% duty cycle impact |
| Network Comparison | 180 | LoRaWAN vs NB-IoT |

### Key Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Simulation Duration | 24 hours | Per-run duration |
| Warmup Period | 2 hours | Excluded from statistics |
| Number of Devices | 10-100 | Varies by experiment |
| Uplink Interval | 600s | Periodic telemetry |
| Duty Cycle | 1% | EU868 compliant |

## Results Summary

### Performance Comparison (Command Control, 100 devices)

| Metric | Novel LPWAN | MQTT-SN | CoAP |
|--------|-------------|---------|------|
| Delivery Rate | 96.48% ± 0.15% | 96.46% ± 0.16% | 96.47% ± 0.15% |
| Energy/Message | **9.59 ± 0.09 mJ** | 9.86 ± 0.10 mJ | 10.74 ± 0.14 mJ |
| Cmd Latency | 595.8 ± 4.0 s | 599.1 ± 1.3 s | 599.8 ± 1.3 s |
| ACK Efficiency | **14.67** | 1.0 | 1.0 |

### Key Findings

- **11.1% energy reduction** compared to CoAP
- **3.0% energy reduction** compared to MQTT-SN
- **14.7x ACK efficiency** through windowed bitmap acknowledgments
- **Comparable delivery rates** across all protocols (~96.5%)

## Reproducibility

### Verifying Results

The `results/sample_raw/` directory contains complete outputs from 3 representative runs:

```bash
# Each run directory contains:
cfg_0001_run01/
├── config.yaml            # Exact configuration used
├── simulation.log         # Execution log with timestamps
├── metrics.csv            # Packet-level raw data
├── protocol_comparison.csv # Aggregated protocol metrics
└── summary.yaml           # Per-protocol summary
```

### Docker Reproduction

```bash
cd docker
docker build -t novel-lpwan-sim .
docker run -v $(pwd)/../results:/results novel-lpwan-sim
```

## Citation

If you use this code or data in your research, please cite:

```bibtex
@article{novel_lpwan_2026,
  title={Novel Lightweight MQTT-like Protocol for Bidirectional Command and Control in LPWAN Networks},
  author={[Authors]},
  journal={Journal of Robotics and Control (JRC)},
  year={2026},
  volume={},
  number={},
  pages={},
  doi={}
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contact

For questions about the code or paper, please open an issue or contact:
- **Author**: [Name] - [email]
- **Institution**: [University/Organization]

## Acknowledgments

- SimPy discrete-event simulation framework
- LoRaWAN Alliance for protocol specifications
- 3GPP for NB-IoT specifications
