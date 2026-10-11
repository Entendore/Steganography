import os
import tempfile
import numpy as np
import cv2
import zlib
from PySide6.QtWidgets import QMessageBox
from logger import logger
from stego_engine import StegoEngine
from crypto_engine import CryptoEngine
from acceleration import _encode_lsb_numba, _decode_lsb_numba

# Check optional libs
try:
    import soundfile as sf
    AUDIO_ENABLED = True
except ImportError:
    AUDIO_ENABLED = False

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
            
            dummy_vid_path = os.path.join(tempfile.gettempdir(), "test_vin.avi")
            out_vid_path = os.path.join(tempfile.gettempdir(), "test_vout.avi")
            
            w, h, fps, frames_count = 200, 200, 24, 10
            
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