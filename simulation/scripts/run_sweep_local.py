#!/usr/bin/env python3
"""
Local Sweep Runner (Replacement for SLURM)
==========================================
Orchestrates parallel simulation runs using Docker on local machine.
Designed for Windows 11 + Docker Desktop (WSL2 backend).
"""

import subprocess
import os
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import argparse

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "sim" / "configs" / "sweep"
RESULTS_ROOT = PROJECT_ROOT / "results" / "raw"
IMAGE_NAME = "lpwan-proto-sim"
DEFAULT_MAX_PARALLEL = 4  # Adjust based on CPU cores


def check_docker():
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            print("Error: Docker is not running. Please start Docker Desktop.")
            return False
        return True
    except FileNotFoundError:
        print("Error: Docker not found. Please install Docker Desktop.")
        return False
    except subprocess.TimeoutExpired:
        print("Error: Docker is not responding.")
        return False


def check_image_exists():
    """Check if the simulator image exists."""
    result = subprocess.run(
        ["docker", "images", "-q", IMAGE_NAME],
        capture_output=True,
        text=True
    )
    return bool(result.stdout.strip())


def build_image():
    """Build the Docker image."""
    print(f"Building Docker image '{IMAGE_NAME}'...")
    
    dockerfile_path = PROJECT_ROOT / "docker" / "Dockerfile"
    
    cmd = [
        "docker", "build",
        "-t", IMAGE_NAME,
        "-f", str(dockerfile_path),
        str(PROJECT_ROOT)
    ]
    
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode != 0:
        print("Error: Failed to build Docker image.")
        return False
    
    print("Docker image built successfully.")
    return True


def run_one_config(cfg_path: Path, sweep_name: str, use_docker: bool = True):
    """
    Run simulation for one configuration file.
    
    Args:
        cfg_path: Path to configuration YAML file
        sweep_name: Name of the sweep run
        use_docker: Whether to use Docker (False for direct Python)
    
    Returns:
        Tuple of (config_name, return_code, duration_seconds)
    """
    cfg_name = cfg_path.stem  # e.g., cfg_0001
    out_dir = RESULTS_ROOT / sweep_name / cfg_name
    out_dir.mkdir(parents=True, exist_ok=True)
    
    start_time = datetime.now()
    
    if use_docker:
        # Paths relative to container
        cfg_rel = f"sim/configs/sweep/{cfg_path.name}"
        out_rel = f"results/raw/{sweep_name}/{cfg_name}"
        
        # Convert Windows path to Docker-friendly format
        project_root_docker = str(PROJECT_ROOT).replace("\\", "/")
        
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{project_root_docker}:/opt/lpwan-proto-sim",
            IMAGE_NAME,
            "python3", "sim/run_sim.py",
            "--config", cfg_rel,
            "--output-dir", out_rel
        ]
    else:
        # Direct Python execution - use venv if available
        # Check both project root and parent directory for venv
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            venv_python = PROJECT_ROOT.parent / ".venv" / "Scripts" / "python.exe"
        
        if venv_python.exists():
            python_exe = str(venv_python)
        else:
            python_exe = sys.executable
        
        cmd = [
            python_exe, 
            str(PROJECT_ROOT / "sim" / "run_sim.py"),
            "--config", str(cfg_path),
            "--output-dir", str(out_dir)
        ]
    
    print(f"[START] {cfg_name}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout per run
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        
        if result.returncode != 0:
            print(f"[ERROR] {cfg_name} failed after {duration:.1f}s")
            # Save error log
            error_log = out_dir / "error.log"
            with open(error_log, 'w') as f:
                f.write(f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}")
            return cfg_name, result.returncode, duration
        
        print(f"[OK] {cfg_name} completed in {duration:.1f}s")
        return cfg_name, 0, duration
        
    except subprocess.TimeoutExpired:
        duration = (datetime.now() - start_time).total_seconds()
        print(f"[TIMEOUT] {cfg_name} after {duration:.1f}s")
        return cfg_name, -1, duration
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        print(f"[EXCEPTION] {cfg_name}: {e}")
        return cfg_name, -2, duration


def run_sweep(sweep_name: str, max_parallel: int, config_pattern: str = "*.yaml",
              use_docker: bool = True, dry_run: bool = False, config_dir: Path = None):
    """
    Run parameter sweep with parallel execution.
    
    Args:
        sweep_name: Unique name for this sweep run
        max_parallel: Maximum parallel workers
        config_pattern: Glob pattern for config files
        use_docker: Use Docker containers
        dry_run: Only print what would be run
        config_dir: Directory containing config files
    """
    # Determine config directory
    cfg_dir = Path(config_dir) if config_dir else CONFIG_DIR
    
    # Find config files
    cfg_files = sorted(cfg_dir.glob(config_pattern))
    
    if not cfg_files:
        print(f"No config files found matching '{config_pattern}' in {cfg_dir}")
        return
    
    print(f"Found {len(cfg_files)} configuration files")
    print(f"Sweep name: {sweep_name}")
    print(f"Max parallel workers: {max_parallel}")
    print(f"Using Docker: {use_docker}")
    print()
    
    if dry_run:
        print("Dry run - would process:")
        for cfg in cfg_files:
            print(f"  - {cfg.name}")
        return
    
    # Create results directory
    results_dir = RESULTS_ROOT / sweep_name
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Save sweep metadata
    metadata = {
        'sweep_name': sweep_name,
        'start_time': datetime.now().isoformat(),
        'num_configs': len(cfg_files),
        'max_parallel': max_parallel,
        'use_docker': use_docker,
        'configs': [cfg.name for cfg in cfg_files]
    }
    
    with open(results_dir / "_sweep_meta.json", 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # Run in parallel
    results = []
    
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(run_one_config, cfg, sweep_name, use_docker): cfg 
            for cfg in cfg_files
        }
        
        for future in as_completed(futures):
            cfg = futures[future]
            try:
                name, rc, duration = future.result()
                results.append({
                    'config': name,
                    'return_code': rc,
                    'duration_s': duration,
                    'success': rc == 0
                })
            except Exception as e:
                print(f"[EXCEPTION] {cfg.name}: {e}")
                results.append({
                    'config': cfg.stem,
                    'return_code': -3,
                    'duration_s': 0,
                    'success': False,
                    'error': str(e)
                })
    
    # Summary
    print("\n" + "=" * 60)
    print("SWEEP COMPLETED")
    print("=" * 60)
    
    successful = sum(1 for r in results if r['success'])
    failed = len(results) - successful
    total_time = sum(r['duration_s'] for r in results)
    
    print(f"Total: {len(results)} | Successful: {successful} | Failed: {failed}")
    print(f"Total time: {total_time:.1f}s | Avg per config: {total_time/len(results):.1f}s")
    
    # Save results summary
    metadata['end_time'] = datetime.now().isoformat()
    metadata['results'] = results
    metadata['summary'] = {
        'total': len(results),
        'successful': successful,
        'failed': failed,
        'total_time_s': total_time
    }
    
    with open(results_dir / "_sweep_meta.json", 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\nResults saved to: {results_dir}")
    
    if failed > 0:
        print("\nFailed configs:")
        for r in results:
            if not r['success']:
                print(f"  - {r['config']}: code={r['return_code']}")


def main():
    parser = argparse.ArgumentParser(
        description='Run parameter sweep simulations locally'
    )
    parser.add_argument(
        '--name', '-n',
        type=str,
        default=datetime.now().strftime("sweep_%Y%m%d_%H%M%S"),
        help='Name for this sweep run'
    )
    parser.add_argument(
        '--config-dir', '-c',
        type=str,
        default=None,
        help='Directory containing config files (default: sim/configs/sweep)'
    )
    parser.add_argument(
        '--parallel', '-p',
        type=int,
        default=DEFAULT_MAX_PARALLEL,
        help=f'Maximum parallel workers (default: {DEFAULT_MAX_PARALLEL})'
    )
    parser.add_argument(
        '--pattern',
        type=str,
        default="*.yaml",
        help='Glob pattern for config files'
    )
    parser.add_argument(
        '--no-docker',
        action='store_true',
        help='Run directly with Python instead of Docker'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Only show what would be run'
    )
    parser.add_argument(
        '--build',
        action='store_true',
        help='Build Docker image before running'
    )
    
    args = parser.parse_args()
    
    use_docker = not args.no_docker
    
    if use_docker:
        # Check Docker
        if not check_docker():
            return 1
        
        # Build if requested or image doesn't exist
        if args.build or not check_image_exists():
            if not build_image():
                return 1
    
    # Run sweep
    run_sweep(
        sweep_name=args.name,
        max_parallel=args.parallel,
        config_pattern=args.pattern,
        use_docker=use_docker,
        dry_run=args.dry_run,
        config_dir=args.config_dir
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
