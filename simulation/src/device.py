"""
End Device Module
=================
Simulates IoT end devices with protocol stack and power model.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np
import simpy

logger = logging.getLogger(__name__)


@dataclass
class DeviceState:
    """Minimal device state for novel protocol (target: ~32 bytes)."""
    # Micro-session token (8-12 bytes)
    session_token: bytes = field(default_factory=lambda: bytes(12))
    
    # Sequence numbers (4 bytes total)
    next_seq_uplink: int = 0
    next_seq_downlink_expected: int = 0
    
    # Reliability flags (1 byte)
    reliability_flags: int = 0
    
    # Epoch IDs per command type (8 bytes max)
    epoch_ids: Dict[int, int] = field(default_factory=dict)
    
    def get_total_bytes(self) -> int:
        """Calculate total state size in bytes."""
        return (
            len(self.session_token) +  # token
            2 +  # seq_uplink
            2 +  # seq_downlink
            1 +  # flags
            len(self.epoch_ids)  # epoch IDs
        )


class EndDevice:
    """IoT End Device with multi-protocol support."""
    
    def __init__(self, device_id: int, env: simpy.Environment, config: dict,
                 network: 'NetworkSimulator', gateway: 'Gateway',
                 protocols: Dict[str, 'Protocol'], metrics: 'MetricsCollector'):
        self.device_id = device_id
        self.env = env
        self.config = config
        self.network = network
        self.gateway = gateway
        self.protocols = protocols
        self.metrics = metrics
        
        # Power model (mW)
        power_cfg = config.get('power', {})
        self.power_sleep = power_cfg.get('sleep', 0.001)
        self.power_idle = power_cfg.get('idle', 1.0)
        self.power_rx = power_cfg.get('rx', 12.0)
        self.power_tx_map = power_cfg.get('tx_dbm_to_mw', {14: 80})
        
        # State per protocol
        self.protocol_states = {}
        for proto_name, proto in protocols.items():
            if proto_name == 'novel_lpwan':
                self.protocol_states[proto_name] = DeviceState()
            else:
                self.protocol_states[proto_name] = proto.create_device_state()
        
        # Device status
        self.is_sleeping = True
        self.pending_uplinks = []
        self.pending_commands = []
        
        # Energy tracking
        self.energy_consumed_mj = 0.0
        self.last_state_change_ms = 0.0
        self.current_power_mw = self.power_sleep
        
        logger.debug(f"Device {device_id} initialized")
    
    def run(self):
        """Main device process."""
        while True:
            # Sleep between activities
            sleep_duration = self._calculate_sleep_duration()
            yield self.env.timeout(sleep_duration)
            
            # Wake up
            self._change_power_state('idle')
            
            # Process pending uplinks
            if self.pending_uplinks:
                yield from self._send_uplinks()
            
            # Process received commands
            if self.pending_commands:
                yield from self._process_commands()
                
            # Go back to sleep
            self._change_power_state('sleep')
    
    def _calculate_sleep_duration(self) -> float:
        """Calculate next wake-up time based on traffic pattern."""
        # Will be set by traffic generator
        base_interval = 600000  # 10 minutes in ms
        jitter = np.random.uniform(-0.1, 0.1) * base_interval
        return max(1000, base_interval + jitter)
    
    def _change_power_state(self, state: str):
        """Track power state changes and energy consumption."""
        now = self.env.now
        duration_ms = now - self.last_state_change_ms
        
        # Accumulate energy from previous state
        self.energy_consumed_mj += self.current_power_mw * duration_ms / 1000
        
        # Update state
        if state == 'sleep':
            self.current_power_mw = self.power_sleep
            self.is_sleeping = True
        elif state == 'idle':
            self.current_power_mw = self.power_idle
            self.is_sleeping = False
        elif state == 'rx':
            self.current_power_mw = self.power_rx
        elif state.startswith('tx'):
            dbm = int(state.split('_')[1]) if '_' in state else 14
            self.current_power_mw = self.power_tx_map.get(dbm, 80)
            
        self.last_state_change_ms = now
    
    def _send_uplinks(self):
        """Send pending uplink messages."""
        for msg in self.pending_uplinks[:]:  # Copy list
            for proto_name, proto in self.protocols.items():
                # Change to TX state
                self._change_power_state('tx_14')
                
                # Create protocol-specific packet
                state = self.protocol_states[proto_name]
                packet = proto.create_uplink_packet(
                    device_id=self.device_id,
                    state=state,
                    payload=msg['payload'],
                    qos_class=msg.get('qos_class', 'normal')
                )
                
                # Send via network
                yield self.network.send_uplink(packet)
                
                # Record metrics
                self.metrics.record_device_tx(
                    device_id=self.device_id,
                    protocol=proto_name,
                    packet=packet,
                    energy_mj=packet.airtime_ms * self.current_power_mw / 1000
                )
                
                # Update state
                if proto_name == 'novel_lpwan':
                    state.next_seq_uplink = (state.next_seq_uplink + 1) % 65536
                    
            self.pending_uplinks.remove(msg)
            
        self._change_power_state('idle')
    
    def _process_commands(self):
        """Process received commands."""
        for cmd in self.pending_commands[:]:
            proto_name = cmd['protocol']
            proto = self.protocols.get(proto_name)
            
            if proto:
                if proto_name == 'novel_lpwan':
                    # Novel protocol: Epoch-based idempotency check
                    state = self.protocol_states[proto_name]
                    cmd_type = cmd.get('cmd_type', 0)
                    epoch_id = cmd.get('epoch_id', 0)
                    
                    current_epoch = state.epoch_ids.get(cmd_type, 0)
                    
                    if epoch_id > current_epoch:
                        # New command - apply it
                        state.epoch_ids[cmd_type] = epoch_id
                        self._apply_command(cmd)
                        logger.debug(f"Device {self.device_id}: Applied cmd type {cmd_type}, epoch {epoch_id}")
                    else:
                        # Duplicate - ignore (idempotent)
                        logger.debug(f"Device {self.device_id}: Ignored duplicate cmd type {cmd_type}")
                
                elif proto_name in ('mqtt_sn', 'coap'):
                    # Baseline protocols: Apply command directly (no epoch-based idempotency)
                    # MQTT-SN uses message ID for duplicate detection (simulated)
                    # CoAP uses token-based request/response matching (simulated)
                    self._apply_command(cmd)
                    logger.debug(f"Device {self.device_id}: [{proto_name}] Applied command")
                    
            self.pending_commands.remove(cmd)
            
        yield self.env.timeout(10)  # Command processing time
    
    def _apply_command(self, cmd: dict):
        """Apply a command to the device (stub for actual logic)."""
        # In real implementation, this would update device configuration
        self.metrics.record_command_applied(
            device_id=self.device_id,
            protocol=cmd['protocol'],
            cmd_type=cmd.get('cmd_type', 0),
            latency_ms=self.env.now - cmd.get('created_ms', 0)
        )
    
    def queue_uplink(self, payload: bytes, qos_class: str = 'normal'):
        """Queue an uplink message for transmission."""
        self.pending_uplinks.append({
            'payload': payload,
            'qos_class': qos_class,
            'created_ms': self.env.now
        })
    
    def receive_downlink(self, packet: 'Packet'):
        """Handle received downlink packet."""
        self._change_power_state('rx')
        
        proto_name = packet.protocol
        proto = self.protocols.get(proto_name)
        
        if proto:
            # Parse commands from packet
            commands = proto.parse_downlink_packet(packet)
            
            for cmd in commands:
                cmd['protocol'] = proto_name
                cmd['created_ms'] = packet.timestamp_ms
                self.pending_commands.append(cmd)
                
            # Handle ACK bitmap (novel protocol)
            if proto_name == 'novel_lpwan' and packet.ack_bitmap:
                self._process_ack_bitmap(packet.ack_bitmap, packet.seq_num)
                
        # Record RX energy
        self.metrics.record_device_rx(
            device_id=self.device_id,
            protocol=proto_name,
            packet=packet,
            energy_mj=packet.airtime_ms * self.power_rx / 1000
        )
        
        self._change_power_state('idle')
    
    def _process_ack_bitmap(self, bitmap: int, ack_base: int):
        """Process windowed bitmap ACK."""
        state = self.protocol_states.get('novel_lpwan')
        if not state:
            return
            
        # Each bit in bitmap represents ACK for (ack_base + bit_position)
        for i in range(16):  # 16-bit bitmap
            if bitmap & (1 << i):
                seq_acked = (ack_base + i) % 65536
                # Mark message as acknowledged
                self.metrics.record_ack_received(
                    device_id=self.device_id,
                    seq_num=seq_acked
                )
    
    def get_state_size(self, protocol: str) -> int:
        """Get protocol state size in bytes."""
        state = self.protocol_states.get(protocol)
        if protocol == 'novel_lpwan' and isinstance(state, DeviceState):
            return state.get_total_bytes()
        elif hasattr(state, 'get_size'):
            return state.get_size()
        return 0
