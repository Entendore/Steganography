import os
import numpy as np
import cv2
from PySide6.QtCore import QThread, Signal
from logger import logger
from stego_engine import StegoEngine
from acceleration import get_accelerator, _encode_lsb_numba, _decode_lsb_numba

# Optional Audio
try:
    import soundfile as sf
    AUDIO_ENABLED = True
except ImportError:
    AUDIO_ENABLED = False

# Optional CuPy
try:
    import cupy as cp
    CUPY_INSTALLED = True
except ImportError:
    CUPY_INSTALLED = False

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
            acc = get_accelerator()
            
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