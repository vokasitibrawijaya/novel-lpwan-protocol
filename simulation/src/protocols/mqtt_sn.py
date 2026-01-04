"""
MQTT-SN Protocol Implementation (Baseline)
==========================================
Simplified implementation for comparison purposes.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
import struct

logger = logging.getLogger(__name__)


# MQTT-SN Message Types
MQTTSN_ADVERTISE = 0x00
MQTTSN_SEARCHGW = 0x01
MQTTSN_GWINFO = 0x02
MQTTSN_CONNECT = 0x04
MQTTSN_CONNACK = 0x05
MQTTSN_WILLTOPICREQ = 0x06
MQTTSN_WILLTOPIC = 0x07
MQTTSN_WILLMSGREQ = 0x08
MQTTSN_WILLMSG = 0x09
MQTTSN_REGISTER = 0x0A
MQTTSN_REGACK = 0x0B
MQTTSN_PUBLISH = 0x0C
MQTTSN_PUBACK = 0x0D
MQTTSN_PUBCOMP = 0x0E
MQTTSN_PUBREC = 0x0F
MQTTSN_PUBREL = 0x10
MQTTSN_SUBSCRIBE = 0x12
MQTTSN_SUBACK = 0x13
MQTTSN_UNSUBSCRIBE = 0x14
MQTTSN_UNSUBACK = 0x15
MQTTSN_PINGREQ = 0x16
MQTTSN_PINGRESP = 0x17
MQTTSN_DISCONNECT = 0x18
MQTTSN_WILLTOPICUPD = 0x1A
MQTTSN_WILLTOPICRESP = 0x1B
MQTTSN_WILLMSGUPD = 0x1C
MQTTSN_WILLMSGRESP = 0x1D


@dataclass
class MQTTSNDeviceState:
    """MQTT-SN device state - more complex than novel protocol."""
    
    # Connection state
    connected: bool = False
    client_id: str = ""
    keep_alive_s: int = 60
    
    # Session state
    clean_session: bool = True
    message_id: int = 0
    
    # Topic registration
    topic_ids: Dict[str, int] = None  # topic_name -> topic_id
    registered_topics: Dict[int, str] = None  # topic_id -> topic_name
    
    # Inflight messages (QoS 1/2)
    inflight_publish: Dict[int, dict] = None  # msg_id -> message
    inflight_pubrel: Dict[int, dict] = None  # msg_id -> message (QoS 2)
    
    # Subscriptions
    subscriptions: Dict[int, int] = None  # topic_id -> qos
    
    # Will message
    will_topic: str = ""
    will_message: bytes = b""
    will_qos: int = 0
    will_retain: bool = False
    
    def __post_init__(self):
        if self.topic_ids is None:
            self.topic_ids = {}
        if self.registered_topics is None:
            self.registered_topics = {}
        if self.inflight_publish is None:
            self.inflight_publish = {}
        if self.inflight_pubrel is None:
            self.inflight_pubrel = {}
        if self.subscriptions is None:
            self.subscriptions = {}
    
    def get_size(self) -> int:
        """Estimate state size in bytes."""
        base_size = 32  # Basic fields
        topic_size = len(self.topic_ids) * 20  # Approx per topic
        inflight_size = (len(self.inflight_publish) + len(self.inflight_pubrel)) * 50
        sub_size = len(self.subscriptions) * 4
        will_size = len(self.will_topic) + len(self.will_message)
        
        return base_size + topic_size + inflight_size + sub_size + will_size


class MQTTSNProtocol:
    """
    MQTT-SN Protocol Implementation (Baseline).
    
    Standard MQTT-SN features:
    - CONNECT/CONNACK handshake
    - Topic registration
    - QoS 0, 1, 2, -1
    - Keep-alive (PINGREQ/PINGRESP)
    - Sleeping clients
    """
    
    # Header overhead varies by message type
    PUBLISH_HEADER_SIZE = 7  # Length(1) + MsgType(1) + Flags(1) + TopicId(2) + MsgId(2)
    CONNECT_SIZE = 10  # Minimum CONNECT
    CONNACK_SIZE = 3
    PUBACK_SIZE = 7
    PINGREQ_SIZE = 2
    PINGRESP_SIZE = 2
    
    def __init__(self, config: dict):
        self.config = config
        
        self.qos_levels = config.get('qos_levels', [0, 1, 2, -1])
        self.keep_alive_s = config.get('keep_alive_s', 60)
        self.topic_id_type = config.get('topic_id_type', 'predefined')
        
        logger.info(f"MQTT-SN protocol initialized: QoS levels={self.qos_levels}")
    
    def create_device_state(self) -> MQTTSNDeviceState:
        """Create MQTT-SN device state."""
        return MQTTSNDeviceState(keep_alive_s=self.keep_alive_s)
    
    def get_device_state_size(self, state: MQTTSNDeviceState) -> int:
        """Get device state size in bytes."""
        return state.get_size()
    
    def create_uplink_packet(self, device_id: int, state: MQTTSNDeviceState,
                             payload: bytes, qos_class: str = 'normal') -> 'Packet':
        """Create MQTT-SN PUBLISH packet."""
        from ..network import Packet
        
        # Map qos_class to QoS level
        if qos_class == 'critical':
            qos = 1
        elif qos_class == 'best_effort':
            qos = 0
        else:
            qos = 1
        
        # Increment message ID
        state.message_id = (state.message_id + 1) % 65536
        
        # Build PUBLISH packet
        # [Length, MsgType, Flags, TopicId(2), MsgId(2), Data...]
        topic_id = 1  # Predefined topic
        msg_id = state.message_id if qos > 0 else 0
        
        flags = (qos & 0x03) << 5  # QoS in bits 5-6
        
        header = struct.pack('>BBHH', 
                            MQTTSN_PUBLISH,
                            flags,
                            topic_id,
                            msg_id)
        
        full_payload = bytes([len(header) + len(payload) + 1]) + header + payload
        
        # Track inflight for QoS 1/2
        if qos > 0:
            state.inflight_publish[msg_id] = {
                'payload': payload,
                'qos': qos,
                'timestamp': 0
            }
        
        return Packet(
            packet_id=0,
            source_id=device_id,
            dest_id=-1,
            protocol='mqtt_sn',
            payload=full_payload,
            size_bytes=len(full_payload),
            timestamp_ms=0,
            direction='uplink',
            qos_class=qos_class,
            seq_num=msg_id
        )
    
    def parse_downlink_packet(self, packet: 'Packet') -> List[dict]:
        """Parse MQTT-SN downlink packet."""
        commands = []
        
        if len(packet.payload) < 2:
            return commands
            
        msg_type = packet.payload[1] if len(packet.payload) > 1 else 0
        
        if msg_type == MQTTSN_PUBLISH:
            # Parse PUBLISH
            if len(packet.payload) >= 7:
                flags = packet.payload[2]
                topic_id = struct.unpack('>H', packet.payload[3:5])[0]
                msg_id = struct.unpack('>H', packet.payload[5:7])[0]
                data = packet.payload[7:]
                
                commands.append({
                    'cmd_type': topic_id,
                    'epoch_id': msg_id,
                    'payload': data,
                    'qos': (flags >> 5) & 0x03
                })
                
        return commands
    
    def get_overhead_bytes(self) -> int:
        """Get protocol overhead per message."""
        return self.PUBLISH_HEADER_SIZE
    
    def get_connection_overhead(self) -> int:
        """Get connection establishment overhead."""
        return self.CONNECT_SIZE + self.CONNACK_SIZE
    
    def get_keepalive_overhead_per_hour(self) -> int:
        """Get keep-alive overhead per hour."""
        pings_per_hour = 3600 / self.keep_alive_s
        return int(pings_per_hour * (self.PINGREQ_SIZE + self.PINGRESP_SIZE))
    
    def get_qos1_ack_overhead(self) -> int:
        """Get QoS 1 ACK overhead (per message)."""
        return self.PUBACK_SIZE
    
    def get_qos2_overhead(self) -> int:
        """Get QoS 2 total overhead (PUBREC + PUBREL + PUBCOMP)."""
        return self.PUBACK_SIZE * 3  # Approximately
