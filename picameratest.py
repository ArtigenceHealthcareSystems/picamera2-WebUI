from picamera2 import Picamera2, Preview
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
import cv2
import time

picam2 = Picamera2()

# Create a video configuration with 1456x1088 output size and explicitly set frame rate
config = picam2.create_video_configuration(
    main={"size": (1456, 1088)},
    lores={"size": (640, 480)},  # Add lower resolution stream for preview
    display="lores",  # Use the lower resolution stream for preview
    controls={"FrameDurationLimits": (16666, 16666), "FrameRate": 60.0}
)

# Configure camera
picam2.configure(config)

# Start preview first - use a smaller window size to reduce processing overhead
picam2.start_preview(Preview.QTGL, width=640, height=480)

# Start camera
picam2.start()

# Print confirmation of settings
current_frame_rate = picam2.camera_controls.get("FrameRate", "unknown")
print(f"Recording with frame rate: {current_frame_rate}")

# Set encoder and output with explicit frame rate
encoder = H264Encoder(framerate=60, bitrate=10000000)
# output = FfmpegOutput("picam2_60fps.mp4", audio=False)
output = "picam2_60fps.h264"

# Record a video at 60 fps - ensure frame rate is set
picam2.set_controls({"FrameRate": 60.0})
picam2.start_recording(encoder=encoder, output=output)

# Record for 100 seconds
print("Recording for 100 seconds...")
print("Press Ctrl+C to stop recording early")

try:
    time.sleep(100)
    print("Recording complete.")
except KeyboardInterrupt:
    print("Recording stopped early by user.")

# Clean up
picam2.stop_recording()
picam2.stop_preview()
picam2.close()
print("Camera closed.")

# Note: If you still need higher frame rates, try these options:
# 1. Comment out the preview lines completely for maximum performance
# 2. Reduce the main resolution (e.g., to 1280x720)
# 3. Run with: taskset -c 0,1,2,3 python3 picameratest.py
#    to prioritize CPU cores for the recording process
