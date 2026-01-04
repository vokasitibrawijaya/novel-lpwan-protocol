#!/usr/bin/env python3
"""
IEEE Access Compliant Configuration Generator
==============================================
Generates experiment configurations meeting IEEE publication standards:
- Minimum 30 independent runs per configuration
- Varied random seeds for reproducibility
- Systematic parameter exploration
- Proper baseline configurations
"""

import argparse
import itertools
from pathlib import Path
from copy import deepcopy
from datetime import datetime

import yaml


# =============================================================================
# IEEE ACCESS EXPERIMENT DESIGN
# =============================================================================
# Requirements:
# 1. Minimum 30 independent runs for statistical significance
# 2. Multiple seeds with documented values
# 3. Clear baseline configurations
# 4. Systematic parameter variation (one-at-a-time + factorial)

NUM_RUNS_PER_CONFIG = 30  # IEEE minimum for statistical validity
BASE_SEED = 12345         # Documented seed for reproducibility


def generate_seeds(base_seed: int, num_runs: int) -> list:
    """Generate reproducible seed sequence."""
    return [base_seed + i * 17 for i in range(num_runs)]  # Prime multiplier for spread


# =============================================================================
# EXPERIMENT CONFIGURATIONS
# =============================================================================

# Experiment 1: Scalability Analysis
SCALABILITY_SWEEP = {
    'name': 'scalability',
    'description': 'Evaluate protocol performance as number of devices increases',
    'parameters': {
        'network.num_devices': [10, 25, 50, 100, 150, 200, 300, 500],
    },
    'fixed': {
        'network.type': 'lorawan',
        'traffic.uplink.interval_s': 600,
        'traffic.downlink.mean_rate_per_hour': 2,
    }
}

# Experiment 2: Traffic Pattern Analysis
TRAFFIC_SWEEP = {
    'name': 'traffic_pattern',
    'description': 'Evaluate impact of different traffic patterns and rates',
    'parameters': {
        'traffic.uplink.interval_s': [60, 120, 300, 600, 900, 1800, 3600],
        'traffic.uplink.pattern': ['periodic', 'poisson'],
    },
    'fixed': {
        'network.num_devices': 100,
        'network.type': 'lorawan',
    }
}

# Experiment 3: Command & Control Analysis
COMMAND_SWEEP = {
    'name': 'command_control',
    'description': 'Evaluate downlink command delivery performance',
    'parameters': {
        'traffic.downlink.mean_rate_per_hour': [0.1, 0.5, 1, 2, 5, 10, 20],
    },
    'fixed': {
        'network.num_devices': 100,
        'network.type': 'lorawan',
        'traffic.uplink.interval_s': 600,
    }
}

# Experiment 4: QoS-D Parameter Analysis (Novel Protocol)
QOSD_SWEEP = {
    'name': 'qos_deadline',
    'description': 'Evaluate QoS-D (Deadline + Probability) parameter impact',
    'parameters': {
        'qos_deadline_critical_s': [60, 120, 300, 600, 1200],
        'qos_probability_critical': [0.90, 0.95, 0.99, 0.999],
    },
    'fixed': {
        'network.num_devices': 100,
        'traffic.downlink.mean_rate_per_hour': 5,
    }
}

# Experiment 5: ACK Window Size Analysis (Novel Protocol)
ACK_WINDOW_SWEEP = {
    'name': 'ack_window',
    'description': 'Evaluate windowed bitmap ACK efficiency vs window size',
    'parameters': {
        'protocols.novel_lpwan.ack_window_size': [4, 8, 16, 32, 64],
        'traffic.uplink.interval_s': [300, 600, 900],
    },
    'fixed': {
        'network.num_devices': 100,
    }
}

# Experiment 6: Network Type Comparison
NETWORK_SWEEP = {
    'name': 'network_comparison',
    'description': 'Compare performance across LPWAN technologies',
    'parameters': {
        'network.type': ['lorawan', 'nbiot'],
        'network.num_devices': [50, 100, 200],
    },
    'fixed': {
        'traffic.uplink.interval_s': 600,
    }
}

# Experiment 7: Duty Cycle Impact (LoRaWAN specific)
DUTY_CYCLE_SWEEP = {
    'name': 'duty_cycle',
    'description': 'Evaluate impact of duty cycle restrictions',
    'parameters': {
        'network.lorawan.duty_cycle': [0.001, 0.01, 0.1],  # 0.1%, 1%, 10%
        'network.num_devices': [50, 100, 200],
    },
    'fixed': {
        'network.type': 'lorawan',
        'traffic.uplink.interval_s': 600,
    }
}

ALL_EXPERIMENTS = [
    SCALABILITY_SWEEP,
    TRAFFIC_SWEEP,
    COMMAND_SWEEP,
    QOSD_SWEEP,
    ACK_WINDOW_SWEEP,
    NETWORK_SWEEP,
    DUTY_CYCLE_SWEEP,
]


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


def generate_experiment_configs(base_config: dict, experiment: dict, 
                                 num_runs: int = NUM_RUNS_PER_CONFIG) -> list:
    """
    Generate all configurations for an experiment with multiple runs.
    
    IEEE Requirement: Each configuration runs multiple times with different seeds.
    """
    param_keys = list(experiment['parameters'].keys())
    param_values = list(experiment['parameters'].values())
    
    # Generate all parameter combinations
    combinations = list(itertools.product(*param_values))
    
    configs = []
    config_id = 1
    
    for combo in combinations:
        # For each parameter combination, generate multiple runs
        seeds = generate_seeds(BASE_SEED, num_runs)
        
        for run_id, seed in enumerate(seeds):
            config = deepcopy(base_config)
            
            # Apply fixed parameters
            for key, value in experiment.get('fixed', {}).items():
                set_nested_value(config, key, value)
            
            # Apply varied parameters
            for key, value in zip(param_keys, combo):
                # Handle special compound parameters
                if key == 'qos_deadline_critical_s':
                    qos_classes = get_nested_value(config, 'protocols.novel_lpwan.qos_classes', [])
                    for qc in qos_classes:
                        if qc.get('name') == 'critical':
                            qc['deadline_s'] = value
                elif key == 'qos_probability_critical':
                    qos_classes = get_nested_value(config, 'protocols.novel_lpwan.qos_classes', [])
                    for qc in qos_classes:
                        if qc.get('name') == 'critical':
                            qc['probability'] = value
                else:
                    set_nested_value(config, key, value)
            
            # Set seed for this run
            config['simulation']['seed'] = seed
            config['simulation']['run_id'] = run_id + 1
            
            configs.append({
                'id': config_id,
                'experiment': experiment['name'],
                'params': dict(zip(param_keys, combo)),
                'run_id': run_id + 1,
                'seed': seed,
                'config': config
            })
            
            config_id += 1
    
    return configs


def save_experiment_configs(configs: list, output_dir: Path, experiment_name: str):
    """Save experiment configurations with proper organization."""
    exp_dir = output_dir / experiment_name
    exp_dir.mkdir(parents=True, exist_ok=True)
    
    # Group by parameter combination
    param_groups = {}
    for cfg in configs:
        key = str(cfg['params'])
        if key not in param_groups:
            param_groups[key] = []
        param_groups[key].append(cfg)
    
    # Save index
    index = {
        'experiment': experiment_name,
        'generated': datetime.now().isoformat(),
        'num_configs': len(configs),
        'num_param_combinations': len(param_groups),
        'runs_per_combination': NUM_RUNS_PER_CONFIG,
        'base_seed': BASE_SEED,
        'parameter_combinations': []
    }
    
    # Save configs
    for params_key, group in param_groups.items():
        combo_info = {
            'params': group[0]['params'],
            'num_runs': len(group),
            'config_files': []
        }
        
        for cfg in group:
            filename = f"cfg_{cfg['id']:04d}_run{cfg['run_id']:02d}.yaml"
            filepath = exp_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# Experiment: {experiment_name}\n")
                f.write(f"# Parameters: {cfg['params']}\n")
                f.write(f"# Run: {cfg['run_id']}/{NUM_RUNS_PER_CONFIG}\n")
                f.write(f"# Seed: {cfg['seed']}\n")
                f.write("#\n")
                yaml.dump(cfg['config'], f, default_flow_style=False)
            
            combo_info['config_files'].append(filename)
        
        index['parameter_combinations'].append(combo_info)
    
    # Save index
    with open(exp_dir / '_index.yaml', 'w') as f:
        yaml.dump(index, f, default_flow_style=False)
    
    print(f"  Generated {len(configs)} configs for '{experiment_name}'")
    print(f"    - {len(param_groups)} parameter combinations")
    print(f"    - {NUM_RUNS_PER_CONFIG} runs each")
    
    return len(configs)


def main():
    parser = argparse.ArgumentParser(
        description='Generate IEEE Access compliant experiment configurations'
    )
    parser.add_argument(
        '--base', '-b',
        type=str,
        default='sim/configs/base_ieee.yaml',
        help='Path to IEEE-compliant base configuration'
    )
    parser.add_argument(
        '--out', '-o',
        type=str,
        default='sim/configs/ieee_experiments',
        help='Output directory for experiment configs'
    )
    parser.add_argument(
        '--experiment', '-e',
        type=str,
        choices=[e['name'] for e in ALL_EXPERIMENTS] + ['all'],
        default='all',
        help='Which experiment to generate'
    )
    parser.add_argument(
        '--runs', '-r',
        type=int,
        default=NUM_RUNS_PER_CONFIG,
        help=f'Number of runs per configuration (default: {NUM_RUNS_PER_CONFIG})'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Quick mode: only 5 runs per config (for testing)'
    )
    
    args = parser.parse_args()
    
    base_path = Path(args.base)
    output_dir = Path(args.out)
    
    # Use quick mode runs if specified
    num_runs = 5 if args.quick else args.runs
    
    print("="*60)
    print("IEEE ACCESS COMPLIANT EXPERIMENT GENERATOR")
    print("="*60)
    print(f"\nBase config: {base_path}")
    print(f"Output directory: {output_dir}")
    print(f"Runs per configuration: {num_runs}")
    print()
    
    # Load base config
    if not base_path.exists():
        # Try alternative path
        alt_path = Path('sim/configs/base.yaml')
        if alt_path.exists():
            base_path = alt_path
            print(f"Using alternative base config: {base_path}")
        else:
            print(f"ERROR: Base config not found: {base_path}")
            return 1
    
    base_config = load_base_config(base_path)
    
    # Select experiments
    if args.experiment == 'all':
        experiments = ALL_EXPERIMENTS
    else:
        experiments = [e for e in ALL_EXPERIMENTS if e['name'] == args.experiment]
    
    # Generate configs
    total_configs = 0
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save master index
    master_index = {
        'generated': datetime.now().isoformat(),
        'base_config': str(base_path),
        'runs_per_config': num_runs,
        'experiments': []
    }
    
    for experiment in experiments:
        print(f"\nGenerating: {experiment['name']}")
        print(f"  Description: {experiment['description']}")
        
        configs = generate_experiment_configs(base_config, experiment, num_runs)
        count = save_experiment_configs(configs, output_dir, experiment['name'])
        
        total_configs += count
        master_index['experiments'].append({
            'name': experiment['name'],
            'description': experiment['description'],
            'num_configs': count,
            'parameters': experiment['parameters'],
            'fixed': experiment.get('fixed', {})
        })
    
    # Save master index
    with open(output_dir / '_master_index.yaml', 'w') as f:
        yaml.dump(master_index, f, default_flow_style=False)
    
    print(f"\n{'='*60}")
    print(f"GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"\nTotal configurations: {total_configs}")
    print(f"Output directory: {output_dir}")
    print(f"\nExperiment directories:")
    for exp in experiments:
        print(f"  - {exp['name']}/")
    
    # Estimate runtime
    est_time_per_config_min = 0.1  # Rough estimate
    total_time_hours = (total_configs * est_time_per_config_min) / 60
    print(f"\nEstimated total runtime: {total_time_hours:.1f} hours")
    print(f"  (at ~{est_time_per_config_min*60:.0f} seconds per config)")
    
    return 0


if __name__ == "__main__":
    exit(main())
