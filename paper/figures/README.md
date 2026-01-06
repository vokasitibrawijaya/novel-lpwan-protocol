# Figures for Novel LPWAN Protocol Paper

This directory contains all figures and graphics used in the paper "Novel Lightweight MQTT-Like Protocol for LPWAN Command-and-Control Applications".

## Figure Files

### PDF Figures (Vector Graphics)
- **fig_architecture.pdf** - System architecture diagram showing device statelessness, gateway intelligence, and network server connection
- **fig_bitmap_ack.pdf** - Message sequence diagram illustrating bitmap ACK mechanism (4 uplinks acknowledged in single downlink)
- **fig_topology.pdf** - Network topology diagrams for single and dual gateway configurations

### Source Files (LaTeX/TikZ)
- **fig_architecture.tex** - TikZ source code for architecture diagram
- **fig_bitmap_ack.tex** - TikZ source code for bitmap ACK sequence diagram
- **fig_topology.tex** - TikZ source code for network topology figure

### Images
- **open_access.png** - Open Access logo for journal header

## Compilation Instructions

To regenerate the PDF figures from source:

```bash
pdflatex fig_architecture.tex
pdflatex fig_bitmap_ack.tex
pdflatex fig_topology.tex
```

Requirements:
- LaTeX distribution (TeX Live, MiKTeX, etc.)
- TikZ package with libraries: shapes, arrows, positioning, fit, calc, decorations.pathreplacing

## Figure Descriptions

### Fig. 1: System Architecture
Shows the three-tier architecture:
- **Devices** (stateless): Only maintain token + sequence numbers
- **Gateway** (stateful): Handles token management, ACK aggregation, command queuing
- **Network Server**: MQTT broker or HTTP server for application integration

### Fig. 2: Bitmap ACK Sequence
Illustrates the aggregate acknowledgment mechanism:
- Multiple uplinks (seq 10-13) transmitted from device
- Gateway buffers uplink metadata
- Single downlink ACK with bitmap acknowledges all 4 messages
- 16:1 aggregation ratio reduces downlink traffic

### Fig. 3: Network Topology
Shows two deployment scenarios:
- **(a) Single Gateway**: Radial device distribution (N=10, 50, 100 devices)
- **(b) Dual Gateway**: Overlapping coverage zones with shared devices

## Usage in Paper

These figures are referenced in the main paper as:
- `\ref{fig:architecture}` - Section III (Protocol Design)
- `\ref{fig:bitmap_ack}` - Section III-D (Windowed Bitmap ACK Scheme)
- `\ref{fig:topology}` - Section IV-E (Experimental Scenarios)

## License

These figures are part of the paper submitted to Journal of Robotics and Control (JRC) and follow the same licensing terms as the main manuscript.
