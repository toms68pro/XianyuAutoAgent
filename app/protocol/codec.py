import base64
import json
import struct
from typing import Any, Dict, List


class MessagePackDecoder:
    """MessagePack 纯 Python 异步安全解码器"""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.length = len(data)

    def read_byte(self) -> int:
        if self.pos >= self.length:
            raise ValueError("Unexpected end of data")
        byte = self.data[self.pos]
        self.pos += 1
        return byte

    def read_bytes(self, count: int) -> bytes:
        if self.pos + count > self.length:
            raise ValueError("Unexpected end of data")
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result

    def read_uint8(self) -> int:
        return self.read_byte()

    def read_uint16(self) -> int:
        return struct.unpack('>H', self.read_bytes(2))[0]

    def read_uint32(self) -> int:
        return struct.unpack('>I', self.read_bytes(4))[0]

    def read_uint64(self) -> int:
        return struct.unpack('>Q', self.read_bytes(8))[0]

    def read_int8(self) -> int:
        return struct.unpack('>b', self.read_bytes(1))[0]

    def read_int16(self) -> int:
        return struct.unpack('>h', self.read_bytes(2))[0]

    def read_int32(self) -> int:
        return struct.unpack('>i', self.read_bytes(4))[0]

    def read_int64(self) -> int:
        return struct.unpack('>q', self.read_bytes(8))[0]

    def read_float32(self) -> float:
        return struct.unpack('>f', self.read_bytes(4))[0]

    def read_float64(self) -> float:
        return struct.unpack('>d', self.read_bytes(8))[0]

    def read_string(self, length: int) -> str:
        return self.read_bytes(length).decode('utf-8', errors='replace')

    def decode_value(self) -> Any:
        if self.pos >= self.length:
            raise ValueError("Unexpected end of data")

        format_byte = self.read_byte()

        # Positive fixint (0xxxxxxx)
        if format_byte <= 0x7f:
            return format_byte
        # Fixmap (1000xxxx)
        elif 0x80 <= format_byte <= 0x8f:
            return self.decode_map(format_byte & 0x0f)
        # Fixarray (1001xxxx)
        elif 0x90 <= format_byte <= 0x9f:
            return self.decode_array(format_byte & 0x0f)
        # Fixstr (101xxxxx)
        elif 0xa0 <= format_byte <= 0xbf:
            return self.read_string(format_byte & 0x1f)
        elif format_byte == 0xc0:
            return None
        elif format_byte == 0xc2:
            return False
        elif format_byte == 0xc3:
            return True
        elif format_byte == 0xc4:
            return self.read_bytes(self.read_uint8())
        elif format_byte == 0xc5:
            return self.read_bytes(self.read_uint16())
        elif format_byte == 0xc6:
            return self.read_bytes(self.read_uint32())
        elif format_byte == 0xca:
            return self.read_float32()
        elif format_byte == 0xcb:
            return self.read_float64()
        elif format_byte == 0xcc:
            return self.read_uint8()
        elif format_byte == 0xcd:
            return self.read_uint16()
        elif format_byte == 0xce:
            return self.read_uint32()
        elif format_byte == 0xcf:
            return self.read_uint64()
        elif format_byte == 0xd0:
            return self.read_int8()
        elif format_byte == 0xd1:
            return self.read_int16()
        elif format_byte == 0xd2:
            return self.read_int32()
        elif format_byte == 0xd3:
            return self.read_int64()
        elif format_byte == 0xd9:
            return self.read_string(self.read_uint8())
        elif format_byte == 0xda:
            return self.read_string(self.read_uint16())
        elif format_byte == 0xdb:
            return self.read_string(self.read_uint32())
        elif format_byte == 0xdc:
            return self.decode_array(self.read_uint16())
        elif format_byte == 0xdd:
            return self.decode_array(self.read_uint32())
        elif format_byte == 0xde:
            return self.decode_map(self.read_uint16())
        elif format_byte == 0xdf:
            return self.decode_map(self.read_uint32())
        elif format_byte >= 0xe0:
            return format_byte - 256
        else:
            raise ValueError(f"Unknown format byte: 0x{format_byte:02x}")

    def decode_array(self, size: int) -> List[Any]:
        return [self.decode_value() for _ in range(size)]

    def decode_map(self, size: int) -> Dict[Any, Any]:
        result = {}
        for _ in range(size):
            key = self.decode_value()
            val = self.decode_value()
            result[key] = val
        return result

    def decode(self) -> Any:
        try:
            return self.decode_value()
        except Exception:
            return base64.b64encode(self.data).decode('utf-8')


def decrypt_message(raw_data: str) -> Any:
    """闲鱼钉钉消息解密：Base64 -> MessagePack -> Python 对象"""
    try:
        cleaned = ''.join(c for c in raw_data if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
        while len(cleaned) % 4 != 0:
            cleaned += '='
        
        decoded_bytes = base64.b64decode(cleaned)

        # 优先尝试 MessagePack 解码
        try:
            decoder = MessagePackDecoder(decoded_bytes)
            return decoder.decode()
        except Exception:
            # 回退尝试 UTF-8 JSON
            try:
                text_result = decoded_bytes.decode('utf-8')
                return json.loads(text_result)
            except Exception:
                return {"raw_text": decoded_bytes.decode('utf-8', errors='ignore')}
    except Exception as e:
        return {"error": f"Decrypt failed: {str(e)}", "raw": raw_data}


def encode_chat_payload(text: str) -> str:
    """将文本消息包装为闲鱼 Web 兼容的 Base64 负载"""
    struct_msg = {
        "contentType": 1,
        "text": {
            "text": text
        }
    }
    return base64.b64encode(json.dumps(struct_msg, ensure_ascii=False).encode('utf-8')).decode('utf-8')
