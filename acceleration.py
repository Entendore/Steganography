import numpy as np

# Accelerators Check
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

# JIT Functions
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

def get_accelerator() -> str:
    """Returns the best available accelerator: 'cupy', 'numba', or 'numpy'."""
    if CUPY_INSTALLED:
        try:
            cp.zeros(1)
            return "cupy"
        except Exception:
            pass
    return "numba" if NUMBA_INSTALLED else "numpy"