"""
Traffic Generator Module
========================
Generates synthetic traffic patterns for simulation.
"""

import logging
from typing import List, Dict, Any
import numpy as np
import simpy

logger = logging.getLogger(__name__)


class TrafficGenerator:
    """
    Generates uplink and downlink traffic for simulation.
    
    Traffic patterns:
    - Uplink: periodic, poisson, event-driven
    - Downlink: uniform, bursty, scheduled
    """
    
    def __init__(self, env: simpy.Environment, config: dict,
                 devices: List['EndDevice'], gateway: 'Gateway',
                 metrics: 'MetricsCollector'):
        self.env = env
        self.config = config
        self.devices = devices
        self.gateway = gateway
        self.metrics = metrics
        
        # Uplink config
        uplink_cfg = config.get('uplink', {})
        self.uplink_pattern = uplink_cfg.get('pattern', 'periodic')
        self.uplink_interval_ms = uplink_cfg.get('interval_s', 600) * 1000
        self.uplink_payload_size = uplink_cfg.get('payload_bytes', 20)
        self.uplink_jitter = uplink_cfg.get('jitter_ratio', 0.1)
        
        # Downlink config
        downlink_cfg = config.get('downlink', {})
        self.downlink_pattern = downlink_cfg.get('pattern', 'bursty')
        self.downlink_rate = downlink_cfg.get('mean_rate_per_hour', 2)
        self.downlink_payload_size = downlink_cfg.get('payload_bytes', 10)
        self.priority_dist = downlink_cfg.get('priority_distribution', {
            'critical': 0.05,
            'normal': 0.25,
            'best_effort': 0.70
        })
        
        # Command pull config
        cmd_pull_cfg = config.get('command_pull', {})
        self.cmd_pull_enabled = cmd_pull_cfg.get('enabled', True)
        self.cmd_budget_default = cmd_pull_cfg.get('budget_default', 3)
        
        logger.info(f"TrafficGenerator initialized: uplink={self.uplink_pattern}, downlink={self.downlink_pattern}")
    
    def run(self):
        """Main traffic generation process."""
        # Start uplink generator for each device
        for device in self.devices:
            self.env.process(self._generate_uplink(device))
        
        # Start downlink command generator
        self.env.process(self._generate_downlink_commands())
        
        yield self.env.timeout(0)  # Yield to start
    
    def _generate_uplink(self, device: 'EndDevice'):
        """Generate uplink traffic for a device."""
        # Initial random offset to avoid synchronization
        initial_delay = np.random.uniform(0, self.uplink_interval_ms)
        yield self.env.timeout(initial_delay)
        
        while True:
            # Generate payload
            payload = self._generate_telemetry_payload()
            
            # Determine QoS class (mostly normal/best-effort for telemetry)
            qos_class = np.random.choice(
                ['normal', 'best_effort'],
                p=[0.3, 0.7]
            )
            
            # Queue uplink
            device.queue_uplink(payload, qos_class)
            
            # Calculate next interval
            if self.uplink_pattern == 'periodic':
                jitter = np.random.uniform(-self.uplink_jitter, self.uplink_jitter)
                interval = self.uplink_interval_ms * (1 + jitter)
            elif self.uplink_pattern == 'poisson':
                interval = np.random.exponential(self.uplink_interval_ms)
            else:  # event_driven
                # Simulate sensor events
                interval = np.random.exponential(self.uplink_interval_ms * 2)
            
            yield self.env.timeout(max(1000, interval))  # Min 1 second
    
    def _generate_telemetry_payload(self) -> bytes:
        """Generate synthetic telemetry payload."""
        # Simulate sensor readings
        temperature = np.random.uniform(15, 35)
        humidity = np.random.uniform(30, 80)
        battery = np.random.uniform(2.8, 4.2)
        
        # Pack as bytes (simplified)
        import struct
        payload = struct.pack('>fff', temperature, humidity, battery)
        
        # Pad or truncate to target size
        if len(payload) < self.uplink_payload_size:
            payload += bytes(self.uplink_payload_size - len(payload))
        
        return payload[:self.uplink_payload_size]
    
    def _generate_downlink_commands(self):
        """Generate downlink commands to devices for ALL enabled protocols."""
        # Calculate inter-arrival time
        cmds_per_device_per_ms = self.downlink_rate / 3600000
        
        # Get enabled protocols from first device
        enabled_protocols = list(self.devices[0].protocols.keys()) if self.devices else ['novel_lpwan']
        
        while True:
            # Select random device
            device = np.random.choice(self.devices)
            
            # Generate command
            priority = np.random.choice(
                list(self.priority_dist.keys()),
                p=list(self.priority_dist.values())
            )
            
            # Command type (0-7 for novel protocol)
            cmd_type = np.random.randint(0, 8)
            
            # Payload
            payload = self._generate_command_payload(cmd_type)
            
            # Deadline based on priority
            if priority == 'critical':
                deadline_s = 600  # 10 minutes
                probability = 0.99
            elif priority == 'normal':
                deadline_s = 3600  # 1 hour
                probability = 0.90
            else:
                deadline_s = 86400  # 1 day
                probability = 0.50
            
            # Queue command at gateway for ALL enabled protocols
            # This ensures fair comparison - same commands are sent to all protocols
            for proto_name in enabled_protocols:
                self.gateway.queue_command(
                    device_id=device.device_id,
                    cmd_type=cmd_type,
                    payload=payload,
                    priority=priority,
                    deadline_s=deadline_s,
                    probability=probability,
                    protocol=proto_name  # Specify protocol for each command
                )
            
            # Calculate next command arrival
            # Poisson process: inter-arrival is exponential
            num_devices = len(self.devices)
            total_rate_per_ms = cmds_per_device_per_ms * num_devices
            
            if self.downlink_pattern == 'uniform':
                interval = 1 / total_rate_per_ms if total_rate_per_ms > 0 else 60000
            elif self.downlink_pattern == 'bursty':
                # Bursts: occasionally generate multiple commands quickly
                if np.random.random() < 0.1:  # 10% chance of burst
                    interval = np.random.exponential(1000)  # Fast burst
                else:
                    interval = np.random.exponential(1 / total_rate_per_ms) if total_rate_per_ms > 0 else 60000
            else:  # scheduled
                # Commands at specific times (e.g., hourly)
                interval = 3600000 / self.downlink_rate
            
            yield self.env.timeout(max(100, interval))
    
    def _generate_command_payload(self, cmd_type: int) -> bytes:
        """Generate command payload based on type."""
        import struct
        
        if cmd_type == 0:  # Configuration update
            # e.g., new reporting interval
            new_interval = np.random.randint(60, 900)
            return struct.pack('>H', new_interval)
        
        elif cmd_type == 1:  # Threshold update
            threshold = np.random.uniform(0, 100)
            return struct.pack('>f', threshold)
        
        elif cmd_type == 2:  # Mode change
            mode = np.random.randint(0, 4)
            return bytes([mode])
        
        elif cmd_type == 3:  # Actuator command
            action = np.random.randint(0, 2)  # on/off
            return bytes([action])
        
        elif cmd_type == 4:  # Time sync
            import time
            timestamp = int(time.time())
            return struct.pack('>I', timestamp)
        
        else:
            # Generic command
            return bytes(np.random.randint(0, 256, size=self.downlink_payload_size))
