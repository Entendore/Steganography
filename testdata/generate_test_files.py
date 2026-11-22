import numpy as np
import cv2
import os
import sys

# Check for audio library
try:
    import soundfile as sf
    AUDIO_LIB = True
except ImportError:
    AUDIO_LIB = False
    print("⚠️ 'soundfile' not installed. Audio files will not be generated.")
    print("   Install with: pip install soundfile")

def format_size(n):
    for u in ['B', 'KB', 'MB', 'GB']:
        if n < 1024: return f"{n:.2f} {u}"
        n /= 1024
    return f"{n:.2f} TB"

def create_image_png(filename="test_image.png"):
    """
    Creates a PNG image with random noise.
    PNG is lossless and the best format for Image Steganography.
    """
    print(f"🖼️ Generating Image: {filename}...")
    
    # 1920x1080 resolution, 3 channels (RGB)
    width, height = 1920, 1080
    
    # Create a base image with random noise (good for hiding data)
    # np.random.randint is faster for large arrays
    img = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
    
    # Add some visible elements so we can verify the image isn't broken
    cv2.rectangle(img, (100, 100), (400, 400), (255, 0, 0), -1)
    cv2.putText(img, "TEST IMAGE PNG", (150, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    
    cv2.imwrite(filename, img)
    
    # Calculate capacity (Width * Height * 3 channels / 8 bits)
    cap_bytes = (width * height * 3) // 8
    print(f"   ✅ Created: {filename} ({format_size(os.path.getsize(filename))})")
    print(f"   💡 Approx Capacity: {format_size(cap_bytes)}")
    return filename

def create_audio_wav(filename="test_audio.wav"):
    """
    Creates a standard WAV file (Uncompressed PCM).
    """
    if not AUDIO_LIB: return None
    print(f"🎵 Generating Audio: {filename}...")
    
    duration = 15 # seconds
    sample_rate = 44100
    
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    
    # Generate a mix of sine waves (chord)
    signal = 0.3 * np.sin(2 * np.pi * 440 * t) + \
             0.2 * np.sin(2 * np.pi * 554.37 * t) + \
             0.2 * np.sin(2 * np.pi * 659.25 * t)
             
    # Add amplitude noise to make it sound more natural
    # (Static noise is actually better for steganography masking, but let's keep it musical)
    
    # Normalize to 16-bit range
    signal_int16 = np.int16(signal * 32767)
    
    sf.write(filename, signal_int16, sample_rate)
    
    # Calculate capacity (Samples / 8 bits)
    cap_bytes = len(signal_int16) // 8
    print(f"   ✅ Created: {filename} ({format_size(os.path.getsize(filename))})")
    print(f"   💡 Approx Capacity: {format_size(cap_bytes)}")
    return filename

def create_audio_flac(filename="test_audio.flac"):
    """
    Creates a FLAC file (Lossless Compressed Audio).
    """
    if not AUDIO_LIB: return None
    print(f"🎵 Generating Audio: {filename}...")
    
    duration = 15 # seconds
    sample_rate = 44100
    
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    
    # White noise is best for hiding audio data
    signal = np.random.uniform(-0.5, 0.5, len(t))
    
    # Normalize
    signal_int16 = np.int16(signal * 32767)
    
    sf.write(filename, signal_int16, sample_rate)
    
    cap_bytes = len(signal_int16) // 8
    print(f"   ✅ Created: {filename} ({format_size(os.path.getsize(filename))})")
    print(f"   💡 Approx Capacity: {format_size(cap_bytes)}")
    return filename

def create_video_avi(filename="test_video.avi"):
    """
    Creates an AVI video using the FFV1 codec.
    This is the EXACT format the app uses for output.
    """
    print(f"🎬 Generating Video: {filename}...")
    
    width, height = 640, 480
    fps = 30
    duration = 5 # seconds
    
    # FFV1 is the lossless codec used by the app
    fourcc = cv2.VideoWriter_fourcc(*'FFV1')
    out = cv2.VideoWriter(filename, fourcc, fps, (width, height))
    
    total_frames = duration * fps
    
    for i in range(total_frames):
        # Create a frame with moving noise
        frame = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
        
        # Draw a moving circle
        center_x = int((i / total_frames) * width)
        cv2.circle(frame, (center_x, height//2), 50, (0, 255, 0), -1)
        
        # Add frame counter text
        cv2.putText(frame, f"Frame {i}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
        
        out.write(frame)
        
    out.release()
    
    # Capacity calc: Frames * Width * Height * 3 channels / 8 bits
    cap_bytes = (total_frames * width * height * 3) // 8
    print(f"   ✅ Created: {filename} ({format_size(os.path.getsize(filename))})")
    print(f"   💡 Approx Capacity: {format_size(cap_bytes)}")
    return filename

if __name__ == "__main__":
    print("\n" + "="*40)
    print("   STEGANOGRAPHY TEST FILE GENERATOR")
    print("="*40 + "\n")
    
    # 1. Generate Images (PNG Recommended)
    create_image_png("carrier_image.png")
    
    # 2. Generate Audio
    create_audio_wav("carrier_audio.wav")
    create_audio_flac("carrier_audio.flac")
    
    # 3. Generate Video (AVI FFV1)
    create_video_avi("carrier_video.avi")
    
    print("\n" + "="*40)
    print("   GENERATION COMPLETE")
    print("="*40)
    print("Files saved in current directory.")
    print("\nINSTRUCTIONS:")
    print("1. Load 'carrier_image.png' into the Image tab.")
    print("2. Load 'carrier_audio.flac' into the Audio tab.")
    print("3. Load 'carrier_video.avi' into the Video tab.")