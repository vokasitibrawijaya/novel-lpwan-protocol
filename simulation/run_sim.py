#!/usr/bin/env python3
"""
LPWAN Protocol Simulator - Main Entry Point
============================================
Simulates novel MQTT-like protocol for LPWAN compared with MQTT-SN and CoAP baselines.

Novel features implemented:
1. Micro-Session Token (stateless device)
2. Windowed Bitmap ACK
3. QoS-D (Deadline + Probability)
4. Command Pull Slot
5. Epoch-Based Idempotent Commanding
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

import yaml
import numpy as np
import pandas as pd
import simpy
from tqdm import tqdm

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.network import NetworkSimulator
from src.protocols.novel_lpwan import NovelLPWANProtocol
from src.protocols.mqtt_sn import MQTTSNProtocol
from src.protocols.coap import CoAPProtocol
from src.device import EndDevice
from src.gateway import Gateway
from src.metrics import MetricsCollector
from src.traffic import TrafficGenerator


def setup_logging(output_dir: Path, verbose: bool = False):
    """Configure logging to file and console."""
    log_level = logging.DEBUG if verbose else logging.INFO
    
    log_file = output_dir / "simulation.log"
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    """Load YAML configuration file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def create_protocols(config: dict) -> dict:
    """Instantiate enabled protocols."""
    protocols = {}
    proto_cfg = config['protocols']
    
    if proto_cfg.get('novel_lpwan', {}).get('enabled', False):
        protocols['novel_lpwan'] = NovelLPWANProtocol(proto_cfg['novel_lpwan'])
        
    if proto_cfg.get('mqtt_sn', {}).get('enabled', False):
        protocols['mqtt_sn'] = MQTTSNProtocol(proto_cfg['mqtt_sn'])
        
    if proto_cfg.get('coap', {}).get('enabled', False):
        protocols['coap'] = CoAPProtocol(proto_cfg['coap'])
        
    return protocols


def run_simulation(config: dict, output_dir: Path, logger: logging.Logger):
    """Execute the discrete-event simulation."""
    
    sim_cfg = config['simulation']
    net_cfg = config['network']
    
    # Set random seed for reproducibility
    np.random.seed(sim_cfg['seed'])
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Duration in milliseconds
    duration_ms = sim_cfg['duration_hours'] * 3600 * 1000
    warmup_ms = sim_cfg['warmup_hours'] * 3600 * 1000
    
    logger.info(f"Simulation duration: {sim_cfg['duration_hours']}h, warmup: {sim_cfg['warmup_hours']}h")
    
    # Initialize protocols
    protocols = create_protocols(config)
    logger.info(f"Enabled protocols: {list(protocols.keys())}")
    
    # Initialize metrics collector
    metrics = MetricsCollector(
        config=config['metrics'],
        output_dir=output_dir,
        warmup_ms=warmup_ms
    )
    
    # Create network simulator
    network = NetworkSimulator(
        env=env,
        config=net_cfg,
        metrics=metrics
    )
    
    # Create gateway
    gateway = Gateway(
        env=env,
        config=config['gateway'],
        network=network,
        protocols=protocols,
        metrics=metrics
    )
    
    # Create end devices
    devices = []
    for i in range(net_cfg['num_devices']):
        device = EndDevice(
            device_id=i,
            env=env,
            config=config['device'],
            network=network,
            gateway=gateway,
            protocols=protocols,
            metrics=metrics
        )
        devices.append(device)
    
    # Create traffic generator
    traffic_gen = TrafficGenerator(
        env=env,
        config=config['traffic'],
        devices=devices,
        gateway=gateway,
        metrics=metrics
    )
    
    # Register components
    network.set_devices(devices)
    network.set_gateway(gateway)
    
    # Start processes
    env.process(gateway.run())
    for device in devices:
        env.process(device.run())
    env.process(traffic_gen.run())
    env.process(metrics.periodic_collection(env))
    
    # Run simulation with progress bar
    logger.info("Starting simulation...")
    
    step_ms = sim_cfg['time_step_ms']
    total_steps = duration_ms // step_ms
    
    with tqdm(total=total_steps, desc="Simulating", unit="steps") as pbar:
        current_ms = 0
        while current_ms < duration_ms:
            env.run(until=current_ms + step_ms)
            current_ms += step_ms
            pbar.update(1)
    
    logger.info("Simulation completed!")
    
    # Collect final metrics
    metrics.finalize()
    
    return metrics


def save_results(metrics: 'MetricsCollector', output_dir: Path, logger: logging.Logger):
    """Save simulation results to files."""
    
    # Summary statistics
    summary = metrics.get_summary()
    summary_path = output_dir / "summary.yaml"
    with open(summary_path, 'w') as f:
        yaml.dump(summary, f, default_flow_style=False)
    logger.info(f"Saved summary to {summary_path}")
    
    # Detailed metrics CSV
    df = metrics.get_dataframe()
    csv_path = output_dir / "metrics.csv"
    df.to_csv(csv_path, index=False)
    logger.info(f"Saved metrics to {csv_path}")
    
    # Per-protocol comparison
    comparison = metrics.get_protocol_comparison()
    comp_path = output_dir / "protocol_comparison.csv"
    comparison.to_csv(comp_path, index=False)
    logger.info(f"Saved protocol comparison to {comp_path}")
    
    # Print summary to console
    print("\n" + "="*60)
    print("SIMULATION RESULTS SUMMARY")
    print("="*60)
    
    for proto_name, proto_metrics in summary.items():
        print(f"\n{proto_name.upper()}:")
        print("-" * 40)
        for metric_name, value in proto_metrics.items():
            if isinstance(value, float):
                print(f"  {metric_name}: {value:.4f}")
            else:
                print(f"  {metric_name}: {value}")


def main():
    parser = argparse.ArgumentParser(
        description='LPWAN Protocol Simulator - Compare novel protocol with MQTT-SN/CoAP'
    )
    parser.add_argument(
        '--config', '-c',
        type=str,
        required=True,
        help='Path to YAML configuration file'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        required=True,
        help='Directory to save output results'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    config_path = Path(args.config)
    output_dir = Path(args.output_dir)
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    logger = setup_logging(output_dir, args.verbose)
    logger.info(f"Configuration: {config_path}")
    logger.info(f"Output directory: {output_dir}")
    
    # Load configuration
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)
        
    config = load_config(config_path)
    
    # Save config copy to output
    config_copy = output_dir / "config.yaml"
    with open(config_copy, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    # Run simulation
    try:
        metrics = run_simulation(config, output_dir, logger)
        save_results(metrics, output_dir, logger)
    except Exception as e:
        logger.exception(f"Simulation failed: {e}")
        sys.exit(1)
    
    logger.info("Done!")


if __name__ == "__main__":
    main()
