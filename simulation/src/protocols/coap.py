"""
CoAP Protocol Implementation (Baseline)
=======================================
Simplified implementation for comparison purposes.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
import struct

logger = logging.getLogger(__name__)


# CoAP Message Types
COAP_CON = 0  # Confirmable
COAP_NON = 1  # Non-confirmable
COAP_ACK = 2  # Acknowledgment
COAP_RST = 3  # Reset

# CoAP Methods
COAP_GET = 1
COAP_POST = 2
COAP_PUT = 3
COAP_DELETE = 4

# CoAP Response Codes
COAP_CREATED = 65  # 2.01
COAP_DELETED = 66  # 2.02
COAP_VALID = 67    # 2.03
COAP_CHANGED = 68  # 2.04
COAP_CONTENT = 69  # 2.05


@dataclass
class CoAPDeviceState:
    """CoAP device state."""
    
    # Message tracking
    message_id: int = 0
    token: bytes = b""
    
    # Inflight transactions (CON messages awaiting ACK)
    inflight: Dict[int, dict] = field(default_factory=dict)
    
    # Observe subscriptions
    observe_tokens: Dict[str, bytes] = field(default_factory=dict)  # uri -> token
    
    # Block transfer state
    block_state: Dict[str, dict] = field(default_factory=dict)
    
    def get_size(self) -> int:
        """Estimate state size in bytes."""
        base_size = 16  # message_id, token
        inflight_size = len(self.inflight) * 30
        observe_size = len(self.observe_tokens) * 20
        block_size = len(self.block_state) * 50
        return base_size + inflight_size + observe_size + block_size


class CoAPProtocol:
    """
    CoAP Protocol Implementation (Baseline).
    
    Standard CoAP features:
    - CON/NON messages
    - Retransmission for CON
    - Token-based request/response matching
    - Observe (notifications)
    """
    
    # Header size: Version(2) + Type(2) + TKL(4) + Code(8) + MessageID(16) = 4 bytes
    # Plus token (0-8 bytes) and options
    HEADER_SIZE = 4
    TOKEN_SIZE = 4  # Typical token size
    
    def __init__(self, config: dict):
        self.config = config
        
        self.confirmable_ratio = config.get('confirmable_ratio', 0.5)
        self.max_retransmit = config.get('max_retransmit', 4)
        self.ack_timeout_s = config.get('ack_timeout_s', 2)
        
        logger.info(f"CoAP protocol initialized: CON ratio={self.confirmable_ratio}")
    
    def create_device_state(self) -> CoAPDeviceState:
        """Create CoAP device state."""
        import os
        return CoAPDeviceState(token=os.urandom(4))
    
    def get_device_state_size(self, state: CoAPDeviceState) -> int:
        """Get device state size in bytes."""
        return state.get_size()
    
    def create_uplink_packet(self, device_id: int, state: CoAPDeviceState,
                             payload: bytes, qos_class: str = 'normal') -> 'Packet':
        """Create CoAP request packet."""
        from ..network import Packet
        
        # Determine if CON or NON based on qos_class
        if qos_class == 'critical':
            msg_type = COAP_CON
        elif qos_class == 'best_effort':
            msg_type = COAP_NON
        else:
            # Use configured ratio
            import random
            msg_type = COAP_CON if random.random() < self.confirmable_ratio else COAP_NON
        
        # Increment message ID
        state.message_id = (state.message_id + 1) % 65536
        
        # Build CoAP header
        # Byte 0: Version(2) | Type(2) | Token Length(4)
        # Byte 1: Code (method)
        # Bytes 2-3: Message ID
        # Bytes 4+: Token
        
        tkl = len(state.token)
        byte0 = (1 << 6) | (msg_type << 4) | tkl  # Version 1
        code = COAP_POST  # Assume POST for telemetry
        
        header = struct.pack('>BBH', byte0, code, state.message_id)
        header += state.token
        
        # Add URI-Path option (simplified: single byte option)
        # Option delta=11 (Uri-Path), length=4
        option = bytes([0xB4]) + b'data'  # /data
        
        # Payload marker + payload
        full_payload = header + option + bytes([0xFF]) + payload
        
        # Track inflight for CON
        if msg_type == COAP_CON:
            state.inflight[state.message_id] = {
                'payload': payload,
                'retries': 0,
                'timestamp': 0
            }
        
        return Packet(
            packet_id=0,
            source_id=device_id,
            dest_id=-1,
            protocol='coap',
            payload=full_payload,
            size_bytes=len(full_payload),
            timestamp_ms=0,
            direction='uplink',
            qos_class=qos_class,
            seq_num=state.message_id
        )
    
    def parse_downlink_packet(self, packet: 'Packet') -> List[dict]:
        """Parse CoAP response/notification."""
        commands = []
        
        if len(packet.payload) < 4:
            return commands
        
        byte0, code, msg_id = struct.unpack('>BBH', packet.payload[:4])
        
        msg_type = (byte0 >> 4) & 0x03
        tkl = byte0 & 0x0F
        
        # Find payload marker
        payload_start = 4 + tkl
        for i in range(payload_start, len(packet.payload)):
            if packet.payload[i] == 0xFF:
                payload_start = i + 1
                break
        
        if payload_start < len(packet.payload):
            cmd_payload = packet.payload[payload_start:]
            
            commands.append({
                'cmd_type': code,
                'epoch_id': msg_id,
                'payload': cmd_payload,
                'confirmable': msg_type == COAP_CON
            })
        
        return commands
    
    def get_overhead_bytes(self) -> int:
        """Get protocol overhead per message."""
        # Header + token + minimal options + payload marker
        return self.HEADER_SIZE + self.TOKEN_SIZE + 5 + 1
    
    def get_ack_overhead(self) -> int:
        """Get ACK message size."""
        # Empty ACK: just header
        return self.HEADER_SIZE
    
    def get_retransmission_overhead(self, reliability: float) -> float:
        """
        Calculate average retransmission overhead based on target reliability.
        
        Args:
            reliability: Target delivery probability (e.g., 0.99)
        """
        # Simplified model: each retransmit has same success probability p
        # Average transmissions = 1 + (1-p) + (1-p)^2 + ... until reliability met
        import math
        
        p_success = 0.95  # Per-transmission success rate
        
        if reliability <= p_success:
            return 1.0
        
        # Solve for n: 1 - (1-p)^n >= reliability
        n = math.ceil(math.log(1 - reliability) / math.log(1 - p_success))
        
        # Average number of transmissions
        avg_tx = sum((1 - p_success)**i for i in range(n))
        
        return avg_tx
