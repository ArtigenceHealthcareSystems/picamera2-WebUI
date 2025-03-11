import os, io, logging, json, time, re
from datetime import datetime
from threading import Condition
import threading
import argparse
import subprocess  # For running libcamera-vid command
import signal      # For handling process signals
import shlex       # For properly escaping command arguments

from flask import Flask, render_template, request, jsonify, Response, send_file, abort, session

import secrets

from PIL import Image

from gpiozero import Button, LED

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.encoders import MJPEGEncoder
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from libcamera import Transform, controls

# Init Flask
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Generates a random 32-character hexadecimal string
# https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie#samesitesamesite-value
app.config["SESSION_COOKIE_SAMESITE"] = "None"
Picamera2.set_logging(Picamera2.DEBUG)

# Get global camera information
global_cameras = Picamera2.global_camera_info()
# global_cameras = [global_cameras[0]]

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
# Define the path to the camera-config.json file
camera_config_path = os.path.join(current_dir, 'camera-config.json')
last_config_file_path = os.path.join(current_dir, 'camera-last-config.json')


# Load the camera-module-info.json file
with open(os.path.join(current_dir, 'camera-module-info.json'), 'r') as file:
    camera_module_info = json.load(file)

# Define the minimum required configuration
minimum_last_config = {
    "cameras": []
}

gpio_template = [
    {'pin': 1, 'label': '3v3 Power', 'status': 'disabled', 'color': 'warning'},
    {'pin': 2, 'label': '5v Power', 'status': 'disabled', 'color': 'danger'},
    {'pin': 3, 'label': 'GPIO 2', 'status': '', 'color': 'primary'},
    {'pin': 4, 'label': '5v Power', 'status': 'disabled', 'color': 'danger'},
    {'pin': 5, 'label': 'GPIO 3', 'status': '', 'color': 'primary'},
    {'pin': 6, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 7, 'label': 'GPIO 4', 'status': '', 'color': 'success'},
    {'pin': 8, 'label': 'GPIO 14', 'status': '', 'color': 'purple'},
    {'pin': 9, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 10, 'label': 'GPIO 10', 'status': '', 'color': 'purple'},
    {'pin': 11, 'label': 'GPIO 17', 'status': '', 'color': 'success'},
    {'pin': 12, 'label': 'GPIO 18', 'status': '', 'color': 'info'},
    {'pin': 13, 'label': 'GPIO 27', 'status': '', 'color': 'success'},
    {'pin': 14, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 15, 'label': 'GPIO 22', 'status': '', 'color': 'success'},
    {'pin': 16, 'label': 'GPIO 23', 'status': '', 'color': 'success'},
    {'pin': 17, 'label': '3v3 Power', 'status': 'disabled', 'color': 'warning'},
    {'pin': 18, 'label': 'GPIO 24', 'status': '', 'color': 'success'},
    {'pin': 19, 'label': 'GPIO 10', 'status': '', 'color': 'pink'},
    {'pin': 20, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 21, 'label': 'GPIO 9', 'status': '', 'color': 'pink'},
    {'pin': 22, 'label': 'GPIO 25', 'status': '', 'color': 'success'},
    {'pin': 23, 'label': 'GPIO 11', 'status': '', 'color': 'pink'},
    {'pin': 24, 'label': 'GPIO 8', 'status': '', 'color': 'pink'},
    {'pin': 25, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 26, 'label': 'GPIO 7', 'status': '', 'color': 'pink'},
    {'pin': 27, 'label': 'GPIO 0', 'status': '', 'color': 'primary'},
    {'pin': 28, 'label': 'GPIO 1', 'status': '', 'color': 'primary'},
    {'pin': 29, 'label': 'GPIO 5', 'status': '', 'color': 'success'},
    {'pin': 30, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 31, 'label': 'GPIO 6', 'status': '', 'color': 'success'},
    {'pin': 32, 'label': 'GPIO 12', 'status': '', 'color': 'success'},
    {'pin': 33, 'label': 'GPIO 13', 'status': '', 'color': 'success'},
    {'pin': 34, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 35, 'label': 'GPIO 19', 'status': '', 'color': 'info'},
    {'pin': 36, 'label': 'GPIO 16', 'status': '', 'color': 'success'},
    {'pin': 37, 'label': 'GPIO 27', 'status': '', 'color': 'success'},
    {'pin': 38, 'label': 'GPIO 20', 'status': '', 'color': 'info'},
    {'pin': 39, 'label': 'Ground', 'status': 'disabled', 'color': 'dark'},
    {'pin': 40, 'label': 'GPIO 21', 'status': '', 'color': 'info'}  
]

# Function to load or initialize configuration
def load_or_initialize_config(file_path, default_config):
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            try:
                config = json.load(file)
                if not config:  # Check if the file is empty
                    raise ValueError("Empty configuration file")
            except (json.JSONDecodeError, ValueError):
                # If file is empty or invalid, create new config
                with open(file_path, 'w') as file:
                    json.dump(default_config, file, indent=4)
                config = default_config
    else:
        # Create the file with minimum configuration if it doesn't exist
        with open(file_path, 'w') as file:
            json.dump(default_config, file, indent=4)
        config = default_config
    return config

# Load or initialize the configuration
camera_last_config = load_or_initialize_config(last_config_file_path, minimum_last_config)


# Set the path where the images will be stored
CAMERA_CONFIG_FOLDER = os.path.join(current_dir, 'static/camera_config')
app.config['CAMERA_CONFIG_FOLDER'] = CAMERA_CONFIG_FOLDER
# Create the upload folder if it doesn't exist
os.makedirs(app.config['CAMERA_CONFIG_FOLDER'], exist_ok=True)

# Set the path where the images will be stored
UPLOAD_FOLDER = os.path.join(current_dir, 'static/gallery')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.buffer = io.BytesIO()
        self.condition = Condition()
        self.frame_count = 0
        self.fps = 0.0
        self.last_time = time.time()
        self.last_frame_time = time.time()
        self.frame_size = 0
        self.frame_intervals = []  # Keep track of recent frame intervals
        self.max_intervals = 30    # Store up to 30 frame intervals for averaging
        self.max_valid_fps = 120.0  # Maximum valid FPS value
        print("DEBUG: StreamingOutput initialized")

    def write(self, buf):
        try:
            current_time = time.time()
            buf_size = len(buf)
            
            if buf_size == 0:
                print("DEBUG: Received empty buffer in write")
                return
            
            try:
                self.buffer.seek(0)
                self.buffer.truncate()
                self.buffer.write(buf)
                self.frame_size = buf_size
            except IOError as e:
                print(f"DEBUG: Error writing to buffer: {e}")
                return
            
            # Calculate and validate frame interval
            frame_interval = current_time - self.last_frame_time
            if frame_interval > 0:  # Only store valid intervals
                self.frame_intervals.append(frame_interval)
                # Keep only the most recent intervals
                if len(self.frame_intervals) > self.max_intervals:
                    self.frame_intervals.pop(0)
            
            self.last_frame_time = current_time
            self.frame_count += 1
            
            time_diff = current_time - self.last_time
            if time_diff >= 1.0:
                try:
                    # Calculate FPS based on actual frame count and time
                    calculated_fps = float(self.frame_count) / time_diff
                    
                    # Validate FPS value
                    if calculated_fps > self.max_valid_fps:
                        print(f"DEBUG: Invalid FPS detected: {calculated_fps}, capping at {self.max_valid_fps}")
                        calculated_fps = self.max_valid_fps
                    
                    self.fps = round(calculated_fps, 1)
                    
                    # Calculate and validate average frame interval
                    if self.frame_intervals:
                        avg_interval = sum(self.frame_intervals) / len(self.frame_intervals)
                        print(f"DEBUG: Actual FPS: {self.fps}, Avg interval: {avg_interval*1000:.1f}ms")
                    
                    # Reset counters
                    self.frame_intervals = []
                    self.frame_count = 0
                    self.last_time = current_time
                    
                except (TypeError, ValueError, ZeroDivisionError) as e:
                    print(f"DEBUG: FPS calculation error: {e}")
                    self.fps = 0.0
            
            with self.condition:
                self.condition.notify_all()
                
        except Exception as e:
            print(f"DEBUG: Error in StreamingOutput.write: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            self.fps = 0.0

    def get_current_fps(self):
        """Get the current actual FPS"""
        return self.fps

    def get_current_latency(self):
        """Get the current frame latency in milliseconds"""
        if not self.frame_intervals:
            return 0.0
        # Use the most recent frame interval for latency
        return self.frame_intervals[-1] * 1000  # Convert to milliseconds

# Define a function to generate the stream for a specific camera
def generate_stream(camera):
    """Generator function for streaming video frames"""
    print("DEBUG: Starting generate_stream function")
    
    if not camera:
        print("DEBUG: Camera is None")
        return
    
    # Use the correct streaming output attribute
    if hasattr(camera, 'output'):
        output = camera.output
    else:
        print("DEBUG: Camera has no output attribute")
        return
    
    if not output:
        print("DEBUG: Camera output is None")
        return
    
    try:
        while True:
            try:
                # Wait for a new frame
                print("DEBUG: Waiting for next frame")
                with output.condition:
                    output.condition.wait(timeout=1.0)
                    
                    # Get the frame
                    frame = output.read_frame()
                        
                    if frame:
                        print(f"DEBUG: Got frame of size {len(frame)} bytes")
                        yield (b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                    else:
                        print("DEBUG: No frame received")
                        time.sleep(0.1)  # Short sleep to prevent busy-waiting
            except Exception as e:
                print(f"DEBUG: Error in frame generation: {e}")
                time.sleep(0.1)  # Short sleep to prevent busy-waiting
    except Exception as e:
        print(f"DEBUG: Error in generate_stream: {e}")
        import traceback
        print(f"DEBUG: Traceback:\n{traceback.format_exc()}")

class LibcameraProcess:
    """Class to manage libcamera-vid processes for streaming and recording"""
    def __init__(self, camera_num, output_handler=None):
        self.camera_num = camera_num
        self.process = None
        self.output_handler = output_handler
        self.is_running = False
        self.cmd_args = []
        print(f"DEBUG: LibcameraProcess initialized for camera {camera_num}")
        
    def start(self, width, height, fps=60, output=None, timeout=0, nopreview=True, codec="mjpeg", quality=90, hflip=False, vflip=False, additional_args=None):
        """Start a libcamera-vid process with the specified parameters"""
        if self.is_running:
            print("DEBUG: Stopping existing process before starting new one")
            self.stop()
            time.sleep(0.1)  # Reduced wait time
            
        # Check for any existing libcamera processes and kill them
        try:
            print("DEBUG: Checking for existing libcamera processes")
            subprocess.run(["pkill", "-f", "libcamera-vid"], stderr=subprocess.DEVNULL)
            time.sleep(0.1)  # Reduced wait time
        except Exception as e:
            print(f"DEBUG: Error killing existing processes: {e}")
            
        # Base command with performance optimizations
        cmd = ["libcamera-vid"]
        
        # Add camera selection if needed
        if self.camera_num > 0:
            cmd.extend(["--camera", str(self.camera_num)])
            
        # Add resolution
        cmd.extend(["--width", str(width), "--height", str(height)])
        
        # Add frame rate with performance optimizations
        cmd.extend(["--framerate", str(fps)])
        
        # Add codec
        cmd.extend(["--codec", codec])
        
        # Add quality for MJPEG with slight reduction for better performance
        if codec.lower() == "mjpeg":
            cmd.extend(["--quality", str(quality)])
            
        # Add inline headers for MJPEG streaming
        if codec.lower() == "mjpeg" and not output:
            cmd.append("--inline")
            # Add segmentation for streaming (with a value)
            cmd.extend(["--segment", "1"])
        
        # Add timeout (0 = run indefinitely)
        cmd.extend(["--timeout", str(timeout)])
        
        # Add nopreview flag if needed
        if nopreview:
            cmd.append("--nopreview")
            
        # Add rotation flags if needed
        if hflip:
            cmd.append("--hflip")
        if vflip:
            cmd.append("--vflip")
            
        # Performance optimization flags
        cmd.extend([
            "--buffer-count", "2",  # Minimize frame buffering
            "--flush", "1"  # Flush frames immediately
        ])
            
        # Add output file if provided
        if output:
            # Ensure the directory exists
            output_dir = os.path.dirname(output)
            if output_dir and not os.path.exists(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    print(f"DEBUG: Created output directory: {output_dir}")
                except Exception as e:
                    print(f"DEBUG: Error creating output directory: {e}")
                    return False
                    
            # Make sure output has a % directive if using segment
            if "--segment" in cmd and "%" not in output:
                # Add segment number to filename
                base, ext = os.path.splitext(output)
                output = f"{base}_%04d{ext}"
                
            # Test if we can write to the output file
            try:
                # Touch the file to ensure we can write to it
                with open(output, 'a'):
                    pass
                print(f"DEBUG: Successfully verified write access to: {output}")
            except Exception as e:
                print(f"DEBUG: Cannot write to output file: {e}")
                return False
                
            cmd.extend(["--output", output])
        else:
            # If no output file, output to stdout for streaming
            cmd.extend(["--output", "-"])
            
        # Add any additional arguments
        if additional_args:
            cmd.extend(additional_args)
            
        # Store the command arguments for logging
        self.cmd_args = cmd
        print(f"DEBUG: Starting libcamera-vid with command: {' '.join(cmd)}")
        
        try:
            # Start the process with optimized buffer sizes
            if output:
                # If outputting to a file, use smaller buffer for better performance
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,  # Capture stdout instead of discarding it
                    stderr=subprocess.PIPE,  # Capture stderr for debugging
                    bufsize=4096
                )
                
                # Start a thread to monitor the process output for errors
                threading.Thread(target=self._monitor_process_output, daemon=True).start()
            else:
                # For streaming, use the output handler
                if self.output_handler:
                    self.process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=4096
                    )
                    self.stdout_thread = threading.Thread(target=self._handle_stdout, daemon=True)
                    self.stdout_thread.start()
                else:
                    # No output handler, just pipe to DEVNULL
                    self.process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        bufsize=4096
                    )
                    
            self.is_running = True
            print("DEBUG: Process started successfully")
            return True
            
        except Exception as e:
            print(f"DEBUG: Error starting libcamera-vid process: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            self.process = None
            self.is_running = False
            return False
            
    def _monitor_process_output(self):
        """Monitor process output for errors"""
        try:
            for line in self.process.stderr:
                line = line.decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"DEBUG: libcamera-vid stderr: {line}")
                    
            # Check if process exited with error
            if self.process.poll() is not None and self.process.returncode != 0:
                print(f"DEBUG: libcamera-vid process exited with code: {self.process.returncode}")
        except Exception as e:
            print(f"DEBUG: Error monitoring process output: {e}")

    def _handle_stdout(self):
        """Handle stdout from the libcamera-vid process"""
        print("DEBUG: Stdout handler thread started")
        
        if not self.process or not self.process.stdout:
            print("DEBUG: No process or stdout available")
            return
            
        try:
            while self.is_running and self.process and self.process.poll() is None:
                try:
                    # Read a chunk from stdout with a timeout
                    chunk = self.process.stdout.read1(32768)  # Use read1 for better buffering
                    
                    if not chunk:
                        print("DEBUG: Empty chunk received, checking process status")
                        if self.process.poll() is not None:
                            print(f"DEBUG: Process exited with code {self.process.poll()}")
                            break
                        continue
                    
                    print(f"DEBUG: Received chunk of size {len(chunk)} bytes")
                    
                    # Pass the chunk to the output handler
                    if self.output_handler:
                        self.output_handler.write(chunk)
                    else:
                        print("DEBUG: No output handler available")
                        
                except IOError as e:
                    print(f"DEBUG: IOError reading from stdout: {e}")
                    if not self.is_running or self.process.poll() is not None:
                        break
                    time.sleep(0.1)  # Brief pause before retry
                    
        except Exception as e:
            print(f"DEBUG: Fatal error in stdout handler: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
        finally:
            print("DEBUG: Stdout handler thread ending")
            if self.process and self.process.poll() is None:
                print("DEBUG: Process still running at handler exit")
            else:
                print("DEBUG: Process not running at handler exit")

    def stop(self):
        """Stop the libcamera-vid process"""
        if self.process:
            try:
                print("DEBUG: Attempting to stop process")
                # Try to terminate gracefully first
                self.process.terminate()
                
                # Wait a bit for the process to terminate
                try:
                    self.process.wait(timeout=2)
                    print("DEBUG: Process terminated gracefully")
                except subprocess.TimeoutExpired:
                    # If it doesn't terminate, kill it
                    print("DEBUG: Process did not terminate, forcing kill")
                    self.process.kill()
                    self.process.wait()
            except Exception as e:
                print(f"DEBUG: Error stopping libcamera-vid process: {e}")
            
            self.process = None
            self.is_running = False
            print("DEBUG: Process stopped")
        return True
        
    def is_alive(self):
        """Check if the process is still running"""
        is_alive = self.is_running and self.process and self.process.poll() is None
        print(f"DEBUG: Process alive status: {is_alive}")
        return is_alive

# CameraObject that will store the itteration of 1 or more cameras
class CameraObject:
    def __init__(self, camera_num, camera_info):
        # Store camera info but don't initialize Picamera2
        self.camera_info = camera_info
        self.camera = None  # Will be initialized on demand
        
        # Initialize recording attributes
        self.recording = False
        self.recording_process = None
        self.video_path = None
        
        # Default controls for the Camera (will be populated when camera is initialized)
        self.settings = {}
        
        # Initialize other attributes
        self.sensor_modes = []
        self.streaming_process = None
        self.output = None
        
        # Load or create default configuration
        self.live_config = self.default_camera_settings()
        
        # Initialize output resolutions
        self.output_resolutions = {
            "0": (1456, 1088)  # Default resolution
        }
        
        print(f"\nCamera Settings:\n{self.live_config.get('capture-settings', {})}\n")
        
        # Get the resolution from the config
        resolution = self.live_config.get('capture-settings', {}).get("Resolution", "0")
        if resolution in self.output_resolutions:
            print(f"\nCamera Set Resolution:\n{self.output_resolutions[resolution]}\n")
    
    def init_camera(self):
        """Initialize the Picamera2 instance on demand"""
        if self.camera is not None:
            # Camera already initialized
            return self.camera
            
        try:
            print(f"DEBUG: Initializing Picamera2 for camera {self.camera_info.get('Num', 0)}")
            self.camera = Picamera2(self.camera_info.get('Num', 0))
            self.settings = self.camera.camera_controls
            self.sensor_modes = self.camera.sensor_modes
            return self.camera
        except Exception as e:
            print(f"DEBUG: Error initializing camera: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            return None
    
    def release_camera(self):
        """Release the Picamera2 instance"""
        if self.camera is not None:
            try:
                print(f"DEBUG: Releasing Picamera2 for camera {self.camera_info.get('Num', 0)}")
                self.camera.close()
                self.camera = None
                time.sleep(1)  # Give time for resources to be released
                return True
            except Exception as e:
                print(f"DEBUG: Error releasing camera: {e}")
                import traceback
                print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
                return False
        return True

    def build_default_config(self):
        default_config = {}
        for control, values in self.settings.items():
            if control in ['ScalerCrop', 'ScalerCrops', 'AfPause', 'FrameDurationLimits', 'NoiseReductionMode', 'AfMetering', 'ColourGains', 'StatsOutputEnable', 'AfWindows', 'AeFlickerPeriod', 'HdrMode', 'AfTrigger']:
                continue  # Skip ScalerCrop for debugging purposes
            
            if isinstance(values, tuple) and len(values) == 3:
                min_value, max_value, default_value = values
                
                # Handle default_value being None
                if default_value is None:
                    default_value = min_value  # Assign minimum value if default is None
                
                # Handle array or span types (example with ScalerCrop)
                if isinstance(min_value, (list, tuple)):
                    default_value = list(min_value)  # Convert to list if needed
                
                default_config[control] = default_value
        return default_config
    
    def setbutton(self):
        if self.live_config['GPIO']['enableGPIO']:
            if self.live_config['GPIO']['button'] >= 1:
                self.button = Button(f'BOARD{self.live_config["GPIO"]["button"]}', bounce_time = 0.1)
                self.button.when_pressed = self.take_photo
                self.current_button = self.live_config["GPIO"]["button"]
                
    def setled(self):
        if self.live_config['GPIO']['enableGPIO']:
            if self.live_config['GPIO']['led'] >= 1:
                self.led = LED(f'BOARD{self.live_config["GPIO"]["led"]}')
                self.led.on()

    def available_resolutions(self):
        # Use a set to collect unique resolutions
        resolutions_set = set()
        for mode in self.sensor_modes:
            size = mode.get('size')
            if size:
                resolutions_set.add(size)
        # Convert the set back to a list
        unique_resolutions = list(resolutions_set)
        # Sort the resolutions from smallest to largest
        sorted_resolutions = sorted(unique_resolutions, key=lambda x: (x[0] * x[1], x))
        return sorted_resolutions

    def take_photo(self):
        """Take a photo with the camera"""
        try:
            # Initialize camera on demand
            camera = self.init_camera()
            if not camera:
                print("DEBUG: Failed to initialize camera for photo capture")
                return None
                
            # Configure camera
            self.configure_camera()
            
            # Create output directory if it doesn't exist
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(UPLOAD_FOLDER, f"pimage_{timestamp}.jpg")
            
            # Capture image
            camera.capture_file(filepath)
            
            # Release camera
            self.release_camera()
            
            print(f"DEBUG: Photo captured successfully: {filepath}")
            return filepath
        except Exception as e:
            print(f"DEBUG: Error capturing photo: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            # Make sure to release camera on error
            self.release_camera()
            return None

    def start_streaming(self):
        """Start streaming from the camera"""
        try:
            print("DEBUG: Starting streaming process")
            
            # Create a new streaming output
            self.output = StreamingOutput()
            
            # Get settings from camera
            encoder = self.live_config.get('capture-settings', {}).get("Encoder", "MJPEGEncoder")
            frame_rate = self.live_config.get('capture-settings', {}).get("FrameRate", 60)
            print(f"DEBUG: Using encoder: {encoder}, frame rate: {frame_rate}")
            
            # Get current resolution
            selected_resolution = self.live_config.get('capture-settings', {}).get("Resolution", "1456x1088")
            if hasattr(self, 'output_resolutions') and selected_resolution in self.output_resolutions:
                resolution = self.output_resolutions[selected_resolution]
                width, height = resolution
            else:
                # Default resolution if not found
                print(f"DEBUG: Resolution '{selected_resolution}' not found in output_resolutions, using default")
                width, height = 1456, 1088
                
            print(f"DEBUG: Using resolution: {width}x{height}")
            
            # Get rotation settings
            hflip = self.live_config.get('rotation', {}).get('hflip', 0) == 1
            vflip = self.live_config.get('rotation', {}).get('vflip', 0) == 1
            print(f"DEBUG: Rotation settings - hflip: {hflip}, vflip: {vflip}")
            
            # Stop any existing streaming process
            if self.streaming_process and self.streaming_process.is_alive():
                print("DEBUG: Stopping existing streaming process")
                self.streaming_process.stop()
                time.sleep(0.5)  # Give process time to fully stop
            
            # Create a new streaming process
            print("DEBUG: Creating new streaming process")
            # Use camera_info["Num"] instead of camera_num
            camera_number = self.camera_info.get("Num", 0)
            print(f"DEBUG: Using camera number: {camera_number}")
            self.streaming_process = LibcameraProcess(camera_number, self.output)
            
            # Start the streaming process
            success = self.streaming_process.start(
                width=width,
                height=height,
                fps=frame_rate,
                codec="mjpeg",
                quality=90,
                hflip=hflip,
                vflip=vflip,
                # Don't add any additional arguments that might conflict
                additional_args=None
            )
            
            if success:
                print(f"DEBUG: Successfully started stream with libcamera-vid at {frame_rate} FPS")
                return True
            else:
                print("DEBUG: Failed to start streaming process")
                return False
                
        except Exception as e:
            print(f"DEBUG: Error in start_streaming: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            return False

    def stop_streaming(self):
        """Stop streaming and release all resources"""
        print("DEBUG: Stopping streaming process")
        
        try:
            # Stop the streaming process
            if self.streaming_process:
                print("DEBUG: Stopping libcamera process")
                self.streaming_process.stop()
                self.streaming_process = None
            
            # Clear the output handler
            if hasattr(self, 'output'):
                print("DEBUG: Clearing output handler")
                self.output = None
                
            # Make sure to kill any lingering libcamera processes
            try:
                print("DEBUG: Killing any lingering libcamera processes")
                subprocess.run(["pkill", "-f", "libcamera-vid"], stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"DEBUG: Error killing processes: {e}")
                
            print("DEBUG: Streaming stopped successfully")
            return True
        except Exception as e:
            print(f"DEBUG: Error in stop_streaming: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            return False

    def load_settings_from_file(self, config_location):
        with open(os.path.join(CAMERA_CONFIG_FOLDER ,config_location), 'r') as file:
            return json.load(file)
        
    def update_settings(self, new_settings):
        self.settings.update(new_settings)

    def save_settings_to_file(self):
        with open(self.camera_info['Config_Location'], 'w') as file:
            json.dump(self.settings, file)

    def configure_camera(self):
        try:
            # Attempt to set the controls
            self.camera.set_controls(self.live_config['controls'])
            print('\nControls set successfully.\n')
            
            # Adding a small sleep to ensure operations are completed
            time.sleep(0.5)
        except Exception as e:
            # Log the exception
            logging.error("An error occurred while configuring the camera: %s", str(e))
            print(f"\nAn error occurred: {str(e)}\n")
    
    def file_exists(self, file_name, file_path):
        file = os.path.join(file_path ,file_name)
        return os.path.exists(file)

    def default_camera_settings(self):
        """Create default camera settings"""
        # Default capture settings
        self.capture_settings = {
            "Resize": False,
            "makeRaw": False,
            "Resolution": "0",  # Default resolution index
            "Encoder": "MJPEGEncoder",
            "FrameRate": 60
        }
        
        # Default rotation settings
        self.rotation_settings = {
            "hflip": 0,
            "vflip": 0
        }
        
        # Default controls
        self.controls = {
            "AeMeteringMode": 0,
            "Contrast": 1.0,
            "AnalogueGain": 1.0,
            "AeEnable": False,
            "SyncFrames": 100,
            "ExposureValue": 0.0,
            "AeFlickerMode": 0,
            "ExposureTime": 20000,
            "AeExposureMode": 0,
            "SyncMode": 0,
            "AeConstraintMode": 0,
            "AwbEnable": False,
            "AwbMode": 0,
            "ColourTemperature": 100,
            "Saturation": 1.0,
            "CnnEnableInputTensor": False,
            "Brightness": 0.0,
            "Sharpness": 1.0
        }
        
        # Default GPIO settings
        self.gpio_settings = {
            "enableGPIO": False,
            "button": 0,
            "led": 0
        }
        
        # Create the live config
        self.live_config = {
            "controls": self.controls,
            "rotation": self.rotation_settings,
            "sensor-mode": 0,
            "capture-settings": self.capture_settings,
            "GPIO": self.gpio_settings
        }
        
        return self.live_config

    def config_from_file(self, file):
        newconfig = self.load_settings_from_file(file)
        print(f"\Setting New Config:\n {newconfig}\n")
        self.live_config = newconfig
        self.stop_streaming()
        self.live_config['capture-settings']['Encoder'] = self.live_config['capture-settings'].get("Encoder", "MJPEGEncoder")
        selected_resolution = self.live_config['capture-settings']['Resolution']
        resolution = self.output_resolutions[selected_resolution]
        mode = self.camera.sensor_modes[self.live_config['sensor-mode']]
        print(f'\nSensor Mode Config:\n{mode}\n')
        self.video_config = self.camera.create_video_configuration(main={'size':resolution}, sensor={'output_size': mode['size'], 'bit_depth': mode['bit_depth']})
        self.apply_rotation(self.live_config['rotation'])
        self.camera_info['Has_Config'] = True
        self.camera_info['Config_Location'] = file
        self.update_camera_last_config()
        self.setbutton()
        self.setled()
        self.start_streaming()
        self.configure_camera()

    def update_camera_last_config(self):
        global camera_last_config
        for cam in camera_last_config["cameras"]:
            if cam["Num"] == self.camera_info['Num']:
                cam["Has_Config"] = self.camera_info['Has_Config']
                cam["Config_Location"] = self.camera_info['Config_Location']
        with open(os.path.join(current_dir, 'camera-last-config.json'), 'w') as file:
            json.dump(camera_last_config, file, indent=4)

    def save_live_config(self, file):
        print(f'\Saving Live Config:\n{file}\n')
        self.live_config['Model'] = self.camera_info['Model']
        self.camera_info['Has_Config'] = True
        
        if not file.endswith(".json"):
            file += ".json"
        
        self.camera_info['Config_Location'] = file
        
        try:
            with open(os.path.join(CAMERA_CONFIG_FOLDER, file), 'w') as f:
                json.dump(self.live_config, f, indent=4)
            self.update_camera_last_config()
            return file  # Return the filename on success
        except Exception as e:
            print(f'\nAn error occurred:\n{e}\n')
            return None  # Return None or raise an exception on failure

    def update_live_config(self, data):
        try:
            # Initialize default return values
            success = False
            settings = {}
            
            # Update only the keys that are present in the data
            for key in data:
                if key in self.live_config['controls']:
                    try:
                        if key in ('AfMode', 'AeConstraintMode', 'AeExposureMode', 'AeFlickerMode', 'AeFlickerPeriod', 'AeMeteringMode', 'AfRange', 'AfSpeed', 'AwbMode', 'ExposureTime'):
                            self.live_config['controls'][key] = int(data[key])
                        elif key in ('Brightness', 'Contrast', 'Saturation', 'Sharpness', 'ExposureValue', 'LensPosition', 'AnalogueGain'):
                            self.live_config['controls'][key] = float(data[key])
                        elif key in ('AeEnable', 'AwbEnable', 'ScalerCrop'):
                            self.live_config['controls'][key] = data[key]
                        
                        success = True
                        settings = self.live_config['controls']
                        print(f'\nUpdated live setting:\n{settings}\n')
                        return success, settings
                    except Exception as e:
                        logging.error(f"Error updating control setting: {e}")
                        return False, {'error': str(e)}
                        
                elif key in self.live_config['capture-settings']:
                    try:
                        if key == 'Resolution':
                            self.live_config['capture-settings']['Resolution'] = int(data[key])
                            selected_resolution = int(data[key])
                            resolution = self.output_resolutions[selected_resolution]
                            mode = self.camera.sensor_modes[self.sensor_mode]
                            self.stop_streaming()
                            self.video_config = self.camera.create_video_configuration(main={'size':resolution}, sensor={'output_size': mode['size'], 'bit_depth': mode['bit_depth']})
                            self.camera.configure(self.video_config)
                            self.apply_rotation(self.live_config['rotation'])
                            self.start_streaming()
                        elif key == 'makeRaw':
                            self.live_config['capture-settings'][key] = data[key]
                        elif key == 'Encoder':
                            self.live_config['capture-settings'][key] = data[key]
                            self.stop_streaming()
                            time.sleep(1)
                            self.start_streaming()
                        
                        success = True
                        settings = self.live_config['capture-settings']
                        return success, settings
                    except Exception as e:
                        logging.error(f"Error updating capture setting: {e}")
                        return False, {'error': str(e)}
                        
                elif key in self.live_config['GPIO']:
                    try:
                        if key == 'button':
                            self.live_config['GPIO'][key] = int(data[key])
                            self.setbutton()
                        elif key == 'led':
                            self.live_config['GPIO'][key] = int(data[key])
                            self.setled()
                        elif key == 'enableGPIO':
                            self.live_config['GPIO'][key] = data[key]
                        
                        success = True
                        settings = self.live_config['GPIO']
                        return success, settings
                    except Exception as e:
                        logging.error(f"Error updating GPIO setting: {e}")
                        return False, {'error': str(e)}
                        
                elif key == 'sensor-mode':
                    try:
                        self.sensor_mode = sensor_mode = int(data[key])
                        selected_resolution = self.live_config['capture-settings']['Resolution']
                        resolution = self.output_resolutions[selected_resolution]
                        mode = self.camera.sensor_modes[self.sensor_mode]
                        self.live_config['sensor-mode'] = int(data[key])
                        self.stop_streaming()
                        
                        try:
                            self.video_config = self.camera.create_video_configuration(main={'size':resolution}, sensor={'output_size': mode['size'], 'bit_depth': mode['bit_depth']})
                            self.apply_rotation(self.live_config['rotation'])
                        except Exception as e:
                            logging.error("An error occurred while configuring the camera: %s", str(e))
                            print(f"\nAn error occurred:\n{str(e)}\n")
                            return False, {'error': str(e)}
                            
                        self.camera.configure(self.video_config)
                        print(f'\nVideo Config:\n{self.video_config}\n')
                        self.start_streaming()
                        success = True
                        settings = self.live_config['sensor-mode']
                        return success, settings
                    except Exception as e:
                        logging.error(f"Error updating sensor mode: {e}")
                        return False, {'error': str(e)}
            
            # If no matching key was found
            return False, {'error': 'No valid settings were updated'}
            
        except Exception as e:
            logging.error(f"Error in update_live_config: {e}")
            return False, {'error': str(e)}

    def apply_rotation(self,data):
        self.stop_streaming()
        transform = Transform()
        # Update settings that require a restart
        for key, value in data.items():
            if key in self.live_config['rotation']:
                if key in ('hflip', 'vflip'):
                    self.live_config['rotation'][key] = data[key]
                    setattr(transform, key, value) 
            self.video_config['transform'] = transform 
            self.camera.configure(self.video_config)
            time.sleep(0.5)
        self.start_streaming()
        success = True
        settings = self.live_config['rotation']
        return success, settings

    def take_snapshot(self,camera_num):
        try:
            image_name = f'snapshot/pimage_snapshot_{camera_num}'
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], image_name)
            request = self.camera.capture_request()
            request.save("main", f'{filepath}.jpg')
            logging.info(f"Image captured successfully. Path: {filepath}")
            return f'{filepath}.jpg'
        except Exception as e:
            logging.error(f"Error capturing image: {e}")
        
    def take_preview(self,camera_num):
        try:
            image_name = f'snapshot/pimage_preview_{camera_num}'
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], image_name)
            request = self.camera.capture_request()
            request.save("main", f'{filepath}.jpg')
            logging.info(f"Image captured successfully. Path: {filepath}")
            return f'{filepath}.jpg'
        except Exception as e:
            logging.error(f"Error capturing image: {e}")

    def start_recording_video(self):
        """Start recording video using libcamera-vid"""
        if self.recording and self.recording_process and self.recording_process.is_alive():
            print("DEBUG: Already recording")
            return False, "Already recording"
        
        try:
            # Clean up any stale state
            self.recording = False
            if self.recording_process:
                try:
                    self.recording_process.stop()
                except:
                    pass
            self.recording_process = None
            self.video_path = None
            
            # Create a unique filename with timestamp
            timestamp = int(datetime.timestamp(datetime.now()))
            video_name = f'video_cam_{self.camera_info["Num"]}_{timestamp}.mp4'
            self.video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_name)
            
            print(f"DEBUG: Recording to file: {self.video_path}")
            
            # Get current resolution
            selected_resolution = self.live_config['capture-settings']["Resolution"]
            resolution = self.output_resolutions[selected_resolution]
            width, height = resolution
            
            # Get rotation settings
            hflip = self.live_config['rotation'].get('hflip', 0) == 1
            vflip = self.live_config['rotation'].get('vflip', 0) == 1
            
            # Create a new recording process
            self.recording_process = LibcameraProcess(self.camera_info["Num"])
            
            # Start the recording process with MJPEG output to file
            success = self.recording_process.start(
                width=width,
                height=height,
                fps=frame_rate,
                output=self.video_path,
                codec="mjpeg",
                quality=90,  # Adjust quality as needed
                hflip=hflip,
                vflip=vflip,
                additional_args=[
                    "--segment", "0",  # Disable segmentation for recording
                    "--save-pts", "timestamps.txt"  # Save timestamps for debugging
                ]
            )
            
            if success:
                # Verify the process is running
                time.sleep(0.5)  # Give it a moment to start
                if self.recording_process.is_alive():
                    # Only set recording flag if process started successfully
                    self.recording = True
                    print(f"DEBUG: Started recording to {self.video_path}")
                    return True, video_name
                else:
                    print(f"DEBUG: Recording process started but died immediately")
                    self.recording_process = None
                    self.video_path = None
                    return False, "Recording process failed to start properly"
            else:
                print(f"DEBUG: Failed to start recording process")
                # Clean up on failure
                self.recording_process = None
                self.video_path = None
                return False, "Failed to start recording process"
                
        except Exception as e:
            print(f"DEBUG: Error starting video recording: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            # Clean up on error
            self.recording = False
            self.recording_process = None
            self.video_path = None
            return False, str(e)

    def stop_recording_video(self):
        try:
            print(f"DEBUG: stop_recording_video called - Current state: recording={self.recording}, process={self.recording_process is not None}")
            
            # Always attempt to stop any recording process, even if state is inconsistent
            video_path = self.video_path  # Store path before clearing
            process_stopped = False
            
            # Try to stop the recording process if it exists
            if self.recording_process is not None:
                print("DEBUG: Stopping recording process")
                try:
                    self.recording_process.stop()
                    process_stopped = True
                    # Give the filesystem a moment to finalize the file
                    time.sleep(0.5)
                except Exception as e:
                    print(f"DEBUG: Error stopping recording process: {e}")
                finally:
                    self.recording_process = None
            
            # Reset recording state
            self.recording = False
            
            # If we don't have a video path but we stopped a process, consider it a success
            if video_path is None and process_stopped:
                print("DEBUG: Recording process stopped, but no video path was set")
                self.video_path = None
                return True, "Recording stopped (no file produced)"
            
            # If we have a video path, check if the file exists
            if video_path:
                print(f"DEBUG: Checking for video file at: {video_path}")
                
                # Wait for the file to be fully written (up to 5 seconds)
                max_retries = 10
                retry_delay = 0.5
                file_exists = False
                file_size = 0
                
                for attempt in range(max_retries):
                    if os.path.exists(video_path):
                        file_exists = True
                        file_size = os.path.getsize(video_path)
                        print(f"DEBUG: Found file, size: {file_size} bytes (attempt {attempt + 1})")
                        
                        # If file has content, we can consider it valid
                        if file_size > 0:
                            # Wait a bit more to ensure it's fully written
                            time.sleep(retry_delay)
                            # Check if size is stable
                            new_size = os.path.getsize(video_path)
                            if new_size == file_size:
                                print(f"DEBUG: File size is stable at {file_size} bytes")
                                self.video_path = None
                                return True, video_path
                            else:
                                print(f"DEBUG: File size changed from {file_size} to {new_size} bytes")
                                file_size = new_size
                    else:
                        print(f"DEBUG: File not found (attempt {attempt + 1})")
                    
                    time.sleep(retry_delay)
                
                # If we get here, we couldn't find a stable file
                error_msg = "Recording file not found" if not file_exists else f"File exists but may be incomplete (size: {file_size} bytes)"
                print(f"DEBUG: {error_msg}")
                
                # If the file exists but is small, we'll still return it
                if file_exists and file_size > 0:
                    print(f"DEBUG: Returning potentially incomplete file")
                    self.video_path = None
                    return True, video_path
                
                self.video_path = None
                return False, error_msg
            
            # If we get here, we weren't recording and didn't stop anything
            if not process_stopped:
                print("DEBUG: Not recording - no process was stopped")
                return False, "Not recording"
            
            # Default case - we stopped something but don't have a file
            return True, "Recording stopped"
                
        except Exception as e:
            print(f"DEBUG: Error stopping video recording: {e}")
            import traceback
            print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
            # Make sure to clean up state even on error
            self.recording = False
            self.recording_process = None
            self.video_path = None
            return False, str(e)

    def is_recording(self):
        """Check if the camera is recording"""
        return self.recording and self.recording_process is not None and self.recording_process.is_alive()

# Init dictionary to store camera instances
cameras = {}
camera_new_config = {'cameras': []}
print(f'\nDetected Cameras:\n{global_cameras}\n')

# Iterate over each camera in the global_cameras list
for camera_info in global_cameras:
    # Flag to check if a matching camera is found in the last config
    matching_camera_found = False
    print(f'\nCamera Info:\n{camera_info}\n')

    # Get the number of the camera in the global_cameras list
    camera_num = camera_info['Num']

    # Check against last known config
    for camera_info_last in camera_last_config['cameras']:
        if (camera_info['Num'] == camera_info_last['Num'] and camera_info['Model'] == camera_info_last['Model']):
            print(f"\nDetected camera:\n{camera_info['Num']}: {camera_info['Model']} matched last used in config.\n")
            camera_new_config['cameras'].append(camera_info_last)
            matching_camera_found = True
            camera_info['Config_Location'] = camera_new_config['cameras'][camera_num]['Config_Location']
            camera_info['Has_Config'] = camera_new_config['cameras'][camera_num]['Has_Config']
            camera_obj = CameraObject(camera_num, camera_info)
            camera_obj.start_streaming()
            cameras[camera_num] = camera_obj
            break
    
    # If no matching camera found, check if it's a known Pi camera module
    if not matching_camera_found:
        is_pi_cam = False
        for camera_modules in camera_module_info['camera_modules']:
            if (camera_info['Model'] == camera_modules['sensor_model']):
                is_pi_cam = True
                print("\nCamera config has changed since last boot - Adding new Camera\n")
                add_camera_config = {'Num':camera_info['Num'], 'Model':camera_info['Model'], 'Is_Pi_Cam': is_pi_cam, 'Has_Config': False, 'Config_Location': f"default_{camera_info['Model']}.json"}
                camera_new_config['cameras'].append(add_camera_config)
                camera_info['Config_Location'] = camera_new_config['cameras'][camera_num]['Config_Location']
                camera_info['Has_Config'] = camera_new_config['cameras'][camera_num]['Has_Config']
                camera_obj = CameraObject(camera_num, camera_info)
                camera_obj.start_streaming()
                cameras[camera_num] = camera_obj
                break
        
        # If it's not a Pi camera or in the last config, add it anyway
        if not is_pi_cam:
            print("\nAdding a new unknown camera to the configuration\n")
            add_camera_config = {'Num':camera_info['Num'], 'Model':camera_info['Model'], 'Is_Pi_Cam': False, 'Has_Config': False, 'Config_Location': f"default_{camera_info['Model']}.json"}
            camera_new_config['cameras'].append(add_camera_config)
            camera_info['Config_Location'] = add_camera_config['Config_Location']
            camera_info['Has_Config'] = add_camera_config['Has_Config']
            camera_obj = CameraObject(camera_num, camera_info)
            camera_obj.start_streaming()
            cameras[camera_num] = camera_obj

# Print the new config for debug
print(f'\nCurrent detected compatible Cameras:\n{camera_new_config}\n')
# Write config to last config file for next reboot
camera_last_config = camera_new_config
with open(os.path.join(current_dir, 'camera-last-config.json'), 'w') as file:
    json.dump(camera_last_config, file, indent=4)



def get_camera_info(camera_model, camera_module_info):
    return next(
        (module for module in camera_module_info["camera_modules"] if module["sensor_model"] == camera_model),
        next(module for module in camera_module_info["camera_modules"] if module["sensor_model"] == "Unknown")
    )

####################
# Site Routes (routes to actual pages)
####################

@app.context_processor
def inject_theme():
    theme = session.get('theme', 'light')
    return {'theme': theme}

@app.context_processor
def inject_utility_functions():
    """Make utility functions available to all templates."""
    return {
        'enumerate': enumerate,
        'len': len,
        'str': str
    }

@app.route('/set_theme/<theme>')
def set_theme(theme):
    session['theme'] = theme
    return jsonify({'success': True})

# Define your 'home' route
@app.route('/')
def home():
    # Assuming cameras is a dictionary containing your CameraObjects
    cameras_data = [(camera_num, camera) for camera_num, camera in cameras.items()]
    camera_list = [(camera_num, camera, camera.camera_info['Model'], get_camera_info(camera.camera_info['Model'], camera_module_info)) for camera_num, camera in cameras.items()]
    return render_template('home.html', cameras_data=cameras_data, camera_list=camera_list, active_page='home')

@app.route('/control_camera_<int:camera_num>')
def control_camera(camera_num):
    print(f"\n{'='*50}")
    print(f"DEBUG: Entering control_camera route for camera {camera_num}")
    print(f"{'='*50}\n")
    
    try:
        # Get cameras data
        cameras_data = [(num, cam) for num, cam in cameras.items()]
        print(f"DEBUG: cameras_data: {[(num, cam.camera_info['Model']) for num, cam in cameras.items()]}")
        
        # Get camera list
        camera_list = [(num, cam, cam.camera_info['Model']) for num, cam in cameras.items()]
        print(f"DEBUG: camera_list: {[(num, cam.camera_info['Model'], model) for num, cam, model in camera_list]}")
        
        # Get camera object
        camera = cameras.get(camera_num)
        print(f"DEBUG: Retrieved camera object for camera {camera_num}: {'Found' if camera else 'Not Found'}")
        
        if camera is None:
            print("DEBUG: Camera not found, returning error template")
            return render_template('error.html', error="Camera not found", cameras_data=cameras_data, camera_list=camera_list)
        
        # Make sure to release any existing camera instance
        camera.release_camera()
        
        # Get settings from camera (use empty dict if not available)
        settings_from_camera = camera.settings or {}
        print(f"DEBUG: settings_from_camera keys: {list(settings_from_camera.keys()) if settings_from_camera else 'None'}")
        
        # Get live settings
        live_settings = camera.live_config.get('controls', {})
        print(f"DEBUG: live_settings keys: {list(live_settings.keys()) if live_settings else 'None'}")
        
        # Get rotation settings
        rotation_settings = camera.live_config.get('rotation', {})
        print(f"DEBUG: rotation_settings keys: {list(rotation_settings.keys()) if rotation_settings else 'None'}")
        
        # Get capture settings
        capture_settings = camera.live_config.get('capture-settings', {})
        print(f"DEBUG: capture_settings keys: {list(capture_settings.keys()) if capture_settings else 'None'}")
        
        # Get resolutions
        resolutions = camera.output_resolutions or {"0": (1456, 1088)}
        print(f"DEBUG: Number of resolutions: {len(resolutions)}")
        
        # Get frame rate
        frame_rate = capture_settings.get('FrameRate', 60)
        print(f"DEBUG: frame_rate: {frame_rate}")
        
        # Get camera info
        camera_info = camera.camera_info
        print(f"DEBUG: camera_info: {camera_info}")
        
        print("DEBUG: About to render template with all required variables")
        
        return render_template(
            'camerasettings.html',
            camera_num=camera_num,  # Add camera_num parameter
            settings_from_camera=settings_from_camera,
            live_settings=live_settings,
            rotation_settings=rotation_settings,
            capture_settings=capture_settings,
            resolutions=resolutions,
            frame_rate=frame_rate,
            cameras_data=cameras_data,
            camera_list=camera_list,
            camera_info=camera_info,
            active_page='camera_settings'
        )
    except Exception as e:
        print(f"DEBUG: Error in control_camera route: {e}")
        import traceback
        print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
        return render_template('error.html', error=str(e), cameras_data=cameras_data, camera_list=camera_list)

@app.route("/beta")
def beta():
    return render_template("beta.html", title="beta")

@app.route("/camera_info_<int:camera_num>")
def camera_info(camera_num):
    # Assuming cameras is a dictionary containing your CameraObjects
    cameras_data = [(camera_num, camera) for camera_num, camera in cameras.items()]
    camera_list = [(camera_num, camera, camera.camera_info['Model']) for camera_num, camera in cameras.items()]
    try:
        camera = cameras.get(camera_num)
        if camera is None:
            return render_template('error.html', error="Camera not found", cameras_data=cameras_data, camera_list=camera_list)
        
        # Get camera info
        camera_info = camera.camera_info
        sensor_modes = camera.sensor_modes
        
        return render_template('camera_info.html', 
                              camera_num=camera_num, 
                              camera_info=camera_info, 
                              sensor_modes=sensor_modes,
                              cameras_data=cameras_data, 
                              camera_list=camera_list,
                              active_page='camera_info')
    except Exception as e:
        logging.error(f"Error loading camera info: {e}")
        return render_template('error.html', error=str(e), cameras_data=cameras_data, camera_list=camera_list)

@app.route('/reset_default_settings_camera_<int:camera_num>', methods=['GET'])
def reset_default_settings_camera(camera_num):
    try:
        camera = cameras.get(camera_num)
        camera.default_camera_settings()
        resolutions = camera.available_resolutions()
        response_data = {
        'live_settings': camera.live_config.get('controls'),
        'rotation_settings': camera.live_config.get('rotation')
        }
        print(f"DEBUG: reset_default_settings_camera - Response data: {response_data}")
        return jsonify(response_data)
    except Exception as e:
        print(f"DEBUG: reset_default_settings_camera - Error: {str(e)}")
        return jsonify(error=str(e))

@app.route('/get_file_settings_camera_<int:camera_num>', methods=['POST'])
def get_file_settings_camera(camera_num):
    try:
        # Parse JSON data from the request
        filename = request.get_json().get('filename')
        camera = cameras.get(camera_num)
        if not camera:
            return jsonify(success=False, error="Camera not found.")
        
        camera.config_from_file(filename)
        resolutions = camera.available_resolutions()
        response_data = {
            'live_settings': camera.live_config.get('controls'),
            'rotation_settings': camera.live_config.get('rotation'),
            'capture_settings': camera.live_config.get('capture-settings'), 
            'resolutions': camera.available_resolutions(),
            'success': True
        }
        return jsonify(response_data)
    except Exception as e:
        return jsonify(success=False, error=str(e))

@app.route('/save_config_file_camera_<int:camera_num>', methods=['POST'])
def save_config_file(camera_num):
    try:
        # Fetch the filename from the request
        filename = request.get_json().get('filename')
        print(f'\nReceived filename:\n{filename}\n')
        
        # Fetch the camera object from the global 'cameras' dictionary
        camera = cameras.get(camera_num)
        if not camera:
            raise ValueError(f'\nCamera with number {camera_num} not found\n')
        
        # Call the save_live_config method on the camera object
        response_data = camera.save_live_config(filename)
        if response_data is not None:
            print(f'\nSaved config data:\n{response_data}\n')
            # Return the success response with the filename and model
            return jsonify(success=True, filename=response_data, model=camera.camera_info['Model'])
        else:
            return jsonify(success=False, error="Failed to save config file")
    except Exception as e:
        # Log the error and return an error response
        print(f'\nERROR:\n{e}\n')
        return jsonify(success=False, error=str(e))

@app.route('/capture_photo_<int:camera_num>', methods=['POST'])
def capture_photo(camera_num):
    try:
        cameras_data = [(camera_num, camera) for camera_num, camera in cameras.items()]
        camera = cameras.get(camera_num)
        camera.take_photo()  # Call your take_photo function
        time.sleep(1)
        return jsonify(success=True, message="Photo captured successfully")
    except Exception as e:
        return jsonify(success=False, message=str(e))

@app.route("/about")
def about():
    cameras_data = [(camera_num, camera) for camera_num, camera in cameras.items()]
    camera_list = [(camera_num, camera, camera.camera_info['Model'], get_camera_info(camera.camera_info['Model'], camera_module_info)) for camera_num, camera in cameras.items()]
    # Pass cameras_data as a context variable to your template
    return render_template("about.html", title="About Picamera2 WebUI", cameras_data=cameras_data, camera_list=camera_list, active_page='about')

def direct_camera_stream(camera_num, width=1456, height=1088, fps=30):
    """Stream directly from the camera using a subprocess call to libcamera-vid"""
    print(f"DEBUG: Starting direct camera stream for camera {camera_num}")
    
    # Make sure to release any Picamera2 instances
    if camera_num in cameras:
        cameras[camera_num].release_camera()
    
    # Kill any existing libcamera processes
    try:
        print("DEBUG: Killing any existing libcamera processes")
        subprocess.run(["pkill", "-f", "libcamera"], stderr=subprocess.DEVNULL)
        time.sleep(0.1)  # Reduced wait time
    except Exception as e:
        print(f"DEBUG: Error killing processes: {e}")
    
    # Build the command with optimized parameters
    cmd = [
        "libcamera-vid",
        "--width", str(width),
        "--height", str(height),
        "--framerate", str(fps),
        "--codec", "mjpeg",
        "--quality", "50",
        "--inline",
        "--timeout", "0",
        "--nopreview",
        "--buffer-count", "2",
        "--flush", "1",
        "--output", "-"
    ]
    
    if camera_num > 0:
        cmd.extend(["--camera", str(camera_num)])
    
    print(f"DEBUG: Running command: {' '.join(cmd)}")
    
    # Start the process with optimized buffer size
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=4096  # Small buffer size for lower latency
        )
        
        # Check if process started successfully
        time.sleep(0.1)  # Brief wait
        if process.poll() is not None:
            stderr = process.stderr.read().decode()
            print(f"DEBUG: Process failed to start: {stderr}")
            return None
        
        print("DEBUG: Process started successfully")
        return process
    except Exception as e:
        print(f"DEBUG: Error starting process: {e}")
        import traceback
        print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
        return None

def generate_direct_stream(process):
    """Generate a stream from a subprocess"""
    print("DEBUG: Starting generate_direct_stream")
    
    if not process:
        print("DEBUG: No process provided")
        return
    
    try:
        # Buffer for JPEG data
        buffer = bytearray()
        jpeg_start = b'\xff\xd8'
        jpeg_end = b'\xff\xd9'
        
        while True:
            try:
                # Read data from the process
                chunk = process.stdout.read1(4096)
                
                if not chunk:
                    print("DEBUG: End of stream or no data")
                    if process.poll() is not None:
                        print("DEBUG: Process has terminated")
                        break
                    continue
                
                # Add chunk to buffer
                buffer.extend(chunk)
                
                # Process all complete frames in buffer
                while len(buffer) > 0:
                    # Find start marker
                    start_idx = buffer.find(jpeg_start)
                    if start_idx < 0:
                        # No start marker found, clear buffer
                        buffer.clear()
                        break
                    
                    # Remove any data before the start marker
                    if start_idx > 0:
                        buffer = buffer[start_idx:]
                        start_idx = 0
                    
                    # Find end marker
                    end_idx = buffer.find(jpeg_end, start_idx + 2)
                    if end_idx < 0:
                        # No end marker found, wait for more data
                        break
                    
                    # Extract the frame
                    frame = buffer[:end_idx + 2]
                    
                    # Remove the frame from buffer
                    buffer = buffer[end_idx + 2:]
                    
                    # Yield the frame
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                
                # Prevent buffer from growing too large
                if len(buffer) > 512 * 1024:  # 512KB limit
                    print("DEBUG: Buffer too large, clearing")
                    buffer.clear()
                    
            except IOError as e:
                print(f"DEBUG: IOError in generate_direct_stream: {e}")
                if process.poll() is not None:
                    break
                continue
                
    except Exception as e:
        print(f"DEBUG: Error in generate_direct_stream: {e}")
        import traceback
        print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
    finally:
        # Clean up
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except:
                process.kill()
            print("DEBUG: Process terminated")

@app.route('/video_feed_<int:camera_num>')
def video_feed(camera_num):
    """Route for streaming video from a camera"""
    print(f"DEBUG: Video feed requested for camera {camera_num}")
    
    # Check if camera exists
    if camera_num not in cameras:
        print(f"DEBUG: Camera {camera_num} not found")
        return "Camera not found", 404
    
    # Get camera settings
    camera = cameras[camera_num]
    width = 1456
    height = 1088
    fps = 30
    
    try:
        # Try to get settings from camera
        if hasattr(camera, 'live_config'):
            fps = camera.live_config.get('capture-settings', {}).get("FrameRate", 30)
            selected_resolution = camera.live_config.get('capture-settings', {}).get("Resolution", "1456x1088")
            if hasattr(camera, 'output_resolutions') and selected_resolution in camera.output_resolutions:
                width, height = camera.output_resolutions[selected_resolution]
    except Exception as e:
        print(f"DEBUG: Error getting camera settings: {e}")
    
    # Start direct camera stream
    process = direct_camera_stream(camera_num, width, height, fps)
    
    if not process:
        print("DEBUG: Failed to start camera stream")
        return "Failed to start camera stream", 500
    
    print("DEBUG: Starting video feed stream")
    
    try:
        return Response(generate_direct_stream(process),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    except Exception as e:
        print(f"DEBUG: Error in video_feed: {e}")
        import traceback
        print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
        return f"Error: {str(e)}", 500

@app.route('/snapshot_<int:camera_num>')
def snapshot(camera_num):
    camera = cameras.get(camera_num)
    if camera:
        # Capture an image
        filepath = camera.take_snapshot(camera_num)
        # Wait for a few seconds to ensure the image is saved
        time.sleep(1)
        return send_file(filepath, as_attachment=False, download_name="snapshot.jpg",  mimetype='image/jpeg')
    else:
        abort(404)

@app.route('/preview_<int:camera_num>', methods=['POST'])
def preview(camera_num):
    try:
        camera = cameras.get(camera_num)
        if camera:
            # Capture an image
            filepath = camera.take_preview(camera_num)
            # Wait for a few seconds to ensure the image is saved
            time.sleep(1)
            return jsonify(success=True, message="Photo captured successfully")
    except Exception as e:
        return jsonify(success=False, message=str(e))

####################
# POST routes for saving data
####################

# Route to update settings to the buffer
@app.route('/update_live_settings_<int:camera_num>', methods=['POST'])
def update_settings(camera_num):
    cameras_data = [(camera_num, camera) for camera_num, camera in cameras.items()]
    camera = cameras.get(camera_num)
    try:
        # Parse JSON data from the request
        data = request.get_json()
        success, settings = camera.update_live_config(data)
        if success:
            camera.configure_camera()
        return jsonify(success=success, message="Settings updated successfully", settings=settings)
    except Exception as e:
        return jsonify(success=False, message=str(e))

@app.route('/update_restart_settings_<int:camera_num>', methods=['POST'])
def update_restart_settings(camera_num):
    if camera_num not in cameras:
        return jsonify({'success': False, 'message': 'Camera not found'}), 404
    
    try:
        data = request.json
        print(f'\nReceived data: {data}\n')
        
        # Check if we need to update capture settings
        if 'capture-settings' in data:
            # Update capture settings
            cameras[camera_num].live_config['capture-settings'].update(data['capture-settings'])
            
            # If frame rate or resolution is changed, we need to restart streaming
            if 'FrameRate' in data['capture-settings'] or 'Resolution' in data['capture-settings']:
                # Stop streaming
                cameras[camera_num].stop_streaming()
                
                # Start streaming again with new settings
                cameras[camera_num].start_streaming()
                
                print(f'\nRestarted streaming with updated settings\n')
        
        # Handle rotation settings
        if 'hflip' in data or 'vflip' in data:
            # Update rotation settings
            if 'hflip' in data:
                cameras[camera_num].live_config['rotation']['hflip'] = data['hflip']
            if 'vflip' in data:
                cameras[camera_num].live_config['rotation']['vflip'] = data['vflip']
            
            # Restart streaming with new rotation settings
            cameras[camera_num].stop_streaming()
            cameras[camera_num].start_streaming()
            
            print(f'\nRestarted streaming with updated rotation settings\n')
        
        success = True
        settings = cameras[camera_num].live_config['rotation']
        return jsonify({'success': success, 'settings': settings})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/start_recording_<int:camera_num>', methods=['POST'])
def start_recording(camera_num):
    if camera_num not in cameras:
        return jsonify({'success': False, 'message': 'Camera not found'}), 404
    
    success, result = cameras[camera_num].start_recording_video()
    
    if success:
        return jsonify({'success': True, 'message': 'Recording started', 'filename': result})
    else:
        return jsonify({'success': False, 'message': f'Failed to start recording: {result}'})

@app.route('/stop_recording_<int:camera_num>', methods=['POST'])
def stop_recording(camera_num):
    if camera_num not in cameras:
        return jsonify({'success': False, 'message': 'Camera not found'}), 404
    
    success, video_path = cameras[camera_num].stop_recording_video()
    
    if success:
        # Extract just the filename from the path
        video_filename = os.path.basename(video_path)
        return jsonify({'success': True, 'message': 'Recording stopped', 'filename': video_filename})
    else:
        return jsonify({'success': False, 'message': f'Failed to stop recording: {video_path}'})

@app.route('/download_video/<filename>', methods=['GET'])
def download_video(filename):
    try:
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        print(f"DEBUG: Attempting to download video from: {video_path}")
        
        # Check if the file exists
        if not os.path.exists(video_path):
            print(f"DEBUG: Video file not found at: {video_path}")
            return jsonify({
                'success': False, 
                'message': f'Video file not found: {filename}'
            }), 404
            
        # Check if the file is empty
        if os.path.getsize(video_path) == 0:
            print(f"DEBUG: Video file is empty: {video_path}")
            return jsonify({
                'success': False, 
                'message': 'Video file is empty'
            }), 400
            
        print(f"DEBUG: Sending video file: {filename}, size: {os.path.getsize(video_path)} bytes")
        
        # Set the correct MIME type for MJPEG files
        if filename.endswith('.mjpeg'):
            return send_file(
                video_path,
                mimetype='video/x-mjpeg',
                as_attachment=True,
                download_name=filename
            )
        else:
            # For other video formats
            return send_file(
                video_path,
                as_attachment=True,
                download_name=filename
            )
    except Exception as e:
        print(f"DEBUG: Error downloading video: {e}")
        import traceback
        print(f"DEBUG: Traceback:\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'Error downloading video: {str(e)}'
        }), 500

@app.route('/check_recording_status_<int:camera_num>', methods=['GET'])
def check_recording_status(camera_num):
    if camera_num not in cameras:
        print("DEBUG: check_recording_status - Camera not found response")
        return jsonify({'recording': False, 'message': 'Camera not found'}), 404
    
    try:
        is_recording = bool(cameras[camera_num].is_recording())
        print(f"DEBUG: check_recording_status - Response data: {{'recording': {is_recording}}}")
        return jsonify({'recording': is_recording})
    except Exception as e:
        print(f"DEBUG: check_recording_status - Error: {str(e)}")
        return jsonify({'recording': False, 'error': str(e)})

@app.route('/get_fps_<int:camera_num>', methods=['GET'])
def get_fps(camera_num):
    print(f"DEBUG: get_fps called for camera {camera_num}")
    if camera_num not in cameras:
        print("DEBUG: get_fps - Camera not found response")
        return jsonify({'success': False, 'message': 'Camera not found'}), 404
    
    try:
        camera = cameras[camera_num]
        # Get current resolution
        selected_resolution = camera.live_config.get('capture-settings', {}).get("Resolution", "0")
        width, height = camera.output_resolutions.get(selected_resolution, (1456, 1088))
        
        # Get the actual measurements from the output handler
        if hasattr(camera, 'output') and camera.output:
            actual_fps = camera.output.get_current_fps()
            actual_latency = camera.output.get_current_latency()
            print(f"DEBUG: get_fps - Actual FPS: {actual_fps}, Latency: {actual_latency:.1f}ms")
        else:
            actual_fps = 0.0
            actual_latency = 0.0
            print("DEBUG: get_fps - No output handler available")
        
        return jsonify({
            'success': True,
            'fps': actual_fps,
            'target_fps': camera.live_config.get('capture-settings', {}).get("FrameRate", 30),
            'width': width,
            'height': height,
            'latency': actual_latency
        })
    except Exception as e:
        print(f"DEBUG: get_fps - Error: {str(e)}")
        import traceback
        print(f"DEBUG: get_fps - Traceback:\n{traceback.format_exc()}")
        return jsonify({'success': False, 'fps': 0, 'error': str(e)})

####################
# Image Gallery Functions
####################

@app.route('/image_gallery')
def image_gallery():
    # Assuming cameras is a dictionary containing your CameraObjects
    cameras_data = [(camera_num, camera) for camera_num, camera in cameras.items()]
    camera_list = [(camera_num, camera, camera.camera_info['Model']) for camera_num, camera in cameras.items()]
    
    try:
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)
        
        # Get all image files
        image_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.jpg')]
        
        # Get all video files (both MP4 and MJPEG)
        video_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.mp4') or f.endswith('.mjpeg')]
        
        # Sort files by creation time (newest first)
        image_files.sort(key=lambda x: os.path.getctime(os.path.join(UPLOAD_FOLDER, x)), reverse=True)
        video_files.sort(key=lambda x: os.path.getctime(os.path.join(UPLOAD_FOLDER, x)), reverse=True)
        
        # If there are no files, render a special template
        if not image_files and not video_files:
            return render_template('no_files.html', cameras_data=cameras_data, camera_list=camera_list)
        
        # Create a list of dictionaries with image information
        images_info = []
        for image_file in image_files:
            # Check if there's a corresponding .dng file
            dng_file = image_file.replace('.jpg', '.dng')
            has_dng = os.path.exists(os.path.join(UPLOAD_FOLDER, dng_file))

            # Get image dimensions
            img = Image.open(os.path.join(UPLOAD_FOLDER, image_file))
            width, height = img.size
            
            # Get file creation time
            creation_time = datetime.fromtimestamp(os.path.getctime(os.path.join(UPLOAD_FOLDER, image_file)))
            
            # Add image info to the list
            images_info.append({
                'filename': image_file,
                'width': width,
                'height': height,
                'has_dng': has_dng,
                'creation_time': creation_time,
                'type': 'image'
            })
        
        # Create a list of dictionaries with video information
        videos_info = []
        for video_file in video_files:
            # Get file creation time
            creation_time = datetime.fromtimestamp(os.path.getctime(os.path.join(UPLOAD_FOLDER, video_file)))
            
            # Determine video type
            video_type = 'mjpeg' if video_file.endswith('.mjpeg') else 'mp4'
            
            # Add video info to the list
            videos_info.append({
                'filename': video_file,
                'creation_time': creation_time,
                'type': 'video',
                'format': video_type
            })
        
        # Combine and sort all media by creation time
        all_media = images_info + videos_info
        all_media.sort(key=lambda x: x['creation_time'], reverse=True)
        
        return render_template('image_gallery.html', media=all_media, cameras_data=cameras_data, camera_list=camera_list, active_page='image_gallery')
    except Exception as e:
        logging.error(f"Error loading image gallery: {e}")
        return render_template('error.html', error=str(e), cameras_data=cameras_data, camera_list=camera_list)

@app.route('/delete_image/<filename>', methods=['DELETE'])
def delete_image(filename):
    try:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Check if the file exists
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'message': 'File not found'})
        
        # Delete the file
        os.remove(filepath)
        
        # If it's an image, also delete the corresponding DNG file if it exists
        if filename.endswith('.jpg'):
            dng_file = filename.replace('.jpg', '.dng')
            dng_filepath = os.path.join(app.config['UPLOAD_FOLDER'], dng_file)
            if os.path.exists(dng_filepath):
                os.remove(dng_filepath)
        
        return jsonify({'success': True, 'message': 'File deleted successfully'})
    except Exception as e:
        logging.error(f"Error deleting file: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/view_image/<filename>', methods=['GET'])
def view_image(filename):
    # Assuming cameras is a dictionary containing your CameraObjects
    cameras_data = [(camera_num, camera) for camera_num, camera in cameras.items()]
    camera_list = [(camera_num, camera, camera.camera_info['Model']) for camera_num, camera in cameras.items()]
    
    try:
        # Check if the file exists
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(image_path):
            return render_template('error.html', error=f"Image not found: {filename}", cameras_data=cameras_data, camera_list=camera_list)
        
        # Check if there's a corresponding .dng file
        dng_file = filename.replace('.jpg', '.dng')
        has_dng = os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], dng_file))
        
        # Get image dimensions
        img = Image.open(image_path)
        width, height = img.size
        
        # Get file creation time
        creation_time = datetime.fromtimestamp(os.path.getctime(image_path))
        
        return render_template('view_image.html', 
                              filename=filename, 
                              width=width, 
                              height=height, 
                              has_dng=has_dng,
                              creation_time=creation_time,
                              cameras_data=cameras_data, 
                              camera_list=camera_list,
                              active_page='image_gallery')
    except Exception as e:
        logging.error(f"Error viewing image: {e}")
        return render_template('error.html', error=str(e), cameras_data=cameras_data, camera_list=camera_list)

@app.route('/download_image/<filename>', methods=['GET'])
def download_image(filename):
    try:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        return send_file(image_path, as_attachment=True)
    except Exception as e:
        print(f"\nError downloading image:\n{e}\n")
        abort(500)

if __name__ == "__main__":
    # Parse any argument passed from command line
    parser = argparse.ArgumentParser(description='PiCamera2 WebUI')
    parser.add_argument('--port', type=int, default=8080, help='Port number to run the web server on')
    parser.add_argument('--ip', type=str, default='0.0.0.0', help='IP to which the web server is bound to')
    args = parser.parse_args()
    
    app.run(host=args.ip, port=args.port)
