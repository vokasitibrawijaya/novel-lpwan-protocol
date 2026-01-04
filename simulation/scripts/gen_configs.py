#!/usr/bin/env python3
"""
Configuration Generator for Parameter Sweep
============================================
Generates multiple configuration files for exploring protocol parameter space.
"""

import argparse
import itertools
import os
from pathlib import Path
from copy import deepcopy

import yaml


# Parameter sweep definitions
SWEEP_PARAMETERS = {
    # Network parameters
    'network.num_devices': [10, 50, 100, 200],
    'network.type': ['lorawan', 'nbiot'],
    'network.lorawan.duty_cycle': [0.01, 0.001],  # 1%, 0.1%
    
    # Traffic parameters
    'traffic.uplink.interval_s': [300, 600, 900, 1800],  # 5min, 10min, 15min, 30min
    'traffic.uplink.pattern': ['periodic', 'poisson'],
    'traffic.downlink.mean_rate_per_hour': [0.5, 1, 2, 5],
    
    # Novel protocol parameters
    'protocols.novel_lpwan.ack_window_size': [8, 16, 32],
    'protocols.novel_lpwan.token_size_bytes': [8, 12, 16],
    
    # QoS parameters
    'qos_deadline_critical_s': [60, 300, 600],  # 1min, 5min, 10min
    'qos_probability_normal': [0.85, 0.90, 0.95],
}

# Reduced sweep for quick testing
QUICK_SWEEP = {
    'network.num_devices': [50, 100],
    'traffic.uplink.interval_s': [600],
    'protocols.novel_lpwan.ack_window_size': [16],
}


def load_base_config(path: Path) -> dict:
    """Load base configuration file."""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def set_nested_value(config: dict, key_path: str, value):
    """Set a value in nested dictionary using dot notation."""
    keys = key_path.split('.')
    current = config
    
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    
    current[keys[-1]] = value


def get_nested_value(config: dict, key_path: str, default=None):
    """Get a value from nested dictionary using dot notation."""
    keys = key_path.split('.')
    current = config
    
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    
    return current


def generate_sweep_configs(base_config: dict, sweep_params: dict) -> list:
    """Generate all configuration combinations from sweep parameters."""
    
    # Get all parameter keys and values
    param_keys = list(sweep_params.keys())
    param_values = list(sweep_params.values())
    
    # Generate all combinations
    combinations = list(itertools.product(*param_values))
    
    configs = []
    for i, combo in enumerate(combinations):
        config = deepcopy(base_config)
        
        # Apply each parameter value
        for key, value in zip(param_keys, combo):
            # Handle special compound parameters
            if key == 'qos_deadline_critical_s':
                # Update critical QoS class deadline
                qos_classes = get_nested_value(config, 'protocols.novel_lpwan.qos_classes', [])
                for qc in qos_classes:
                    if qc.get('name') == 'critical':
                        qc['deadline_s'] = value
            elif key == 'qos_probability_normal':
                # Update normal QoS class probability
                qos_classes = get_nested_value(config, 'protocols.novel_lpwan.qos_classes', [])
                for qc in qos_classes:
                    if qc.get('name') == 'normal':
                        qc['probability'] = value
            else:
                set_nested_value(config, key, value)
        
        # Update seed for reproducibility but variation
        config['simulation']['seed'] = base_config['simulation']['seed'] + i
        
        configs.append({
            'id': i + 1,
            'params': dict(zip(param_keys, combo)),
            'config': config
        })
    
    return configs


def generate_focused_sweep(base_config: dict, focus: str) -> list:
    """Generate configs focusing on specific aspect."""
    
    focus_sweeps = {
        'ack_efficiency': {
            'protocols.novel_lpwan.ack_window_size': [4, 8, 16, 32, 64],
            'traffic.uplink.interval_s': [300, 600, 900],
        },
        'energy': {
            'network.type': ['lorawan', 'nbiot'],
            'traffic.uplink.interval_s': [300, 600, 1200, 1800],
            'network.num_devices': [50, 100],
        },
        'qos_deadline': {
            'qos_deadline_critical_s': [30, 60, 120, 300, 600],
            'qos_probability_normal': [0.80, 0.90, 0.95, 0.99],
        },
        'scalability': {
            'network.num_devices': [10, 25, 50, 100, 200, 500],
            'traffic.uplink.interval_s': [600],
        },
        'command_rate': {
            'traffic.downlink.mean_rate_per_hour': [0.1, 0.5, 1, 2, 5, 10],
            'network.num_devices': [100],
        },
    }
    
    if focus not in focus_sweeps:
        raise ValueError(f"Unknown focus: {focus}. Available: {list(focus_sweeps.keys())}")
    
    return generate_sweep_configs(base_config, focus_sweeps[focus])


def save_configs(configs: list, output_dir: Path):
    """Save generated configurations to files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save index file
    index = []
    for cfg in configs:
        cfg_id = cfg['id']
        filename = f"cfg_{cfg_id:04d}.yaml"
        filepath = output_dir / filename
        
        # Save config
        with open(filepath, 'w', encoding='utf-8') as f:
            # Add header comment with parameters
            f.write(f"# Configuration {cfg_id}\n")
            f.write(f"# Parameters: {cfg['params']}\n")
            f.write("#\n")
            yaml.dump(cfg['config'], f, default_flow_style=False)
        
        index.append({
            'id': cfg_id,
            'filename': filename,
            'params': cfg['params']
        })
    
    # Save index
    index_path = output_dir / "_index.yaml"
    with open(index_path, 'w', encoding='utf-8') as f:
        yaml.dump(index, f, default_flow_style=False)
    
    print(f"Generated {len(configs)} configurations in {output_dir}")
    print(f"Index saved to {index_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate configuration files for parameter sweep'
    )
    parser.add_argument(
        '--base', '-b',
        type=str,
        default='sim/configs/base.yaml',
        help='Path to base configuration file'
    )
    parser.add_argument(
        '--out', '-o',
        type=str,
        default='sim/configs/sweep',
        help='Output directory for generated configs'
    )
    parser.add_argument(
        '--mode', '-m',
        type=str,
        choices=['full', 'quick', 'focus'],
        default='quick',
        help='Sweep mode: full (all combinations), quick (reduced), focus (specific aspect)'
    )
    parser.add_argument(
        '--focus', '-f',
        type=str,
        choices=['ack_efficiency', 'energy', 'qos_deadline', 'scalability', 'command_rate'],
        help='Focus area for focused sweep'
    )
    parser.add_argument(
        '--max-configs', '-n',
        type=int,
        default=None,
        help='Maximum number of configurations to generate'
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    base_path = Path(args.base)
    output_dir = Path(args.out)
    
    # Load base config
    if not base_path.exists():
        print(f"Error: Base config not found: {base_path}")
        return 1
    
    base_config = load_base_config(base_path)
    
    # Generate configs
    if args.mode == 'full':
        configs = generate_sweep_configs(base_config, SWEEP_PARAMETERS)
    elif args.mode == 'quick':
        configs = generate_sweep_configs(base_config, QUICK_SWEEP)
    elif args.mode == 'focus':
        if not args.focus:
            print("Error: --focus required when mode is 'focus'")
            return 1
        configs = generate_focused_sweep(base_config, args.focus)
    
    # Limit if requested
    if args.max_configs and len(configs) > args.max_configs:
        configs = configs[:args.max_configs]
        print(f"Limited to {args.max_configs} configurations")
    
    # Save
    save_configs(configs, output_dir)
    
    return 0


if __name__ == "__main__":
    exit(main())
