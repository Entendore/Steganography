import sys
import os
import struct
import zlib
import tempfile
import traceback
import numpy as np
from typing import Optional, Tuple, Dict, Any
from datetime import datetime

# ========================
# 1. LIBRARY IMPORTS
# ========================

# GUI
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QFileDialog,
    QTabWidget, QProgressBar, QGroupBox, QMessageBox, QCheckBox,
    QMenuBar, QDockWidget
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QCursor, QAction

# Image/Video Processing
import cv2

# Audio Processing
try:
    import soundfile as sf
    AUDIO_ENABLED = True
except ImportError:
    AUDIO_ENABLED = False

# Accelerators
try:
    from numba import jit, prange
    NUMBA_INSTALLED = True
except ImportError:
    NUMBA_INSTALLED = False
    def jit(*args, **kwargs):
        def decorator(func): return func
        return decorator
    prange = range

try:
    import cupy as cp
    CUPY_INSTALLED = True
except ImportError:
    CUPY_INSTALLED = False

# Cryptography
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

# ========================
# 2. LOGGING HELPER
# ========================

class LogManager:
    """Centralized logging manager to broadcast messages to GUI and Terminal."""
    def __init__(self):
        self.subscribers = []

    def subscribe(self, callback):
        self.subscribers.append(callback)

    def log(self, level, message):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{level.upper()}] {message}"
        print(formatted)
        for callback in self.subscribers:
            callback(formatted)

# Global Logger Instance
logger = LogManager()

# ========================
# 3. CRYPTO ENGINE
# ========================

class CryptoEngine:
    @staticmethod
    def derive_key(password: str, salt: bytes = b'stego_v6_salt') -> bytes:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    @staticmethod
    def encrypt(data: bytes, password: str) -> bytes:
        if not password: return data
        return Fernet(CryptoEngine.derive_key(password)).encrypt(data)

    @staticmethod
    def decrypt(data: bytes, password: str) -> bytes:
        if not password: return data
        try:
            return Fernet(CryptoEngine.derive_key(password)).decrypt(data)
        except InvalidToken:
            raise ValueError("Decryption failed: Incorrect password or corrupted data.")

# ========================
# 4. LSB ACCELERATION ENGINE
# ========================

@jit(nopython=True, parallel=True)
def _encode_lsb_numba(carrier_flat: np.ndarray, payload_bits: np.ndarray) -> np.ndarray:
    limit = len(payload_bits)
    for i in prange(limit):
        carrier_flat[i] = (carrier_flat[i] & 0xFE) | payload_bits[i]
    return carrier_flat

@jit(nopython=True, parallel=True)
def _decode_lsb_numba(carrier_flat: np.ndarray) -> np.ndarray:
    bits = np.zeros(len(carrier_flat), dtype=np.uint8)
    for i in prange(len(carrier_flat)):
        bits[i] = carrier_flat[i] & 1
    return bits

# ========================
# 5. STEGO ENGINE (Core Logic)
# ========================

class StegoEngine:
    MAGIC = b'STGN'
    VERSION = 6  # Version 6 includes Payload Size in header to fix crypto truncation bugs
    
    # Header V6 Layout:
    # Magic(4) + Ver(1) + Flags(1) + OrigSize(4) + PayloadSize(4) + [FileName]

    @staticmethod
    def get_accelerator():
        if CUPY_INSTALLED:
            try:
                cp.zeros(1) 
                return "cupy"
            except: pass
        return "numba" if NUMBA_INSTALLED else "numpy"

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
        header += struct.pack('>I', len(compressed))  # Payload Size (CRITICAL for correct extraction)
        
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
        # Magic(4) + Ver(1) + Flags(1) + OrigSize(4) + PayloadSize(4) = 14 bytes
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
        bit_ptr = 14 * 8 # 112 bits
        if meta['is_file']:
            # Read 2 bytes for filename length
            fn_len_bytes = read_bytes(bit_ptr, 2)
            fn_len = struct.unpack('>H', fn_len_bytes)[0]
            bit_ptr += 16
            
            # Read filename
            fn_bytes = read_bytes(bit_ptr, fn_len)
            meta['filename'] = fn_bytes.decode('utf-8')
            bit_ptr += fn_len * 8

        # --- 3. Extract EXACT Payload (FIX) ---
        # Calculate exact bits needed
        needed_bits = meta['payload_size'] * 8
        
        if (bit_ptr + needed_bits) > len(raw_bits):
            raise ValueError("Carrier file is truncated or header is corrupt.")

        # Slice exactly the bits we need, no more, no less
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

# ========================
# 6. WORKERS (Threading)
# ========================

class BaseWorker(QThread):
    progress = Signal(int)
    finished = Signal(object)
    error = Signal(str)

class ImageWorker(BaseWorker):
    def __init__(self, path, data, password, is_file, filename, mode='encode'):
        super().__init__()
        self.path, self.data, self.password = path, data, password
        self.is_file, self.filename, self.mode = is_file, filename, mode

    def run(self):
        try:
            logger.log("info", f"Image Worker started ({self.mode})")
            acc = StegoEngine.get_accelerator()
            
            if self.mode == 'encode':
                img = cv2.imread(self.path)
                if img is None: raise FileNotFoundError(f"Cannot read image: {self.path}")
                
                payload = StegoEngine.prepare_payload(self.data, self.password, self.is_file, self.filename)
                payload_bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))
                
                if len(payload_bits) > img.size:
                    raise OverflowError(f"Data too large! Needs {len(payload_bits)} bits, capacity {img.size}.")
                
                self.progress.emit(20)
                flat_img = img.ravel()
                
                if acc == 'cupy':
                    gpu_img = cp.asarray(flat_img)
                    gpu_bits = cp.asarray(payload_bits)
                    gpu_img[:len(gpu_bits)] = cp.bitwise_and(gpu_img[:len(gpu_bits)], 0xFE)
                    gpu_img[:len(gpu_bits)] = cp.bitwise_or(gpu_img[:len(gpu_bits)], gpu_bits)
                    result = cp.asnumpy(gpu_img).reshape(img.shape)
                else:
                    result = _encode_lsb_numba(flat_img, payload_bits).reshape(img.shape)

                self.progress.emit(100)
                logger.log("success", "Encoding complete.")
                self.finished.emit(('image', result))

            elif self.mode == 'decode':
                img = cv2.imread(self.path)
                if img is None: raise FileNotFoundError("Cannot read image.")
                self.progress.emit(10)
                
                flat_img = img.ravel()
                if acc == 'cupy':
                    bits = cp.asnumpy(cp.bitwise_and(cp.asarray(flat_img), 1))
                else:
                    bits = _decode_lsb_numba(flat_img)
                
                self.progress.emit(50)
                data, meta = StegoEngine.parse_payload(bits, self.password)
                logger.log("success", "Decoding successful!")
                self.finished.emit(('data', (data, meta)))

        except Exception as e:
            logger.log("error", str(e))
            self.error.emit(f"Image Error: {str(e)}")

class AudioWorker(BaseWorker):
    def __init__(self, path, data, password, is_file, filename, mode='encode'):
        super().__init__()
        self.path, self.data, self.password, self.is_file, self.filename, self.mode = path, data, password, is_file, filename, mode

    def run(self):
        if not AUDIO_ENABLED: 
            self.error.emit("SoundFile library not installed.")
            return

        try:
            logger.log("info", f"Audio Worker started ({self.mode})")
            
            if self.mode == 'encode':
                audio_data, sr = sf.read(self.path, dtype='int32', always_2d=False)
                payload = StegoEngine.prepare_payload(self.data, self.password, self.is_file, self.filename)
                bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))
                
                if len(bits) > len(audio_data): raise OverflowError("Audio file too small.")
                
                self.progress.emit(20)
                encoded = _encode_lsb_numba(audio_data.flatten(), bits).reshape(audio_data.shape)
                out_path = f"{self.path}_stego.wav"
                sf.write(out_path, encoded, sr)
                logger.log("success", f"Audio saved to {out_path}")
                self.finished.emit(('audio_path', out_path))

            elif self.mode == 'decode':
                audio_data, _ = sf.read(self.path, dtype='int32')
                self.progress.emit(20)
                bits = _decode_lsb_numba(audio_data.flatten())
                self.progress.emit(60)
                data, meta = StegoEngine.parse_payload(bits, self.password)
                logger.log("success", "Decoding successful!")
                self.finished.emit(('data', (data, meta)))

        except Exception as e:
            logger.log("error", str(e))
            self.error.emit(str(e))

class VideoWorker(BaseWorker):
    def __init__(self, path, data, password, is_file, filename, mode='encode'):
        super().__init__()
        self.path, self.data, self.password, self.is_file, self.filename, self.mode = path, data, password, is_file, filename, mode

    def run(self):
        try:
            logger.log("info", f"Video Worker started ({self.mode})")
            
            if self.mode == 'encode':
                cap = cv2.VideoCapture(self.path)
                if not cap.isOpened(): raise FileNotFoundError("Cannot open video.")
                w, h, fps = int(cap.get(3)), int(cap.get(4)), cap.get(5)
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                out_path = f"{self.path}_stego.avi"
                
                # Force FFV1 Lossless Codec
                out = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*'FFV1'), fps, (w,h))
                payload = StegoEngine.prepare_payload(self.data, self.password, self.is_file, self.filename)
                bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))
                
                idx, f_count = 0, 0
                while True:
                    ret, frame = cap.read()
                    if not ret: break
                    
                    if idx < len(bits):
                        chunk = bits[idx : idx + frame.size]
                        if len(chunk) < frame.size: 
                            chunk = np.pad(chunk, (0, frame.size - len(chunk)))
                        
                        flat = frame.ravel()
                        _encode_lsb_numba(flat, chunk)
                        # frame is modified in-place by reference via flat
                        out.write(frame)
                        idx += frame.size
                    else:
                        out.write(frame)
                    
                    f_count += 1
                    if f_count % 10 == 0: self.progress.emit(int((f_count/total)*100))
                        
                cap.release()
                out.release()
                logger.log("success", f"Video saved to {out_path}")
                self.finished.emit(('video_path', out_path))

            elif self.mode == 'decode':
                cap = cv2.VideoCapture(self.path)
                if not cap.isOpened(): raise FileNotFoundError("Cannot open video.")
                
                all_bits = []
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                f_count = 0
                
                while True:
                    ret, frame = cap.read()
                    if not ret: break
                    bits = _decode_lsb_numba(frame.ravel())
                    all_bits.append(bits)
                    f_count += 1
                    if f_count % 10 == 0: self.progress.emit(int((f_count/total)*50))
                
                cap.release()
                raw = np.concatenate(all_bits)
                self.progress.emit(75)
                
                data, meta = StegoEngine.parse_payload(raw, self.password)
                logger.log("success", "Decoding successful!")
                self.finished.emit(('data', (data, meta)))

        except Exception as e:
            logger.log("error", str(e))
            self.error.emit(str(e))

# ========================
# 7. TEST SUITE
# ========================
class TestEngine:
    @staticmethod
    def run_tests(parent_widget):
        logger.log("info", "=== STARTING AUTOMATED TESTS ===")
        results = []
        
        # 1. Image Test (Encrypted)
        try:
            logger.log("info", "Testing Image Logic (Encrypted)...")
            dummy_img_path = os.path.join(tempfile.gettempdir(), "test_carrier.png")
            dummy_img = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
            cv2.imwrite(dummy_img_path, dummy_img)
            
            secret = b"Secret Image Message " * 100
            
            # Encode
            payload_pkg = StegoEngine.prepare_payload(secret, "pass123", False, "")
            bits = np.unpackbits(np.frombuffer(payload_pkg, dtype=np.uint8))
            _encode_lsb_numba(dummy_img.ravel(), bits)
            
            # Decode
            extracted_bits = _decode_lsb_numba(dummy_img.ravel())
            data, meta = StegoEngine.parse_payload(extracted_bits, "pass123")
            
            assert data == secret
            results.append(("Image Encode/Decode (Encrypted)", "PASS"))
            logger.log("success", "Image Test PASSED")
            os.remove(dummy_img_path)
        except Exception as e:
            results.append(("Image Encode/Decode (Encrypted)", f"FAIL ({e})"))
            logger.log("error", f"Image Test FAILED: {e}")

        # 2. Audio Test (Plain)
        if AUDIO_ENABLED:
            try:
                logger.log("info", "Testing Audio Logic (Plain)...")
                dummy_aud_path = os.path.join(tempfile.gettempdir(), "test_carrier.wav")
                sr = 44100
                dummy_aud = np.random.randint(-1000, 1000, (sr*5,), dtype=np.int32)
                sf.write(dummy_aud_path, dummy_aud, sr)
                
                secret = b"Secret Audio Tune"
                
                # Encode
                payload_pkg = StegoEngine.prepare_payload(secret, None, False, "")
                bits = np.unpackbits(np.frombuffer(payload_pkg, dtype=np.uint8))
                enc_aud = _encode_lsb_numba(dummy_aud.copy(), bits)
                
                # Decode
                ext_bits = _decode_lsb_numba(enc_aud)
                data, meta = StegoEngine.parse_payload(ext_bits, None)
                
                assert data == secret
                results.append(("Audio Encode/Decode", "PASS"))
                logger.log("success", "Audio Test PASSED")
                os.remove(dummy_aud_path)
            except Exception as e:
                results.append(("Audio Encode/Decode", f"FAIL ({e})"))
                logger.log("error", f"Audio Test FAILED: {e}")
        else:
            results.append(("Audio", "SKIPPED (Lib Missing)"))

        # 3. Video Test (Encrypted)
        try:
            logger.log("info", "Testing Video Logic (Encrypted)...")
            
            # Create dummy video
            dummy_vid_path = os.path.join(tempfile.gettempdir(), "test_vin.avi")
            out_vid_path = os.path.join(tempfile.gettempdir(), "test_vout.avi")
            
            w, h = 200, 200
            fps = 24
            frames_count = 10
            
            fourcc = cv2.VideoWriter_fourcc(*'FFV1')
            out = cv2.VideoWriter(dummy_vid_path, fourcc, fps, (w, h))
            for _ in range(frames_count):
                frame = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
                out.write(frame)
            out.release()
            
            # Encode
            secret = b"Hidden Video Data inside AVI"
            pwd = "vidpass"
            payload_pkg = StegoEngine.prepare_payload(secret, pwd, False, "")
            payload_bits = np.unpackbits(np.frombuffer(payload_pkg, dtype=np.uint8))
            
            cap = cv2.VideoCapture(dummy_vid_path)
            writer = cv2.VideoWriter(out_vid_path, fourcc, fps, (w, h))
            bit_idx = 0
            
            while True:
                ret, frame = cap.read()
                if not ret: break
                flat = frame.ravel()
                if bit_idx < len(payload_bits):
                    chunk = payload_bits[bit_idx : bit_idx + len(flat)]
                    if len(chunk) < len(flat):
                        chunk = np.pad(chunk, (0, len(flat) - len(chunk)))
                    _encode_lsb_numba(flat, chunk)
                    bit_idx += len(flat)
                writer.write(frame)
            cap.release()
            writer.release()
            
            # Decode
            cap2 = cv2.VideoCapture(out_vid_path)
            all_bits = []
            while True:
                ret, frame = cap2.read()
                if not ret: break
                bits = _decode_lsb_numba(frame.ravel())
                all_bits.append(bits)
            cap2.release()
            
            raw_bits = np.concatenate(all_bits)
            data, meta = StegoEngine.parse_payload(raw_bits, pwd)
            
            assert data == secret
            results.append(("Video Encode/Decode (Encrypted)", "PASS"))
            logger.log("success", "Video Test PASSED")
            
            os.remove(dummy_vid_path)
            os.remove(out_vid_path)
            
        except Exception as e:
            results.append(("Video Encode/Decode", f"FAIL ({e})"))
            logger.log("error", f"Video Test FAILED: {e}")

        # Show Result
        msg = "\n".join([f"{k}: {v}" for k, v in results])
        QMessageBox.information(parent_widget, "Test Results", msg)

# ========================
# 8. MAIN GUI
# ========================

class SteganographyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steganography Pro v2.3 (Complete)")
        self.setMinimumSize(1100, 750)
        self.current_worker = None
        self.apply_styles()
        self.create_menu()
        self.create_ui()
        self.create_console()
        self.check_accelerators()

    def check_accelerators(self):
        acc = StegoEngine.get_accelerator()
        msg = f"Ready | Acceleration: {acc.upper()}"
        if not AUDIO_ENABLED: msg += " | Audio Disabled"
        self.statusBar().showMessage(msg)

    def create_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)
        
        tools_menu = bar.addMenu("Tools")
        test_act = QAction("Run Self-Test", self)
        test_act.triggered.connect(lambda: TestEngine.run_tests(self))
        tools_menu.addAction(test_act)

    def create_console(self):
        dock = QDockWidget("Console Log", self)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("font-family: Consolas; font-size: 11px; color: #00FF00; background-color: #000;")
        dock.setWidget(self.log_console)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        logger.subscribe(self.append_log)

    def append_log(self, msg):
        self.log_console.append(msg)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QWidget { background-color: #121212; color: #E0E0E0; font-family: 'Segoe UI'; font-size: 13px; }
            QMenuBar { background-color: #1E1E1E; border-bottom: 1px solid #333; }
            QMenuBar::item:selected { background-color: #0078D4; }
            QMenu { background-color: #1E1E1E; border: 1px solid #333; }
            QMenu::item:selected { background-color: #0078D4; }
            QGroupBox { border: 1px solid #2D2D2D; border-radius: 5px; margin-top: 20px; font-weight: bold; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #0078D4; }
            QPushButton { background-color: #0078D4; color: white; border-radius: 4px; padding: 10px; font-weight: bold; }
            QPushButton:hover { background-color: #1084D8; }
            QPushButton:disabled { background-color: #333333; color: #666666; }
            QLineEdit, QTextEdit { background-color: #1E1E1E; border: 1px solid #333333; border-radius: 4px; padding: 5px; }
            QProgressBar { border: 2px solid #333; border-radius: 5px; text-align: center; background-color: #1E1E1E; }
            QProgressBar::chunk { background-color: #0078D4; width: 10px; }
            QTabWidget::pane { border: 1px solid #333; background-color: #121212; }
            QTabBar::tab { background-color: #1E1E1E; padding: 10px 20px; border-top-left-radius: 4px; }
            QTabBar::tab:selected { background-color: #0078D4; color: white; }
            QDockWidget { color: #0078D4; titlebar-close-icon: url(close.png); }
            QDockWidget::title { background: #1E1E1E; padding: 6px; }
        """)

    def create_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        header = QLabel("🛡️ Steganography Workflow")
        header.setFont(QFont("Segoe UI", 20, QFont.Bold))
        header.setStyleSheet("color: #0078D4;")
        layout.addWidget(header)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.img_ui = self.create_operation_tab("Image")
        self.aud_ui = self.create_operation_tab("Audio")
        self.vid_ui = self.create_operation_tab("Video")

        self.tabs.addTab(self.img_ui['widget'], "🖼️ Image")
        self.tabs.addTab(self.aud_ui['widget'], "🎵 Audio")
        self.tabs.addTab(self.vid_ui['widget'], "🎬 Video")

    def create_operation_tab(self, name):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        left = QVBoxLayout()
        
        # Step 1
        step1_grp = QGroupBox(f"Step 1: Select Source")
        step1_layout = QVBoxLayout(step1_grp)
        path_h = QHBoxLayout()
        path_edit = QLineEdit(); path_edit.setReadOnly(True)
        btn_browse = QPushButton("📂 Browse")
        path_h.addWidget(path_edit); path_h.addWidget(btn_browse)
        info_lbl = QLabel("ℹ️ Capacity: --"); info_lbl.setStyleSheet("color: #888;")
        step1_layout.addLayout(path_h); step1_layout.addWidget(info_lbl)
        left.addWidget(step1_grp)
        
        # Password
        pwd_grp = QGroupBox("🔐 Security")
        pwd_layout = QHBoxLayout(pwd_grp)
        pass_edit = QLineEdit(); pass_edit.setEchoMode(QLineEdit.Password)
        chk_show = QCheckBox("Show")
        chk_show.toggled.connect(lambda c: pass_edit.setEchoMode(QLineEdit.Normal if c else QLineEdit.Password))
        pwd_layout.addWidget(pass_edit); pwd_layout.addWidget(chk_show)
        left.addWidget(pwd_grp)
        layout.addLayout(left, 40)
        
        # Right Panel
        right = QVBoxLayout()
        step2_grp = QGroupBox("Step 2: Payload")
        step2_layout = QVBoxLayout(step2_grp)
        msg_text = QTextEdit()
        file_data = {'data': None, 'name': None}
        def attach_file():
            p, _ = QFileDialog.getOpenFileName(self, "Select File")
            if p:
                with open(p, 'rb') as f: file_data['data'] = f.read()
                file_data['name'] = os.path.basename(p)
                msg_text.setText(f"Attached: {file_data['name']}\nSize: {len(file_data['data'])} bytes")
        btn_attach = QPushButton("📎 Attach File"); btn_attach.clicked.connect(attach_file)
        step2_layout.addWidget(msg_text); step2_layout.addWidget(btn_attach)
        right.addWidget(step2_grp)
        
        # Actions
        step3_grp = QGroupBox("Step 3: Execute")
        step3_layout = QVBoxLayout(step3_grp)
        btn_encode = QPushButton("🔒 ENCODE"); btn_encode.setStyleSheet("background-color: #28a745; padding: 15px;")
        btn_decode = QPushButton("🔓 DECODE"); btn_decode.setStyleSheet("background-color: #6c757d; padding: 15px;")
        prog_bar = QProgressBar()
        step3_layout.addWidget(btn_encode); step3_layout.addWidget(btn_decode); step3_layout.addWidget(prog_bar)
        right.addWidget(step3_grp)
        layout.addLayout(right, 60)
        
        # Connections
        btn_browse.clicked.connect(lambda: self.browse_file(path_edit, info_lbl, name))
        btn_encode.clicked.connect(lambda: self.start_process('encode', path_edit.text(), file_data, msg_text.toPlainText(), pass_edit.text(), name))
        btn_decode.clicked.connect(lambda: self.start_process('decode', path_edit.text(), None, "", pass_edit.text(), name))
        
        return {'widget': widget, 'path': path_edit, 'info': info_lbl, 'pass': pass_edit, 'msg': msg_text, 'prog': prog_bar, 'btn_enc': btn_encode, 'btn_dec': btn_decode, 'file_data': file_data}

    def browse_file(self, path_edit, info_lbl, type_name):
        filters = {"Image": "Images (*.png *.bmp *.tif)", "Audio": "Audio (*.wav *.flac)", "Video": "Video (*.avi)"}
        path, _ = QFileDialog.getOpenFileName(self, "Select", "", filters.get(type_name, ""))
        if path:
            path_edit.setText(path)
            try:
                size = 0
                if type_name == "Image": size = cv2.imread(path).size // 8
                elif type_name == "Audio": size = len(sf.read(path)[0]) // 8
                elif type_name == "Video":
                    cap = cv2.VideoCapture(path)
                    size = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) * int(cap.get(3)) * int(cap.get(4)) * 3 // 8
                    cap.release()
                info_lbl.setText(f"ℹ️ Capacity: {self.format_size(size)}")
            except: pass

    def start_process(self, mode, path, file_dict, text, password, type_name):
        if not path:
            logger.log("warning", "No source file selected.")
            return

        data, is_file, filename = b"", False, ""
        if mode == 'encode':
            if file_dict['data']: data, is_file, filename = file_dict['data'], True, file_dict['name']
            elif text: data = text.encode('utf-8')
            else: return
            
            save_path, _ = QFileDialog.getSaveFileName(self, "Save", "", "")
            if not save_path: return
            self._save_path = save_path
        
        # Worker Selection
        if type_name == "Image": self.current_worker = ImageWorker(path, data, password, is_file, filename, mode)
        elif type_name == "Audio": self.current_worker = AudioWorker(path, data, password, is_file, filename, mode)
        elif type_name == "Video": self.current_worker = VideoWorker(path, data, password, is_file, filename, mode)
        
        # Signals
        try: self.current_worker.finished.disconnect()
        except: pass
        try: self.current_worker.error.disconnect()
        except: pass

        self.current_worker.progress.connect(self.update_progress)
        self.current_worker.finished.connect(lambda res: self.on_finished(res, type_name, mode))
        self.current_worker.error.connect(lambda err: logger.log("error", err))
        self.current_worker.start()

    def update_progress(self, val):
        idx = self.tabs.currentIndex()
        if idx == 0: self.img_ui['prog'].setValue(val)
        elif idx == 1: self.aud_ui['prog'].setValue(val)
        elif idx == 2: self.vid_ui['prog'].setValue(val)

    def on_finished(self, result, type_name, mode):
        type_res, data = result
        if type_res == 'data':
            meta = data[1]
            data = data[0]
            if meta.get('is_file'):
                p, _ = QFileDialog.getSaveFileName(self, "Save File", meta.get('filename',''))
                if p: open(p, 'wb').write(data)
            else:
                idx = self.tabs.currentIndex()
                target_ui = [self.img_ui, self.aud_ui, self.vid_ui][idx]
                try:
                    target_ui['msg'].setText(data.decode('utf-8'))
                except:
                    target_ui['msg'].setText("Binary data extracted (see log).")
                    logger.log("info", f"Binary data size: {len(data)}")
        elif type_res == 'image':
            cv2.imwrite(self._save_path, data)
            logger.log("success", f"Saved to {self._save_path}")
        elif type_res == 'audio_path' or type_res == 'video_path':
            logger.log("success", f"Saved to {data}")

    def format_size(self, n):
        for u in ['B', 'KB', 'MB', 'GB']:
            if n < 1024: return f"{n:.2f} {u}"
            n /= 1024
        return f"{n:.2f} TB"

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SteganographyApp()
    window.show()
    sys.exit(app.exec())