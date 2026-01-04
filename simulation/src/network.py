"""
Network Simulator Module
========================
Simulates LPWAN network characteristics (LoRaWAN, NB-IoT, Sigfox).
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import numpy as np
import simpy

logger = logging.getLogger(__name__)


@dataclass
class Packet:
    """Represents a network packet."""
    packet_id: int
    source_id: int
    dest_id: int
    protocol: str
    payload: bytes
    size_bytes: int
    timestamp_ms: float
    direction: str  # 'uplink' or 'downlink'
    qos_class: str = 'normal'
    priority: int = 1
    seq_num: int = 0
    ack_bitmap: int = 0
    epoch_id: int = 0
    
    # Transmission metadata
    tx_power_dbm: int = 14
    spreading_factor: int = 7
    airtime_ms: float = 0.0
    
    # Delivery status
    delivered: bool = False
    delivery_time_ms: float = 0.0
    retries: int = 0


class LoRaWANChannel:
    """LoRaWAN channel model with duty cycle and SF selection."""
    
    def __init__(self, config: dict):
        self.region = config.get('region', 'EU868')
        self.duty_cycle = config.get('duty_cycle', 0.01)
        self.spreading_factors = config.get('spreading_factors', [7, 8, 9, 10, 11, 12])
        self.rx1_delay_ms = config.get('rx1_delay_ms', 1000)
        self.rx2_delay_ms = config.get('rx2_delay_ms', 2000)
        
        # Time-on-air lookup table (ms per byte for each SF)
        self.toa_per_byte = {
            7: 0.5, 8: 0.9, 9: 1.6, 10: 2.9, 11: 5.2, 12: 9.5
        }
        
        # Packet Error Rate by SF (simplified model)
        self.per_by_sf = {
            7: 0.05, 8: 0.04, 9: 0.03, 10: 0.02, 11: 0.015, 12: 0.01
        }
        
    def calculate_airtime(self, payload_bytes: int, sf: int = 7) -> float:
        """Calculate time-on-air in milliseconds."""
        preamble_ms = 12.25 * (2 ** sf) / 125000 * 1000  # 125kHz BW
        header_ms = 8 * self.toa_per_byte[sf]
        payload_ms = payload_bytes * self.toa_per_byte[sf]
        return preamble_ms + header_ms + payload_ms
    
    def transmit(self, packet: Packet, sf: int = 7) -> bool:
        """Simulate packet transmission with PER."""
        packet.spreading_factor = sf
        packet.airtime_ms = self.calculate_airtime(packet.size_bytes, sf)
        
        # Apply packet error rate
        if np.random.random() < self.per_by_sf[sf]:
            return False
        return True


class NBIoTChannel:
    """NB-IoT channel model."""
    
    def __init__(self, config: dict):
        self.carrier_freq = config.get('carrier_freq_mhz', 900)
        self.ue_category = config.get('ue_category', 'cat-nb1')
        self.psm_enabled = config.get('psm_enabled', True)
        self.edrx_cycle = config.get('edrx_cycle_s', 20.48)
        
        # Simplified throughput model (kbps)
        self.uplink_rate_kbps = 62.5
        self.downlink_rate_kbps = 27.2
        
    def calculate_airtime(self, payload_bytes: int, direction: str) -> float:
        """Calculate transmission time in milliseconds."""
        rate = self.uplink_rate_kbps if direction == 'uplink' else self.downlink_rate_kbps
        return (payload_bytes * 8) / rate
    
    def transmit(self, packet: Packet) -> bool:
        """Simulate NB-IoT transmission."""
        rate = self.uplink_rate_kbps if packet.direction == 'uplink' else self.downlink_rate_kbps
        packet.airtime_ms = (packet.size_bytes * 8) / rate
        
        # NB-IoT has very high reliability due to retransmissions
        per = 0.001  # Very low PER after HARQ
        return np.random.random() > per


class NetworkSimulator:
    """Main network simulation coordinator."""
    
    def __init__(self, env: simpy.Environment, config: dict, metrics: 'MetricsCollector'):
        self.env = env
        self.config = config
        self.metrics = metrics
        
        self.network_type = config.get('type', 'lorawan')
        self.num_devices = config.get('num_devices', 100)
        self.num_gateways = config.get('num_gateways', 1)
        
        # Initialize channel model
        if self.network_type == 'lorawan':
            self.channel = LoRaWANChannel(config.get('lorawan', {}))
        elif self.network_type == 'nbiot':
            self.channel = NBIoTChannel(config.get('nbiot', {}))
        else:
            self.channel = LoRaWANChannel({})  # Default
            
        self.devices = []
        self.gateway = None
        self.packet_counter = 0
        
        # Duty cycle tracking per device
        self.duty_cycle_tracker = {}
        
        logger.info(f"Network initialized: {self.network_type}, {self.num_devices} devices")
        
    def set_devices(self, devices: List['EndDevice']):
        """Register end devices."""
        self.devices = devices
        for d in devices:
            self.duty_cycle_tracker[d.device_id] = {
                'last_tx_ms': 0,
                'airtime_budget_ms': 0
            }
    
    def set_gateway(self, gateway: 'Gateway'):
        """Register gateway."""
        self.gateway = gateway
        
    def create_packet(self, source_id: int, dest_id: int, protocol: str,
                      payload: bytes, direction: str, **kwargs) -> Packet:
        """Create a new packet."""
        self.packet_counter += 1
        
        return Packet(
            packet_id=self.packet_counter,
            source_id=source_id,
            dest_id=dest_id,
            protocol=protocol,
            payload=payload,
            size_bytes=len(payload),
            timestamp_ms=self.env.now,
            direction=direction,
            **kwargs
        )
    
    def can_transmit(self, device_id: int, airtime_ms: float) -> bool:
        """Check if device can transmit (duty cycle constraint)."""
        if self.network_type != 'lorawan':
            return True
            
        tracker = self.duty_cycle_tracker.get(device_id)
        if tracker is None:
            return True
            
        # Calculate duty cycle window (1 hour = 3600000 ms)
        window_ms = 3600000
        max_airtime_ms = window_ms * self.channel.duty_cycle
        
        # Simple check: budget remaining
        return tracker['airtime_budget_ms'] + airtime_ms <= max_airtime_ms
    
    def send_uplink(self, packet: Packet) -> simpy.Event:
        """Send uplink packet from device to gateway."""
        return self.env.process(self._transmit_uplink(packet))
    
    def _transmit_uplink(self, packet: Packet):
        """Uplink transmission process."""
        # Calculate airtime
        if self.network_type == 'lorawan':
            sf = self._select_sf(packet.source_id)
            success = self.channel.transmit(packet, sf)
        else:
            success = self.channel.transmit(packet)
        
        # Simulate transmission time
        yield self.env.timeout(packet.airtime_ms)
        
        # Update duty cycle tracker
        if packet.source_id in self.duty_cycle_tracker:
            self.duty_cycle_tracker[packet.source_id]['airtime_budget_ms'] += packet.airtime_ms
            self.duty_cycle_tracker[packet.source_id]['last_tx_ms'] = self.env.now
        
        # Record metrics
        self.metrics.record_transmission(packet, success)
        
        if success and self.gateway:
            # Deliver to gateway
            packet.delivered = True
            packet.delivery_time_ms = self.env.now
            self.gateway.receive_uplink(packet)
            
    def _select_sf(self, device_id: int) -> int:
        """Select spreading factor based on device/link quality."""
        # Simplified: random SF weighted towards lower
        weights = [0.3, 0.25, 0.2, 0.15, 0.07, 0.03]
        return np.random.choice(self.channel.spreading_factors, p=weights)
    
    def send_downlink(self, packet: Packet, device_id: int) -> simpy.Event:
        """Send downlink packet from gateway to device."""
        return self.env.process(self._transmit_downlink(packet, device_id))
    
    def _transmit_downlink(self, packet: Packet, device_id: int):
        """Downlink transmission process."""
        # Wait for RX window
        if self.network_type == 'lorawan':
            yield self.env.timeout(self.channel.rx1_delay_ms)
        
        # Transmit
        if self.network_type == 'lorawan':
            sf = self._select_sf(device_id)
            success = self.channel.transmit(packet, sf)
        else:
            success = self.channel.transmit(packet)
            
        yield self.env.timeout(packet.airtime_ms)
        
        self.metrics.record_transmission(packet, success)
        
        if success:
            packet.delivered = True
            packet.delivery_time_ms = self.env.now
            # Find device and deliver
            for device in self.devices:
                if device.device_id == device_id:
                    device.receive_downlink(packet)
                    break
