"""
Gateway Module
==============
LPWAN gateway with protocol translation and command scheduling.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import heapq
import numpy as np
import simpy

logger = logging.getLogger(__name__)


@dataclass
class PendingCommand:
    """Command waiting to be delivered."""
    cmd_id: int
    device_id: int
    protocol: str
    cmd_type: int
    payload: bytes
    epoch_id: int
    priority: int  # 0=critical, 1=normal, 2=best_effort
    deadline_ms: float
    created_ms: float
    probability_target: float
    retries: int = 0
    max_retries: int = 3
    
    def __lt__(self, other):
        """For priority queue: higher priority (lower number) first, then earlier deadline."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.deadline_ms < other.deadline_ms


class CommandScheduler:
    """Priority-deadline scheduler for downlink commands."""
    
    def __init__(self, config: dict):
        self.queue_size = config.get('queue_size', 1000)
        self.scheduler_type = config.get('scheduler', 'priority_deadline')
        
        # Per-device queues
        self.queues: Dict[int, List[PendingCommand]] = defaultdict(list)
        self.cmd_counter = 0
        
    def enqueue(self, cmd: PendingCommand):
        """Add command to queue."""
        heapq.heappush(self.queues[cmd.device_id], cmd)
        
        # Trim if over capacity
        if len(self.queues[cmd.device_id]) > self.queue_size:
            # Remove lowest priority, furthest deadline
            self.queues[cmd.device_id] = heapq.nsmallest(
                self.queue_size, 
                self.queues[cmd.device_id]
            )
            heapq.heapify(self.queues[cmd.device_id])
    
    def get_commands_for_device(self, device_id: int, budget: int, 
                                 current_time_ms: float, max_payload: int = 50,
                                 protocol: str = None) -> List[PendingCommand]:
        """Get commands to send in next downlink, respecting budget and payload size.
        
        Args:
            device_id: Target device ID
            budget: Maximum number of commands to retrieve
            current_time_ms: Current simulation time
            max_payload: Maximum payload size in bytes
            protocol: Filter by protocol (optional, returns all if None)
        """
        queue = self.queues.get(device_id, [])
        if not queue:
            return []
        
        selected = []
        remaining_payload = max_payload
        
        # Sort by priority and deadline
        candidates = sorted(queue, key=lambda c: (c.priority, c.deadline_ms))
        
        for cmd in candidates:
            # Check protocol filter
            if protocol is not None and cmd.protocol != protocol:
                continue
                
            # Check if expired
            if cmd.deadline_ms < current_time_ms:
                continue
                
            # Check payload budget
            cmd_size = len(cmd.payload) + 4  # 4 bytes header overhead
            if cmd_size <= remaining_payload and len(selected) < budget:
                selected.append(cmd)
                remaining_payload -= cmd_size
                
        # Remove selected from queue
        for cmd in selected:
            if cmd in queue:
                queue.remove(cmd)
        heapq.heapify(queue)
        
        return selected
    
    def requeue_failed(self, cmd: PendingCommand, current_time_ms: float):
        """Requeue command after failed delivery attempt."""
        if cmd.retries < cmd.max_retries and cmd.deadline_ms > current_time_ms:
            cmd.retries += 1
            self.enqueue(cmd)
            return True
        return False


class AckTracker:
    """Track pending ACKs for windowed bitmap acknowledgment."""
    
    def __init__(self, window_size: int = 16):
        self.window_size = window_size
        
        # Per-device tracking: {device_id: {seq_num: timestamp}}
        self.pending_acks: Dict[int, Dict[int, float]] = defaultdict(dict)
        self.ack_base: Dict[int, int] = defaultdict(int)
        
    def add_pending(self, device_id: int, seq_num: int, timestamp_ms: float):
        """Add message awaiting acknowledgment."""
        self.pending_acks[device_id][seq_num] = timestamp_ms
        
    def generate_ack_bitmap(self, device_id: int) -> Tuple[int, int]:
        """Generate ACK bitmap for device."""
        pending = self.pending_acks.get(device_id, {})
        if not pending:
            return 0, 0
        
        # Find base (oldest unacked)
        min_seq = min(pending.keys())
        
        bitmap = 0
        for seq, _ in pending.items():
            offset = (seq - min_seq) % 65536
            if offset < self.window_size:
                bitmap |= (1 << offset)
                
        return min_seq, bitmap
    
    def mark_acked(self, device_id: int, bitmap: int, base: int):
        """Mark messages as acknowledged based on received bitmap."""
        pending = self.pending_acks.get(device_id, {})
        
        for i in range(self.window_size):
            if bitmap & (1 << i):
                seq = (base + i) % 65536
                if seq in pending:
                    del pending[seq]


class Gateway:
    """LPWAN Gateway with multi-protocol support."""
    
    def __init__(self, env: simpy.Environment, config: dict,
                 network: 'NetworkSimulator', protocols: Dict[str, 'Protocol'],
                 metrics: 'MetricsCollector'):
        self.env = env
        self.config = config
        self.network = network
        self.protocols = protocols
        self.metrics = metrics
        
        # Command scheduler
        self.scheduler = CommandScheduler(config)
        
        # ACK tracker for novel protocol
        novel_cfg = config.get('novel_lpwan', {})
        ack_window = novel_cfg.get('ack_window_size', 16)
        self.ack_tracker = AckTracker(window_size=ack_window)
        
        # Device state (stored at gateway for novel protocol)
        self.device_sessions: Dict[int, dict] = {}
        
        # MQTT bridge config
        self.mqtt_bridge_config = config.get('mqtt_bridge', {})
        
        # Pending downlinks per device
        self.pending_downlinks: Dict[int, List['Packet']] = defaultdict(list)
        
        # Statistics
        self.uplink_count = 0
        self.downlink_count = 0
        self.commands_delivered = 0
        self.commands_expired = 0
        
        logger.info("Gateway initialized")
    
    def run(self):
        """Main gateway process."""
        while True:
            # Process expired commands periodically
            yield self.env.timeout(60000)  # Every minute
            self._cleanup_expired_commands()
    
    def receive_uplink(self, packet: 'Packet'):
        """Handle received uplink packet."""
        self.uplink_count += 1
        device_id = packet.source_id
        proto_name = packet.protocol
        proto = self.protocols.get(proto_name)
        
        logger.debug(f"Gateway received uplink from device {device_id}, proto={proto_name}")
        
        # Process based on protocol
        if proto_name == 'novel_lpwan':
            self._handle_novel_uplink(packet)
        else:
            self._handle_standard_uplink(packet)
        
        # Record metrics
        self.metrics.record_gateway_rx(
            device_id=device_id,
            protocol=proto_name,
            packet=packet
        )
        
        # Opportunity to send downlink (RX window)
        self._schedule_downlink_opportunity(device_id, proto_name)
    
    def _handle_novel_uplink(self, packet: 'Packet'):
        """Handle novel protocol uplink with command pull."""
        device_id = packet.source_id
        
        # Update device session at gateway
        if device_id not in self.device_sessions:
            self.device_sessions[device_id] = {
                'token': packet.payload[:12] if len(packet.payload) >= 12 else b'',
                'last_seq_uplink': 0,
                'subscriptions': [],
                'inflight': {},
            }
        
        session = self.device_sessions[device_id]
        session['last_seq_uplink'] = packet.seq_num
        session['last_seen_ms'] = self.env.now
        
        # Track for ACK
        self.ack_tracker.add_pending(device_id, packet.seq_num, self.env.now)
        
        # Extract telemetry and forward to MQTT broker (simulated)
        self._forward_to_mqtt(device_id, packet)
    
    def _handle_standard_uplink(self, packet: 'Packet'):
        """Handle MQTT-SN or CoAP uplink."""
        device_id = packet.source_id
        proto_name = packet.protocol
        
        # Standard protocol processing
        self._forward_to_mqtt(device_id, packet)
    
    def _forward_to_mqtt(self, device_id: int, packet: 'Packet'):
        """Forward message to MQTT broker (simulated)."""
        if not self.mqtt_bridge_config.get('enabled', False):
            return
            
        # Map QoS
        qos_map = self.mqtt_bridge_config.get('qos_mapping', {})
        mqtt_qos = qos_map.get(packet.qos_class, 0)
        
        # Topic mapping
        topic = f"devices/{device_id}/telemetry"
        
        # In real implementation, publish to MQTT broker
        logger.debug(f"MQTT publish: {topic}, QoS={mqtt_qos}, size={packet.size_bytes}")
    
    def _schedule_downlink_opportunity(self, device_id: int, proto_name: str):
        """Schedule downlink during RX window."""
        # Get pending commands from scheduler (all protocols use scheduler now)
        budget = 3 if proto_name == 'novel_lpwan' else 1  # Novel aggregates, baseline sends one at a time
        commands = self.scheduler.get_commands_for_device(
            device_id, budget, self.env.now, protocol=proto_name
        )
        
        if proto_name == 'novel_lpwan':
            if commands:
                # Create aggregated downlink with bitmap ACK
                ack_base, ack_bitmap = self.ack_tracker.generate_ack_bitmap(device_id)
                
                packet = self._create_novel_downlink(
                    device_id, commands, ack_base, ack_bitmap
                )
                
                # Send via network
                self.env.process(self._send_downlink(packet, device_id))
                
        elif proto_name == 'mqtt_sn':
            # MQTT-SN: Create PUBLISH packet for each command
            for cmd in commands:
                packet = self._create_mqtt_sn_downlink(device_id, cmd)
                self.env.process(self._send_downlink(packet, device_id))
                
        elif proto_name == 'coap':
            # CoAP: Create response/notification for each command
            for cmd in commands:
                packet = self._create_coap_downlink(device_id, cmd)
                self.env.process(self._send_downlink(packet, device_id))
    
    def _create_novel_downlink(self, device_id: int, commands: List[PendingCommand],
                               ack_base: int, ack_bitmap: int) -> 'Packet':
        """Create novel protocol downlink with aggregated commands and ACK."""
        from .network import Packet
        
        # Build payload
        # Header: [msg_type(1), ack_base(2), ack_bitmap(2)]
        payload = bytearray()
        payload.append(0x02)  # msg_type: cmd_response
        payload.extend(ack_base.to_bytes(2, 'big'))
        payload.extend(ack_bitmap.to_bytes(2, 'big'))
        
        # Append commands
        for cmd in commands:
            # [cmd_type(1), epoch_id(1), len(1), payload...]
            payload.append(cmd.cmd_type)
            payload.append(cmd.epoch_id)
            payload.append(len(cmd.payload))
            payload.extend(cmd.payload)
        
        packet = Packet(
            packet_id=0,  # Will be set by network
            source_id=-1,  # Gateway
            dest_id=device_id,
            protocol='novel_lpwan',
            payload=bytes(payload),
            size_bytes=len(payload),
            timestamp_ms=self.env.now,
            direction='downlink',
            ack_bitmap=ack_bitmap,
            seq_num=ack_base
        )
        
        return packet
    
    def _create_mqtt_sn_downlink(self, device_id: int, cmd: PendingCommand) -> 'Packet':
        """Create MQTT-SN PUBLISH downlink packet for a command."""
        from .network import Packet
        import struct
        
        # MQTT-SN PUBLISH format: [len, msg_type, flags, topic_id, msg_id, data]
        MQTTSN_PUBLISH = 0x0C
        
        payload = bytearray()
        
        # Flags: QoS 1, Topic ID type = predefined
        flags = 0x20  # QoS 1
        
        # Topic ID = cmd_type (for command delivery)
        topic_id = cmd.cmd_type
        
        # Message ID = epoch_id (for duplicate detection)
        msg_id = cmd.epoch_id
        
        # Build packet: [length, msg_type, flags, topic_id(2), msg_id(2), data...]
        inner_payload = bytearray()
        inner_payload.append(MQTTSN_PUBLISH)
        inner_payload.append(flags)
        inner_payload.extend(struct.pack('>H', topic_id))
        inner_payload.extend(struct.pack('>H', msg_id))
        inner_payload.extend(cmd.payload)
        
        # Prepend length
        payload.append(len(inner_payload) + 1)  # +1 for length byte
        payload.extend(inner_payload)
        
        packet = Packet(
            packet_id=0,
            source_id=-1,  # Gateway
            dest_id=device_id,
            protocol='mqtt_sn',
            payload=bytes(payload),
            size_bytes=len(payload),
            timestamp_ms=self.env.now,
            direction='downlink'
        )
        
        return packet
    
    def _create_coap_downlink(self, device_id: int, cmd: PendingCommand) -> 'Packet':
        """Create CoAP response/notification downlink packet for a command."""
        from .network import Packet
        import struct
        
        # CoAP format: [ver|type|tkl, code, msg_id, token..., options..., 0xFF, payload]
        COAP_VERSION = 1
        COAP_ACK = 2  # Acknowledgement type
        COAP_CONTENT = 0x45  # 2.05 Content response code
        
        payload = bytearray()
        
        # Token (4 bytes for message correlation)
        token = struct.pack('>I', cmd.epoch_id)[:4]
        tkl = len(token)
        
        # First byte: version(2) | type(2) | tkl(4)
        byte0 = (COAP_VERSION << 6) | (COAP_ACK << 4) | tkl
        
        # Message ID
        msg_id = cmd.cmd_id & 0xFFFF
        
        payload.append(byte0)
        payload.append(COAP_CONTENT)
        payload.extend(struct.pack('>H', msg_id))
        payload.extend(token)
        
        # Payload marker and data
        payload.append(0xFF)  # Payload marker
        payload.extend(cmd.payload)
        
        packet = Packet(
            packet_id=0,
            source_id=-1,  # Gateway
            dest_id=device_id,
            protocol='coap',
            payload=bytes(payload),
            size_bytes=len(payload),
            timestamp_ms=self.env.now,
            direction='downlink'
        )
        
        return packet
    
    def _send_downlink(self, packet: 'Packet', device_id: int):
        """Send downlink packet."""
        self.downlink_count += 1
        
        yield self.network.send_downlink(packet, device_id)
        
        self.metrics.record_gateway_tx(
            device_id=device_id,
            protocol=packet.protocol,
            packet=packet
        )
    
    def queue_command(self, device_id: int, cmd_type: int, payload: bytes,
                      priority: str = 'normal', deadline_s: float = 3600,
                      probability: float = 0.9, protocol: str = 'novel_lpwan'):
        """Queue a command for delivery to device."""
        # Get current epoch for this cmd_type at this device
        session = self.device_sessions.get(device_id, {})
        epochs = session.get('epochs', {})
        current_epoch = epochs.get(cmd_type, 0)
        new_epoch = (current_epoch + 1) % 256
        
        # Store new epoch
        if device_id not in self.device_sessions:
            self.device_sessions[device_id] = {'epochs': {}}
        self.device_sessions[device_id].setdefault('epochs', {})[cmd_type] = new_epoch
        
        # Map priority
        priority_map = {'critical': 0, 'normal': 1, 'best_effort': 2}
        priority_num = priority_map.get(priority, 1)
        
        # Get retry config from QoS class
        proto_cfg = self.config.get('protocols', {}).get('novel_lpwan', {})
        qos_classes = proto_cfg.get('qos_classes', [])
        max_retries = 2
        for qc in qos_classes:
            if qc.get('name') == priority:
                max_retries = qc.get('retries', 2)
                break
        
        cmd = PendingCommand(
            cmd_id=self.scheduler.cmd_counter,
            device_id=device_id,
            protocol=protocol,
            cmd_type=cmd_type,
            payload=payload,
            epoch_id=new_epoch,
            priority=priority_num,
            deadline_ms=self.env.now + deadline_s * 1000,
            created_ms=self.env.now,
            probability_target=probability,
            max_retries=max_retries
        )
        
        self.scheduler.cmd_counter += 1
        self.scheduler.enqueue(cmd)
        
        logger.debug(f"Queued command for device {device_id}: type={cmd_type}, epoch={new_epoch}")
    
    def _cleanup_expired_commands(self):
        """Remove expired commands from queues."""
        for device_id, queue in self.scheduler.queues.items():
            expired = [c for c in queue if c.deadline_ms < self.env.now]
            for cmd in expired:
                queue.remove(cmd)
                self.commands_expired += 1
                self.metrics.record_command_expired(
                    device_id=device_id,
                    cmd_id=cmd.cmd_id,
                    latency_ms=self.env.now - cmd.created_ms
                )
            heapq.heapify(queue)
