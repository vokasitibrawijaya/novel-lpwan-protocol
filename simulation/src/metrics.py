"""
Metrics Collector Module
========================
Collects and aggregates simulation metrics for analysis.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from collections import defaultdict
import pandas as pd
import numpy as np
import simpy

logger = logging.getLogger(__name__)


@dataclass
class TransmissionRecord:
    """Record of a single transmission."""
    timestamp_ms: float
    device_id: int
    protocol: str
    direction: str
    packet_size: int
    airtime_ms: float
    success: bool
    seq_num: int = 0
    qos_class: str = 'normal'
    energy_mj: float = 0.0


@dataclass
class CommandRecord:
    """Record of a command delivery."""
    cmd_id: int
    device_id: int
    protocol: str
    cmd_type: int
    created_ms: float
    delivered_ms: float = 0.0
    expired: bool = False
    applied: bool = False
    latency_ms: float = 0.0


class MetricsCollector:
    """
    Collects simulation metrics for protocol comparison.
    
    Key metrics:
    - Delivery rate (uplink/downlink)
    - Delivery latency
    - Energy per message
    - Airtime usage
    - Downlink efficiency
    - Protocol state memory
    - Retransmission rate
    - QoS deadline compliance
    """
    
    def __init__(self, config: dict, output_dir: 'Path', warmup_ms: float):
        self.config = config
        self.output_dir = output_dir
        self.warmup_ms = warmup_ms
        
        self.collect_interval_ms = config.get('collect_interval_s', 60) * 1000
        self.enabled_metrics = config.get('enabled', [])
        
        # Raw records
        self.transmissions: List[TransmissionRecord] = []
        self.commands: List[CommandRecord] = []
        
        # Aggregated metrics per protocol
        self.metrics: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(float))
        
        # Per-device tracking
        self.device_energy: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.device_messages: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # ACK tracking for efficiency calculation
        self.acks_sent: Dict[str, int] = defaultdict(int)
        self.messages_acked: Dict[str, int] = defaultdict(int)
        
        # Periodic snapshots
        self.snapshots: List[Dict] = []
        
        logger.info(f"MetricsCollector initialized, warmup={warmup_ms}ms")
    
    def record_transmission(self, packet: 'Packet', success: bool):
        """Record a transmission event."""
        record = TransmissionRecord(
            timestamp_ms=packet.timestamp_ms,
            device_id=packet.source_id if packet.direction == 'uplink' else packet.dest_id,
            protocol=packet.protocol,
            direction=packet.direction,
            packet_size=packet.size_bytes,
            airtime_ms=packet.airtime_ms,
            success=success,
            seq_num=packet.seq_num,
            qos_class=packet.qos_class
        )
        self.transmissions.append(record)
        
        # Update aggregates
        proto = packet.protocol
        if success:
            self.metrics[proto][f'{packet.direction}_success'] += 1
        else:
            self.metrics[proto][f'{packet.direction}_failed'] += 1
        
        self.metrics[proto][f'{packet.direction}_bytes'] += packet.size_bytes
        self.metrics[proto][f'{packet.direction}_airtime_ms'] += packet.airtime_ms
    
    def record_device_tx(self, device_id: int, protocol: str, packet: 'Packet', energy_mj: float):
        """Record device transmission with energy."""
        self.device_energy[device_id][protocol] += energy_mj
        self.device_messages[device_id][f'{protocol}_tx'] += 1
        
        self.metrics[protocol]['total_energy_mj'] += energy_mj
        self.metrics[protocol]['tx_count'] += 1
    
    def record_device_rx(self, device_id: int, protocol: str, packet: 'Packet', energy_mj: float):
        """Record device reception with energy."""
        self.device_energy[device_id][protocol] += energy_mj
        self.device_messages[device_id][f'{protocol}_rx'] += 1
        
        self.metrics[protocol]['rx_energy_mj'] += energy_mj
        self.metrics[protocol]['rx_count'] += 1
    
    def record_gateway_rx(self, device_id: int, protocol: str, packet: 'Packet'):
        """Record gateway receiving uplink."""
        self.metrics[protocol]['gateway_rx_count'] += 1
        self.metrics[protocol]['gateway_rx_bytes'] += packet.size_bytes
    
    def record_gateway_tx(self, device_id: int, protocol: str, packet: 'Packet'):
        """Record gateway sending downlink."""
        self.metrics[protocol]['gateway_tx_count'] += 1
        self.metrics[protocol]['gateway_tx_bytes'] += packet.size_bytes
        
        # Track ACK efficiency for novel protocol
        if protocol == 'novel_lpwan' and packet.ack_bitmap:
            self.acks_sent[protocol] += 1
            # Count bits set in bitmap
            bitmap = packet.ack_bitmap
            acked_count = bin(bitmap).count('1')
            self.messages_acked[protocol] += acked_count
    
    def record_ack_received(self, device_id: int, seq_num: int):
        """Record ACK received by device."""
        self.metrics['novel_lpwan']['acks_received'] += 1
    
    def record_command_applied(self, device_id: int, protocol: str, 
                               cmd_type: int, latency_ms: float):
        """Record successful command application."""
        self.metrics[protocol]['commands_applied'] += 1
        self.metrics[protocol]['cmd_latency_sum_ms'] += latency_ms
        self.metrics[protocol]['cmd_latency_count'] += 1
    
    def record_command_expired(self, device_id: int, cmd_id: int, latency_ms: float):
        """Record expired command."""
        self.metrics['all']['commands_expired'] += 1
    
    def periodic_collection(self, env: simpy.Environment):
        """Process to collect periodic snapshots."""
        while True:
            yield env.timeout(self.collect_interval_ms)
            
            if env.now < self.warmup_ms:
                continue
                
            snapshot = {
                'timestamp_ms': env.now,
                'metrics': {}
            }
            
            for proto, proto_metrics in self.metrics.items():
                snapshot['metrics'][proto] = dict(proto_metrics)
            
            self.snapshots.append(snapshot)
    
    def finalize(self):
        """Finalize metrics collection."""
        logger.info("Finalizing metrics collection...")
        
        # Calculate derived metrics
        for proto in self.metrics:
            m = self.metrics[proto]
            
            # Delivery rate
            total_tx = m.get('uplink_success', 0) + m.get('uplink_failed', 0)
            if total_tx > 0:
                m['delivery_rate'] = m.get('uplink_success', 0) / total_tx
            
            # Average latency
            if m.get('cmd_latency_count', 0) > 0:
                m['avg_cmd_latency_ms'] = m['cmd_latency_sum_ms'] / m['cmd_latency_count']
            
            # Energy per message
            if m.get('tx_count', 0) > 0:
                m['energy_per_msg_mj'] = m.get('total_energy_mj', 0) / m['tx_count']
            
            # ACK efficiency (novel protocol)
            if proto == 'novel_lpwan' and self.acks_sent.get(proto, 0) > 0:
                m['ack_efficiency'] = self.messages_acked.get(proto, 0) / self.acks_sent.get(proto, 0)
    
    def get_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get summary statistics per protocol."""
        summary = {}
        
        for proto, m in self.metrics.items():
            if proto == 'all':
                continue
                
            summary[proto] = {
                'delivery_rate': m.get('delivery_rate', 0),
                'avg_cmd_latency_ms': m.get('avg_cmd_latency_ms', 0),
                'energy_per_msg_mj': m.get('energy_per_msg_mj', 0),
                'uplink_bytes': m.get('uplink_bytes', 0),
                'downlink_bytes': m.get('downlink_bytes', 0),
                'total_airtime_ms': m.get('uplink_airtime_ms', 0) + m.get('downlink_airtime_ms', 0),
                'commands_applied': m.get('commands_applied', 0),
                'ack_efficiency': m.get('ack_efficiency', 1.0),
            }
        
        return summary
    
    def get_dataframe(self) -> pd.DataFrame:
        """Get transmission records as DataFrame."""
        records = []
        
        for tx in self.transmissions:
            if tx.timestamp_ms >= self.warmup_ms:
                records.append({
                    'timestamp_ms': tx.timestamp_ms,
                    'device_id': tx.device_id,
                    'protocol': tx.protocol,
                    'direction': tx.direction,
                    'packet_size': tx.packet_size,
                    'airtime_ms': tx.airtime_ms,
                    'success': tx.success,
                    'qos_class': tx.qos_class,
                    'energy_mj': tx.energy_mj
                })
        
        return pd.DataFrame(records)
    
    def get_protocol_comparison(self) -> pd.DataFrame:
        """Get protocol comparison table."""
        summary = self.get_summary()
        
        rows = []
        for proto, metrics in summary.items():
            row = {'protocol': proto}
            row.update(metrics)
            rows.append(row)
        
        return pd.DataFrame(rows)
