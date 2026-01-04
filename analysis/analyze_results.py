#!/usr/bin/env python3
"""
Results Analyzer - Compare Protocol Performance
===============================================
Analyze and visualize simulation results across protocols.
"""

import argparse
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yaml


def load_sweep_results(sweep_dir: Path) -> pd.DataFrame:
    """Load all results from a sweep directory."""
    
    results = []
    
    for config_dir in sweep_dir.iterdir():
        if not config_dir.is_dir() or config_dir.name.startswith('_'):
            continue
        
        # Load config
        config_path = config_dir / "config.yaml"
        if not config_path.exists():
            continue
            
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Load metrics
        metrics_path = config_dir / "protocol_comparison.csv"
        if not metrics_path.exists():
            continue
            
        df = pd.read_csv(metrics_path)
        
        # Add config parameters
        df['config_id'] = config_dir.name
        df['num_devices'] = config['network']['num_devices']
        df['network_type'] = config['network']['type']
        df['uplink_interval_s'] = config['traffic']['uplink']['interval_s']
        
        results.append(df)
    
    if not results:
        return pd.DataFrame()
    
    return pd.concat(results, ignore_index=True)


def plot_delivery_rate_comparison(df: pd.DataFrame, output_dir: Path):
    """Plot delivery rate comparison across protocols."""
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    protocols = df['protocol'].unique()
    x = np.arange(len(protocols))
    width = 0.35
    
    means = df.groupby('protocol')['delivery_rate'].mean()
    stds = df.groupby('protocol')['delivery_rate'].std()
    
    bars = ax.bar(x, means, width, yerr=stds, capsize=5, 
                  color=['#2ecc71', '#3498db', '#e74c3c'])
    
    ax.set_ylabel('Delivery Rate')
    ax.set_title('Protocol Delivery Rate Comparison')
    ax.set_xticks(x)
    ax.set_xticklabels(protocols)
    ax.set_ylim(0, 1.1)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'delivery_rate_comparison.png', dpi=150)
    plt.close()


def plot_energy_per_message(df: pd.DataFrame, output_dir: Path):
    """Plot energy per message comparison."""
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    for proto in df['protocol'].unique():
        proto_df = df[df['protocol'] == proto]
        grouped = proto_df.groupby('num_devices')['energy_per_msg_mj'].mean()
        ax.plot(grouped.index, grouped.values, marker='o', label=proto)
    
    ax.set_xlabel('Number of Devices')
    ax.set_ylabel('Energy per Message (mJ)')
    ax.set_title('Energy Efficiency vs Scale')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'energy_per_message.png', dpi=150)
    plt.close()


def plot_latency_distribution(df: pd.DataFrame, output_dir: Path):
    """Plot command latency distribution."""
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    protocols = df['protocol'].unique()
    positions = range(len(protocols))
    
    data = [df[df['protocol'] == p]['avg_cmd_latency_ms'].dropna() for p in protocols]
    
    bp = ax.boxplot(data, positions=positions, widths=0.6, patch_artist=True)
    
    colors = ['#2ecc71', '#3498db', '#e74c3c']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    ax.set_xticklabels(protocols)
    ax.set_ylabel('Command Latency (ms)')
    ax.set_title('Command Delivery Latency Distribution')
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'latency_distribution.png', dpi=150)
    plt.close()


def plot_ack_efficiency(df: pd.DataFrame, output_dir: Path):
    """Plot ACK efficiency for novel protocol."""
    
    novel_df = df[df['protocol'] == 'novel_lpwan']
    
    if novel_df.empty or 'ack_efficiency' not in novel_df.columns:
        return
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    grouped = novel_df.groupby('uplink_interval_s')['ack_efficiency'].mean()
    
    ax.bar(grouped.index.astype(str), grouped.values, color='#2ecc71')
    
    ax.set_xlabel('Uplink Interval (s)')
    ax.set_ylabel('ACK Efficiency (messages/ACK)')
    ax.set_title('Windowed Bitmap ACK Efficiency')
    ax.grid(True, alpha=0.3, axis='y')
    
    # Add text annotation
    ax.text(0.95, 0.95, f'Avg: {grouped.mean():.1f} msgs/ACK',
            transform=ax.transAxes, ha='right', va='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    plt.savefig(output_dir / 'ack_efficiency.png', dpi=150)
    plt.close()


def generate_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """Generate summary statistics table."""
    
    summary = df.groupby('protocol').agg({
        'delivery_rate': ['mean', 'std'],
        'avg_cmd_latency_ms': ['mean', 'std'],
        'energy_per_msg_mj': ['mean', 'std'],
        'uplink_bytes': 'sum',
        'downlink_bytes': 'sum',
    })
    
    # Flatten column names
    summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
    
    return summary.round(4)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze and visualize simulation results'
    )
    parser.add_argument(
        '--sweep-dir', '-s',
        type=str,
        required=True,
        help='Path to sweep results directory'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output directory for plots (default: sweep_dir/analysis)'
    )
    
    args = parser.parse_args()
    
    sweep_dir = Path(args.sweep_dir)
    output_dir = Path(args.output) if args.output else sweep_dir / 'analysis'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading results from: {sweep_dir}")
    
    df = load_sweep_results(sweep_dir)
    
    if df.empty:
        print("No results found!")
        return 1
    
    print(f"Loaded {len(df)} result rows")
    print(f"Protocols: {df['protocol'].unique()}")
    print()
    
    # Generate plots
    print("Generating plots...")
    plot_delivery_rate_comparison(df, output_dir)
    plot_energy_per_message(df, output_dir)
    plot_latency_distribution(df, output_dir)
    plot_ack_efficiency(df, output_dir)
    
    # Generate summary
    print("\nSummary Statistics:")
    print("=" * 60)
    summary = generate_summary_table(df)
    print(summary.to_string())
    
    # Save summary
    summary.to_csv(output_dir / 'summary_stats.csv')
    
    print(f"\nPlots and summary saved to: {output_dir}")
    
    return 0


if __name__ == "__main__":
    exit(main())
