"""
Novel LPWAN Protocol Implementation
===================================
Implements the novel "MQTT-like but LPWAN-native" protocol with:
- Micro-Session Token (stateless device)
- Windowed Bitmap ACK
- QoS-D (Deadline + Probability)
- Command Pull Slot
- Compact Header (≤6 bytes)
- Epoch-Based Idempotent Commanding
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
import struct

logger = logging.getLogger(__name__)


# Message types (3 bits)
MSG_TYPE_TELEMETRY = 0x00
MSG_TYPE_CMD_PULL = 0x01
MSG_TYPE_CMD_RESP = 0x02
MSG_TYPE_ACK_BITMAP = 0x03
MSG_TYPE_CONTROL = 0x04

# Priority classes (2 bits)
PRIO_CRITICAL = 0
PRIO_NORMAL = 1
PRIO_BEST_EFFORT = 2

# Topic classes (3 bits) - predefined categories
TOPIC_TELEMETRY = 0
TOPIC_ALARM = 1
TOPIC_CONFIG = 2
TOPIC_FIRMWARE = 3
TOPIC_STATUS = 4
TOPIC_CMD = 5
TOPIC_ACK = 6
TOPIC_RESERVED = 7


@dataclass
class NovelHeader:
    """
    Compact 5-byte header for novel protocol.
    
    Layout:
    Byte 0: [msg_type(3) | prio_class(2) | topic_class(3)]
    Byte 1-2: seq_num (16 bits)
    Byte 3: flags (8 bits)
    Byte 4: token_short (8 bits - LSB of full token)
    """
    msg_type: int = MSG_TYPE_TELEMETRY
    prio_class: int = PRIO_NORMAL
    topic_class: int = TOPIC_TELEMETRY
    seq_num: int = 0
    flags: int = 0
    token_short: int = 0
    
    def encode(self) -> bytes:
        """Encode header to bytes."""
        byte0 = ((self.msg_type & 0x07) << 5) | \
                ((self.prio_class & 0x03) << 3) | \
                (self.topic_class & 0x07)
        
        return struct.pack('>BHBB', byte0, self.seq_num, self.flags, self.token_short)
    
    @classmethod
    def decode(cls, data: bytes) -> 'NovelHeader':
        """Decode header from bytes."""
        if len(data) < 5:
            raise ValueError("Header too short")
            
        byte0, seq_num, flags, token_short = struct.unpack('>BHBB', data[:5])
        
        return cls(
            msg_type=(byte0 >> 5) & 0x07,
            prio_class=(byte0 >> 3) & 0x03,
            topic_class=byte0 & 0x07,
            seq_num=seq_num,
            flags=flags,
            token_short=token_short
        )
    
    @staticmethod
    def size() -> int:
        return 5


@dataclass 
class QoSConfig:
    """QoS-D configuration: (probability, deadline)."""
    name: str
    probability: float
    deadline_s: float
    retries: int
    
    
class NovelLPWANProtocol:
    """
    Novel LPWAN Protocol - Main Implementation.
    
    Key features:
    1. Device state: only ~32 bytes (token + seq + flags + epochs)
    2. Gateway holds all session state
    3. Windowed bitmap ACK (1 downlink ACKs up to 16 uplinks)
    4. QoS-D: deadline + probability based reliability
    5. Epoch-based idempotent commands
    """
    
    HEADER_SIZE = 5
    TOKEN_SIZE = 12
    
    def __init__(self, config: dict):
        self.config = config
        
        self.token_size = config.get('token_size_bytes', 12)
        self.header_size = config.get('header_size_bytes', 5)
        self.ack_window_size = config.get('ack_window_size', 16)
        self.ack_base_bits = config.get('ack_base_bits', 16)
        self.epoch_bits = config.get('epoch_bits', 8)
        self.cmd_types = config.get('cmd_types', 8)
        
        # Parse QoS classes
        self.qos_classes = {}
        for qc in config.get('qos_classes', []):
            self.qos_classes[qc['name']] = QoSConfig(
                name=qc['name'],
                probability=qc['probability'],
                deadline_s=qc['deadline_s'],
                retries=qc['retries']
            )
            
        logger.info(f"NovelLPWAN protocol initialized: header={self.header_size}B, token={self.token_size}B")
    
    def create_device_state(self) -> dict:
        """Create minimal device state structure."""
        return {
            'token': bytes(self.token_size),
            'next_seq_uplink': 0,
            'next_seq_downlink_expected': 0,
            'reliability_flags': 0,
            'epoch_ids': {},  # cmd_type -> epoch_id
        }
    
    def get_device_state_size(self, state: dict) -> int:
        """Calculate device state size in bytes."""
        return (
            self.token_size +  # session token
            2 +  # seq_uplink
            2 +  # seq_downlink
            1 +  # flags
            len(state.get('epoch_ids', {}))  # epoch IDs (1 byte each)
        )
    
    def create_uplink_packet(self, device_id: int, state: Any, 
                             payload: bytes, qos_class: str = 'normal') -> 'Packet':
        """Create uplink packet with compact header."""
        from ..network import Packet
        
        # Get priority from QoS class
        qos = self.qos_classes.get(qos_class, self.qos_classes.get('normal'))
        if qos_class == 'critical':
            prio = PRIO_CRITICAL
        elif qos_class == 'best_effort':
            prio = PRIO_BEST_EFFORT
        else:
            prio = PRIO_NORMAL
        
        # Build header
        header = NovelHeader(
            msg_type=MSG_TYPE_TELEMETRY,
            prio_class=prio,
            topic_class=TOPIC_TELEMETRY,
            seq_num=state.next_seq_uplink if hasattr(state, 'next_seq_uplink') else state.get('next_seq_uplink', 0),
            flags=0,
            token_short=state.session_token[-1] if hasattr(state, 'session_token') else 0
        )
        
        # Combine header + payload
        full_payload = header.encode() + payload
        
        return Packet(
            packet_id=0,
            source_id=device_id,
            dest_id=-1,  # Gateway
            protocol='novel_lpwan',
            payload=full_payload,
            size_bytes=len(full_payload),
            timestamp_ms=0,  # Will be set by network
            direction='uplink',
            qos_class=qos_class,
            seq_num=header.seq_num,
            priority=prio
        )
    
    def parse_uplink_packet(self, packet: 'Packet') -> Tuple[NovelHeader, bytes]:
        """Parse uplink packet."""
        header = NovelHeader.decode(packet.payload)
        payload = packet.payload[NovelHeader.size():]
        return header, payload
    
    def create_downlink_packet(self, device_id: int, commands: List[dict],
                               ack_base: int, ack_bitmap: int) -> 'Packet':
        """Create downlink packet with ACK bitmap and commands."""
        from ..network import Packet
        
        # Header for ACK + commands
        header = NovelHeader(
            msg_type=MSG_TYPE_CMD_RESP,
            prio_class=PRIO_NORMAL,
            topic_class=TOPIC_CMD,
            seq_num=ack_base,
            flags=0,
            token_short=0
        )
        
        # Build payload
        payload = bytearray(header.encode())
        
        # ACK bitmap (2 bytes)
        payload.extend(struct.pack('>H', ack_bitmap))
        
        # Commands
        for cmd in commands:
            # [cmd_type(1), epoch_id(1), len(1), data...]
            payload.append(cmd.get('cmd_type', 0) & 0xFF)
            payload.append(cmd.get('epoch_id', 0) & 0xFF)
            cmd_payload = cmd.get('payload', b'')
            payload.append(len(cmd_payload) & 0xFF)
            payload.extend(cmd_payload)
        
        return Packet(
            packet_id=0,
            source_id=-1,
            dest_id=device_id,
            protocol='novel_lpwan',
            payload=bytes(payload),
            size_bytes=len(payload),
            timestamp_ms=0,
            direction='downlink',
            ack_bitmap=ack_bitmap,
            seq_num=ack_base
        )
    
    def parse_downlink_packet(self, packet: 'Packet') -> List[dict]:
        """Parse downlink packet and extract commands."""
        commands = []
        
        if len(packet.payload) < NovelHeader.size() + 2:
            return commands
            
        header = NovelHeader.decode(packet.payload)
        
        # Skip header + ACK bitmap
        offset = NovelHeader.size() + 2
        
        while offset < len(packet.payload):
            if offset + 3 > len(packet.payload):
                break
                
            cmd_type = packet.payload[offset]
            epoch_id = packet.payload[offset + 1]
            cmd_len = packet.payload[offset + 2]
            offset += 3
            
            if offset + cmd_len > len(packet.payload):
                break
                
            cmd_payload = packet.payload[offset:offset + cmd_len]
            offset += cmd_len
            
            commands.append({
                'cmd_type': cmd_type,
                'epoch_id': epoch_id,
                'payload': cmd_payload
            })
        
        return commands
    
    def get_overhead_bytes(self) -> int:
        """Get protocol overhead per message."""
        return self.header_size
    
    def get_ack_overhead_bytes(self) -> int:
        """Get ACK overhead (bitmap covers multiple messages)."""
        # 2 bytes bitmap + 2 bytes ack_base in header
        return 4
    
    def calculate_effective_ack_overhead(self, messages_acked: int) -> float:
        """Calculate effective ACK overhead per message."""
        if messages_acked == 0:
            return 0
        return self.get_ack_overhead_bytes() / messages_acked
