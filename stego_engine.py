import struct
import zlib
import numpy as np
from typing import Optional, Tuple, Dict, Any
from crypto_engine import CryptoEngine

class StegoEngine:
    MAGIC = b'STGN'
    VERSION = 6  # Version 6 includes Payload Size in header
    
    # Header V6 Layout:
    # Magic(4) + Ver(1) + Flags(1) + OrigSize(4) + PayloadSize(4) + [FileName]

    @staticmethod
    def bits_to_bytes(bits: np.ndarray) -> bytes:
        # Efficient bit packing
        pad_len = (8 - len(bits) % 8) % 8
        if pad_len != 0:
            bits = np.pad(bits, (0, pad_len))
        return bytes(np.packbits(bits).tolist())

    @staticmethod
    def prepare_payload(data: bytes, password: Optional[str], is_file: bool, filename: str) -> bytes:
        compressed = zlib.compress(data, level=9)
        if password:
            compressed = CryptoEngine.encrypt(compressed, password)
        
        # Build Header
        header = StegoEngine.MAGIC
        header += struct.pack('B', StegoEngine.VERSION)
        flags = 0x02 | (0x01 if password else 0) | (0x04 if is_file else 0)
        header += struct.pack('B', flags)
        header += struct.pack('>I', len(data))        # Original Size
        header += struct.pack('>I', len(compressed))  # Payload Size (CRITICAL for extraction)
        
        if is_file:
            fn_bytes = filename.encode('utf-8')
            header += struct.pack('>H', len(fn_bytes))
            header += fn_bytes
            
        return header + compressed

    @staticmethod
    def parse_payload(raw_bits: np.ndarray, password: Optional[str]) -> Tuple[bytes, dict]:
        # Helper to read specific byte chunks from bits
        def read_bytes(offset_bits, byte_count):
            start = offset_bits
            end = start + (byte_count * 8)
            if end > len(raw_bits):
                raise ValueError("Incomplete header data in carrier.")
            return StegoEngine.bits_to_bytes(raw_bits[start:end])

        # --- 1. Parse Base Header (14 bytes) ---
        base_header_bytes = read_bytes(0, 14)
        
        if base_header_bytes[:4] != StegoEngine.MAGIC:
            raise ValueError("No hidden data found (Magic bytes mismatch).")

        version = base_header_bytes[4]
        if version != 6:
            raise ValueError(f"Unsupported version: {version}. Expected 6.")

        flags = base_header_bytes[5]
        orig_size = struct.unpack('>I', base_header_bytes[6:10])[0]
        payload_size = struct.unpack('>I', base_header_bytes[10:14])[0]

        meta = {
            'version': version, 
            'encrypted': bool(flags & 0x01), 
            'compressed': True, 
            'is_file': bool(flags & 0x04),
            'original_size': orig_size,
            'payload_size': payload_size
        }

        # --- 2. Parse Optional Filename ---
        bit_ptr = 14 * 8 
        if meta['is_file']:
            fn_len_bytes = read_bytes(bit_ptr, 2)
            fn_len = struct.unpack('>H', fn_len_bytes)[0]
            bit_ptr += 16
            
            fn_bytes = read_bytes(bit_ptr, fn_len)
            meta['filename'] = fn_bytes.decode('utf-8')
            bit_ptr += fn_len * 8

        # --- 3. Extract EXACT Payload ---
        needed_bits = meta['payload_size'] * 8
        
        if (bit_ptr + needed_bits) > len(raw_bits):
            raise ValueError("Carrier file is truncated or header is corrupt.")

        payload_bits = raw_bits[bit_ptr : bit_ptr + needed_bits]
        payload_bytes = StegoEngine.bits_to_bytes(payload_bits)

        # --- 4. Post-Process ---
        if meta['encrypted']:
            if not password:
                raise PermissionError("Password required for this file.")
            payload_bytes = CryptoEngine.decrypt(payload_bytes, password)
        
        if meta['compressed']:
            try:
                payload_bytes = zlib.decompress(payload_bytes)
            except zlib.error:
                raise ValueError("Data corruption detected (Zlib error).")

        return payload_bytes, meta