#!/usr/bin/env python3
"""
IEEE Access Compliant Results Analyzer
======================================
Statistical analysis meeting IEEE publication standards:
- 95% Confidence Intervals
- Multiple independent runs (n≥30)
- Non-parametric tests (Mann-Whitney U, Kruskal-Wallis)
- Effect size calculation (Cohen's d)
- Publication-quality figures
"""

import argparse
from pathlib import Path
from typing import Dict, List, Any, Tuple
import warnings

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from scipy import stats
import yaml

# Use non-interactive backend for server/CI environments
matplotlib.use('Agg')

# IEEE Access figure settings
plt.rcParams.update({
    'font.size': 10,
    'font.family': 'serif',
    'figure.figsize': (7, 5),  # IEEE single column width
    'figure.dpi': 300,
    'axes.labelsize': 10,
    'axes.titlesize': 11,
    'legend.fontsize': 9,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'lines.linewidth': 1.5,
    'lines.markersize': 6,
    'errorbar.capsize': 3,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.05,
})


def calculate_confidence_interval(data: np.ndarray, confidence: float = 0.95) -> Tuple[float, float, float]:
    """
    Calculate mean and confidence interval.
    
    Returns:
        Tuple of (mean, ci_lower, ci_upper)
    """
    n = len(data)
    if n < 2:
        return np.mean(data), np.nan, np.nan
    
    mean = np.mean(data)
    se = stats.sem(data)
    
    # Use t-distribution for small samples
    t_value = stats.t.ppf((1 + confidence) / 2, n - 1)
    ci = t_value * se
    
    return mean, mean - ci, mean + ci


def cohens_d(group1: np.ndarray, group2: np.ndarray) -> float:
    """Calculate Cohen's d effect size."""
    n1, n2 = len(group1), len(group2)
    var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
    
    # Pooled standard deviation
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    
    if pooled_std == 0:
        return 0.0
    
    return (np.mean(group1) - np.mean(group2)) / pooled_std


def interpret_effect_size(d: float) -> str:
    """Interpret Cohen's d effect size."""
    d = abs(d)
    if d < 0.2:
        return "negligible"
    elif d < 0.5:
        return "small"
    elif d < 0.8:
        return "medium"
    else:
        return "large"


def perform_statistical_tests(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    """
    Perform comprehensive statistical tests between protocols.
    
    IEEE requirement: Use appropriate statistical tests with significance levels.
    """
    protocols = df['protocol'].unique()
    results = {
        'metric': metric,
        'normality_tests': {},
        'pairwise_tests': [],
        'overall_test': None,
    }
    
    # Check normality for each protocol (Shapiro-Wilk)
    for proto in protocols:
        data = df[df['protocol'] == proto][metric].dropna()
        if len(data) >= 3:
            stat, p_value = stats.shapiro(data)
            results['normality_tests'][proto] = {
                'statistic': stat,
                'p_value': p_value,
                'is_normal': p_value > 0.05
            }
    
    # Overall test: Kruskal-Wallis (non-parametric ANOVA)
    groups = [df[df['protocol'] == p][metric].dropna() for p in protocols]
    groups = [g for g in groups if len(g) > 0]
    
    if len(groups) >= 2:
        stat, p_value = stats.kruskal(*groups)
        results['overall_test'] = {
            'test': 'Kruskal-Wallis H',
            'statistic': stat,
            'p_value': p_value,
            'significant': p_value < 0.05
        }
    
    # Pairwise comparisons: Mann-Whitney U (non-parametric)
    for i, proto1 in enumerate(protocols):
        for proto2 in protocols[i+1:]:
            data1 = df[df['protocol'] == proto1][metric].dropna()
            data2 = df[df['protocol'] == proto2][metric].dropna()
            
            if len(data1) < 2 or len(data2) < 2:
                continue
            
            # Mann-Whitney U test
            stat, p_value = stats.mannwhitneyu(data1, data2, alternative='two-sided')
            
            # Effect size
            effect = cohens_d(data1.values, data2.values)
            
            results['pairwise_tests'].append({
                'protocol_1': proto1,
                'protocol_2': proto2,
                'test': 'Mann-Whitney U',
                'statistic': stat,
                'p_value': p_value,
                'significant': p_value < 0.05,
                'cohens_d': effect,
                'effect_interpretation': interpret_effect_size(effect),
                'mean_1': np.mean(data1),
                'mean_2': np.mean(data2),
                'improvement_pct': ((np.mean(data1) - np.mean(data2)) / np.mean(data2) * 100) if np.mean(data2) != 0 else 0
            })
    
    return results


def load_sweep_results(sweep_dir: Path) -> pd.DataFrame:
    """Load all results from a sweep directory with run information."""
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
        df['run_id'] = config.get('simulation', {}).get('seed', 0)
        df['num_devices'] = config['network']['num_devices']
        df['network_type'] = config['network']['type']
        df['uplink_interval_s'] = config['traffic']['uplink']['interval_s']
        
        results.append(df)
    
    if not results:
        return pd.DataFrame()
    
    return pd.concat(results, ignore_index=True)


def generate_ieee_summary_table(df: pd.DataFrame, output_dir: Path):
    """
    Generate IEEE-style summary table with confidence intervals.
    
    Format: Mean ± CI (95%)
    """
    metrics = ['delivery_rate', 'energy_per_msg_mj', 'avg_cmd_latency_ms']
    protocols = df['protocol'].unique()
    
    table_data = []
    
    for proto in protocols:
        proto_df = df[df['protocol'] == proto]
        row = {'Protocol': proto}
        
        for metric in metrics:
            data = proto_df[metric].dropna()
            if len(data) > 0:
                mean, ci_low, ci_high = calculate_confidence_interval(data.values)
                ci_half = (ci_high - ci_low) / 2
                row[metric] = f"{mean:.4f} ± {ci_half:.4f}"
            else:
                row[metric] = "N/A"
        
        table_data.append(row)
    
    summary_df = pd.DataFrame(table_data)
    
    # Save as CSV
    summary_df.to_csv(output_dir / 'ieee_summary_table.csv', index=False)
    
    # Save as LaTeX
    latex_table = summary_df.to_latex(index=False, escape=False, 
                                       caption="Protocol Performance Comparison (Mean ± 95\\% CI)",
                                       label="tab:protocol_comparison")
    with open(output_dir / 'ieee_summary_table.tex', 'w') as f:
        f.write(latex_table)
    
    return summary_df


def plot_ieee_comparison_bars(df: pd.DataFrame, metric: str, output_dir: Path,
                              ylabel: str, title: str, filename: str):
    """Generate IEEE-quality bar chart with confidence intervals."""
    
    fig, ax = plt.subplots(figsize=(7, 5))
    
    protocols = df['protocol'].unique()
    x = np.arange(len(protocols))
    
    means = []
    ci_errors = []
    
    for proto in protocols:
        data = df[df['protocol'] == proto][metric].dropna().values
        mean, ci_low, ci_high = calculate_confidence_interval(data)
        means.append(mean)
        ci_errors.append((mean - ci_low, ci_high - mean))
    
    ci_errors = np.array(ci_errors).T
    
    colors = ['#2ecc71', '#3498db', '#e74c3c']
    bars = ax.bar(x, means, width=0.6, yerr=ci_errors, capsize=5,
                  color=colors[:len(protocols)], edgecolor='black', linewidth=0.5)
    
    ax.set_ylabel(ylabel)
    ax.set_xlabel('Protocol')
    ax.set_xticks(x)
    ax.set_xticklabels(protocols)
    ax.set_title(title)
    
    # Add value labels on bars
    for bar, mean in zip(bars, means):
        height = bar.get_height()
        ax.annotate(f'{mean:.3f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=8)
    
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    plt.savefig(output_dir / filename, dpi=300, format='png')
    plt.savefig(output_dir / filename.replace('.png', '.pdf'), format='pdf')
    plt.close()


def plot_ieee_scalability(df: pd.DataFrame, output_dir: Path):
    """Plot scalability analysis with confidence bands."""
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    protocols = df['protocol'].unique()
    colors = {'novel_lpwan': '#2ecc71', 'mqtt_sn': '#3498db', 'coap': '#e74c3c'}
    
    # Left: Delivery Rate vs Number of Devices
    ax = axes[0]
    for proto in protocols:
        proto_df = df[df['protocol'] == proto]
        grouped = proto_df.groupby('num_devices')['delivery_rate']
        
        x = sorted(grouped.groups.keys())
        means = []
        ci_lows = []
        ci_highs = []
        
        for n in x:
            data = grouped.get_group(n).values
            mean, ci_low, ci_high = calculate_confidence_interval(data)
            means.append(mean)
            ci_lows.append(ci_low)
            ci_highs.append(ci_high)
        
        ax.plot(x, means, marker='o', label=proto, color=colors.get(proto, 'gray'))
        ax.fill_between(x, ci_lows, ci_highs, alpha=0.2, color=colors.get(proto, 'gray'))
    
    ax.set_xlabel('Number of Devices')
    ax.set_ylabel('Packet Delivery Ratio')
    ax.set_title('(a) Scalability: Delivery Rate')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Right: Energy vs Number of Devices
    ax = axes[1]
    for proto in protocols:
        proto_df = df[df['protocol'] == proto]
        grouped = proto_df.groupby('num_devices')['energy_per_msg_mj']
        
        x = sorted(grouped.groups.keys())
        means = []
        ci_lows = []
        ci_highs = []
        
        for n in x:
            data = grouped.get_group(n).values
            mean, ci_low, ci_high = calculate_confidence_interval(data)
            means.append(mean)
            ci_lows.append(ci_low)
            ci_highs.append(ci_high)
        
        ax.plot(x, means, marker='s', label=proto, color=colors.get(proto, 'gray'))
        ax.fill_between(x, ci_lows, ci_highs, alpha=0.2, color=colors.get(proto, 'gray'))
    
    ax.set_xlabel('Number of Devices')
    ax.set_ylabel('Energy per Message (mJ)')
    ax.set_title('(b) Scalability: Energy Efficiency')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'ieee_scalability.png', dpi=300)
    plt.savefig(output_dir / 'ieee_scalability.pdf', format='pdf')
    plt.close()


def plot_ieee_cdf(df: pd.DataFrame, metric: str, output_dir: Path,
                  xlabel: str, title: str, filename: str):
    """Plot CDF comparison - common in IEEE papers."""
    
    fig, ax = plt.subplots(figsize=(7, 5))
    
    protocols = df['protocol'].unique()
    colors = {'novel_lpwan': '#2ecc71', 'mqtt_sn': '#3498db', 'coap': '#e74c3c'}
    linestyles = {'novel_lpwan': '-', 'mqtt_sn': '--', 'coap': '-.'}
    
    for proto in protocols:
        data = df[df['protocol'] == proto][metric].dropna().sort_values()
        cdf = np.arange(1, len(data) + 1) / len(data)
        
        ax.plot(data, cdf, label=proto, 
                color=colors.get(proto, 'gray'),
                linestyle=linestyles.get(proto, '-'))
    
    ax.set_xlabel(xlabel)
    ax.set_ylabel('CDF')
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 1)
    
    plt.tight_layout()
    plt.savefig(output_dir / filename, dpi=300)
    plt.savefig(output_dir / filename.replace('.png', '.pdf'), format='pdf')
    plt.close()


def generate_statistical_report(df: pd.DataFrame, output_dir: Path):
    """Generate comprehensive statistical analysis report."""
    
    metrics_to_test = ['delivery_rate', 'energy_per_msg_mj', 'avg_cmd_latency_ms']
    
    report = {
        'analysis_date': pd.Timestamp.now().isoformat(),
        'num_runs': len(df['config_id'].unique()),
        'protocols': list(df['protocol'].unique()),
        'statistical_tests': {}
    }
    
    for metric in metrics_to_test:
        if metric in df.columns:
            report['statistical_tests'][metric] = perform_statistical_tests(df, metric)
    
    # Save report
    with open(output_dir / 'statistical_analysis.yaml', 'w') as f:
        yaml.dump(report, f, default_flow_style=False, allow_unicode=True)
    
    # Generate human-readable summary
    with open(output_dir / 'statistical_summary.txt', 'w') as f:
        f.write("="*70 + "\n")
        f.write("STATISTICAL ANALYSIS REPORT - IEEE Access Standards\n")
        f.write("="*70 + "\n\n")
        
        f.write(f"Number of experimental runs: {report['num_runs']}\n")
        f.write(f"Protocols compared: {', '.join(report['protocols'])}\n")
        f.write(f"Confidence level: 95%\n\n")
        
        for metric, tests in report['statistical_tests'].items():
            f.write(f"\n{'='*50}\n")
            f.write(f"Metric: {metric}\n")
            f.write(f"{'='*50}\n\n")
            
            # Overall test
            if tests['overall_test']:
                ot = tests['overall_test']
                f.write(f"Overall Test ({ot['test']}):\n")
                f.write(f"  H-statistic: {ot['statistic']:.4f}\n")
                f.write(f"  p-value: {ot['p_value']:.6f}\n")
                f.write(f"  Significant difference: {'YES' if ot['significant'] else 'NO'}\n\n")
            
            # Pairwise comparisons
            f.write("Pairwise Comparisons:\n")
            for pw in tests['pairwise_tests']:
                f.write(f"\n  {pw['protocol_1']} vs {pw['protocol_2']}:\n")
                f.write(f"    Mean ({pw['protocol_1']}): {pw['mean_1']:.4f}\n")
                f.write(f"    Mean ({pw['protocol_2']}): {pw['mean_2']:.4f}\n")
                f.write(f"    p-value: {pw['p_value']:.6f}\n")
                f.write(f"    Significant: {'YES' if pw['significant'] else 'NO'}\n")
                f.write(f"    Cohen's d: {pw['cohens_d']:.4f} ({pw['effect_interpretation']})\n")
                f.write(f"    Improvement: {pw['improvement_pct']:.2f}%\n")
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description='IEEE Access compliant statistical analysis'
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
        help='Output directory for analysis (default: sweep_dir/ieee_analysis)'
    )
    
    args = parser.parse_args()
    
    sweep_dir = Path(args.sweep_dir)
    output_dir = Path(args.output) if args.output else sweep_dir / 'ieee_analysis'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("="*60)
    print("IEEE ACCESS COMPLIANT STATISTICAL ANALYSIS")
    print("="*60)
    print(f"\nLoading results from: {sweep_dir}")
    
    df = load_sweep_results(sweep_dir)
    
    if df.empty:
        print("ERROR: No results found!")
        return 1
    
    print(f"Loaded {len(df)} result rows")
    print(f"Protocols: {df['protocol'].unique()}")
    print(f"Configurations: {df['config_id'].nunique()}")
    print()
    
    # Generate IEEE summary table
    print("Generating IEEE summary table...")
    summary = generate_ieee_summary_table(df, output_dir)
    print(summary.to_string())
    print()
    
    # Statistical tests
    print("Performing statistical tests...")
    report = generate_statistical_report(df, output_dir)
    
    # Generate IEEE-quality plots
    print("Generating publication-quality figures...")
    
    plot_ieee_comparison_bars(df, 'delivery_rate', output_dir,
                              'Packet Delivery Ratio', 
                              'Protocol Comparison: Delivery Rate',
                              'ieee_delivery_rate.png')
    
    plot_ieee_comparison_bars(df, 'energy_per_msg_mj', output_dir,
                              'Energy per Message (mJ)',
                              'Protocol Comparison: Energy Efficiency',
                              'ieee_energy_efficiency.png')
    
    if df['num_devices'].nunique() > 1:
        plot_ieee_scalability(df, output_dir)
    
    plot_ieee_cdf(df, 'delivery_rate', output_dir,
                  'Packet Delivery Ratio', 
                  'CDF: Delivery Rate Distribution',
                  'ieee_cdf_delivery.png')
    
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"\nOutput files saved to: {output_dir}")
    print("\nGenerated files:")
    for f in sorted(output_dir.iterdir()):
        print(f"  - {f.name}")
    
    # Print key findings
    print(f"\n{'='*60}")
    print("KEY FINDINGS")
    print(f"{'='*60}")
    
    for metric, tests in report['statistical_tests'].items():
        if tests['overall_test'] and tests['overall_test']['significant']:
            print(f"\n{metric}: Significant difference found (p < 0.05)")
            for pw in tests['pairwise_tests']:
                if pw['significant']:
                    better = pw['protocol_1'] if pw['mean_1'] > pw['mean_2'] else pw['protocol_2']
                    print(f"  - {better} outperforms by {abs(pw['improvement_pct']):.1f}% ({pw['effect_interpretation']} effect)")
    
    return 0


if __name__ == "__main__":
    exit(main())
