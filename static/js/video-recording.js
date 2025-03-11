// Video recording functionality
let recordingInterval;
let recordingStartTime;
let currentCameraNum;
let isRecording = false;
let recordingCanvas = null;
let recordingContext = null;
let frameCapture = null;
let recordedFrames = [];
let lastFrameTime = 0;
let targetFrameInterval = 1000 / 60; // 60 FPS

// FPS calculation variables
let frameCount = 0;
let fps = 0;
let fpsUpdateInterval;

// Initialize recording functionality
document.addEventListener('DOMContentLoaded', function() {
    // Get camera number from URL
    const urlPath = window.location.pathname;
    const match = urlPath.match(/control_camera_(\d+)/);
    if (match) {
        currentCameraNum = match[1];
        checkRecordingStatus();
        
        // Initialize FPS counter
        initFpsCounter();
        
        // Initialize video recording
        initVideoRecording();
    }
});

// Initialize FPS counter
function initFpsCounter() {
    // Create FPS display element if it doesn't exist
    if (!document.getElementById('cameraInfoContainer')) {
        const cameraImage = document.getElementById('cameraImage');
        const cameraContainer = document.querySelector('.camera-container');
        
        if (cameraImage && cameraContainer) {
            // Create container for FPS counter and info
            const infoContainer = document.createElement('div');
            infoContainer.id = 'cameraInfoContainer';
            infoContainer.style.position = 'absolute';
            infoContainer.style.top = '10px';
            infoContainer.style.right = '10px';
            infoContainer.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
            infoContainer.style.color = 'white';
            infoContainer.style.padding = '8px 12px';
            infoContainer.style.borderRadius = '4px';
            infoContainer.style.fontSize = '14px';
            infoContainer.style.fontWeight = 'bold';
            infoContainer.style.zIndex = '1000';
            infoContainer.style.boxShadow = '0 2px 5px rgba(0,0,0,0.3)';
            infoContainer.style.minWidth = '120px';
            infoContainer.style.textAlign = 'right';
            
            // Create FPS counter text with label
            const fpsWrapper = document.createElement('div');
            fpsWrapper.style.display = 'flex';
            fpsWrapper.style.justifyContent = 'space-between';
            
            const fpsLabel = document.createElement('span');
            fpsLabel.textContent = 'FPS:';
            fpsLabel.style.opacity = '0.8';
            
            const fpsCounter = document.createElement('span');
            fpsCounter.id = 'fpsCounter';
            fpsCounter.textContent = '0';
            
            fpsWrapper.appendChild(fpsLabel);
            fpsWrapper.appendChild(fpsCounter);
            
            // Create resolution display with label
            const resWrapper = document.createElement('div');
            resWrapper.style.display = 'flex';
            resWrapper.style.justifyContent = 'space-between';
            resWrapper.style.marginTop = '4px';
            resWrapper.style.fontSize = '12px';
            
            const resLabel = document.createElement('span');
            resLabel.textContent = 'Resolution:';
            resLabel.style.opacity = '0.8';
            
            const resolutionDisplay = document.createElement('span');
            resolutionDisplay.id = 'resolutionDisplay';
            resolutionDisplay.textContent = '--';
            
            resWrapper.appendChild(resLabel);
            resWrapper.appendChild(resolutionDisplay);
            
            // Create latency display with label
            const latencyWrapper = document.createElement('div');
            latencyWrapper.style.display = 'flex';
            latencyWrapper.style.justifyContent = 'space-between';
            latencyWrapper.style.marginTop = '4px';
            latencyWrapper.style.fontSize = '12px';
            
            const latencyLabel = document.createElement('span');
            latencyLabel.textContent = 'Latency:';
            latencyLabel.style.opacity = '0.8';
            
            const latencyDisplay = document.createElement('span');
            latencyDisplay.id = 'latencyDisplay';
            latencyDisplay.textContent = '--';
            
            latencyWrapper.appendChild(latencyLabel);
            latencyWrapper.appendChild(latencyDisplay);
            
            // Create recording indicator
            const recIndicator = document.createElement('div');
            recIndicator.id = 'recordingIndicator';
            recIndicator.style.display = 'none';
            recIndicator.style.marginTop = '4px';
            recIndicator.style.color = '#ff4d4d';
            recIndicator.style.fontWeight = 'bold';
            recIndicator.textContent = '● REC';
            
            infoContainer.appendChild(fpsWrapper);
            infoContainer.appendChild(resWrapper);
            infoContainer.appendChild(latencyWrapper);
            infoContainer.appendChild(recIndicator);
            
            // Add container to the camera container
            cameraContainer.appendChild(infoContainer);
            
            // Update FPS display every second
            fpsUpdateInterval = setInterval(fetchAndUpdateFps, 1000);
        }
    }
}

// Fetch FPS from server and update display
function fetchAndUpdateFps() {
    fetch(`/get_fps_${currentCameraNum}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data && data.success) {
                updateCameraInfo(data);
            } else if (data && data.message) {
                console.warn('Server warning:', data.message);
            }
        })
        .catch(error => {
            console.error('Error fetching FPS:', error);
            // Clear the update interval if we get too many errors
            if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
                console.warn('Network error detected, stopping FPS updates');
                if (fpsUpdateInterval) {
                    clearInterval(fpsUpdateInterval);
                    fpsUpdateInterval = null;
                }
            }
        });
}

// Update the camera information display
function updateCameraInfo(data) {
    const fpsCounter = document.getElementById('fpsCounter');
    const resolutionDisplay = document.getElementById('resolutionDisplay');
    const recIndicator = document.getElementById('recordingIndicator');
    const latencyDisplay = document.getElementById('latencyDisplay');
    
    if (fpsCounter && typeof data.fps !== 'undefined') {
        // Update FPS with target FPS
        const currentFps = Math.round(data.fps || 0);
        const targetFps = data.target_fps || 60;
        fpsCounter.textContent = `${currentFps} / ${targetFps} FPS`;
        
        // Change color based on FPS ratio
        const fpsRatio = currentFps / targetFps;
        if (fpsRatio < 0.5) {
            fpsCounter.style.color = '#ff4d4d'; // Red for very low FPS
        } else if (fpsRatio < 0.8) {
            fpsCounter.style.color = '#ffcc00'; // Yellow for medium FPS
        } else {
            fpsCounter.style.color = '#66ff66'; // Green for good FPS
        }
    }
    
    if (resolutionDisplay && typeof data.width !== 'undefined' && typeof data.height !== 'undefined') {
        // Update resolution
        const width = data.width || 0;
        const height = data.height || 0;
        resolutionDisplay.textContent = `${width}x${height}`;
    }
    
    if (latencyDisplay && typeof data.latency !== 'undefined') {
        // Update latency
        const latency = data.latency || 0;
        latencyDisplay.textContent = `${latency.toFixed(1)}ms`;
        
        // Change color based on latency
        if (latency > 100) {
            latencyDisplay.style.color = '#ff4d4d'; // Red for high latency
        } else if (latency > 50) {
            latencyDisplay.style.color = '#ffcc00'; // Yellow for medium latency
        } else {
            latencyDisplay.style.color = '#66ff66'; // Green for low latency
        }
    }
    
    if (recIndicator && typeof data.recording !== 'undefined') {
        // Show/hide recording indicator
        if (data.recording) {
            recIndicator.style.display = 'block';
            
            // Add blinking effect
            if (!recIndicator.classList.contains('blink')) {
                recIndicator.classList.add('blink');
                
                // Add blink animation if not already in document
                if (!document.getElementById('blinkStyle')) {
                    const style = document.createElement('style');
                    style.id = 'blinkStyle';
                    style.textContent = `
                        @keyframes blink {
                            0% { opacity: 1; }
                            50% { opacity: 0.3; }
                            100% { opacity: 1; }
                        }
                        .blink {
                            animation: blink 1.5s infinite;
                        }
                    `;
                    document.head.appendChild(style);
                }
            }
        } else {
            recIndicator.style.display = 'none';
            recIndicator.classList.remove('blink');
        }
    }
}

// Check if camera is already recording
function checkRecordingStatus() {
    fetch(`/check_recording_status_${currentCameraNum}`)
        .then(response => response.json())
        .then(data => {
            if (data.recording) {
                // Camera is already recording, update UI
                updateUIForRecording(true);
            }
        })
        .catch(error => {
            console.error('Error checking recording status:', error);
        });
}

// Initialize video recording
function initVideoRecording() {
    // Create a canvas element for frame capture
    recordingCanvas = document.createElement('canvas');
    recordingCanvas.style.display = 'none';
    document.body.appendChild(recordingCanvas);
    recordingContext = recordingCanvas.getContext('2d');
    
    // Get the image element that shows the camera feed
    const cameraImage = document.getElementById('cameraImage');
    if (!cameraImage) return;
    
    // Set initial canvas size
    recordingCanvas.width = cameraImage.naturalWidth || 1456;  // Default width if not set
    recordingCanvas.height = cameraImage.naturalHeight || 1088; // Default height if not set
    
    // Update canvas size when image loads
    cameraImage.onload = function() {
        if (cameraImage.naturalWidth && cameraImage.naturalHeight) {
            recordingCanvas.width = cameraImage.naturalWidth;
            recordingCanvas.height = cameraImage.naturalHeight;
        }
    };
    
    // Set up frame capture
    frameCapture = function() {
        if (isRecording && cameraImage.complete && cameraImage.naturalWidth !== 0) {
            const now = performance.now();
            if (now - lastFrameTime >= targetFrameInterval) {
                try {
                    // Draw frame to canvas
                    recordingContext.drawImage(cameraImage, 0, 0, recordingCanvas.width, recordingCanvas.height);
                    
                    // Get frame data directly as a data URL (synchronous)
                    const frameData = recordingCanvas.toDataURL('image/jpeg', 0.9);
                    // Convert base64 to blob synchronously
                    const byteString = atob(frameData.split(',')[1]);
                    const mimeString = frameData.split(',')[0].split(':')[1].split(';')[0];
                    const ab = new ArrayBuffer(byteString.length);
                    const ia = new Uint8Array(ab);
                    for (let i = 0; i < byteString.length; i++) {
                        ia[i] = byteString.charCodeAt(i);
                    }
                    const blob = new Blob([ab], {type: mimeString});
                    recordedFrames.push(blob);
                    
                    lastFrameTime = now;
                } catch (e) {
                    console.error('Error capturing frame:', e);
                }
            }
        }
    };
}

// Start video recording
function startRecording() {
    if (isRecording) {
        showRecordingAlert('Already recording.', 'warning');
        return;
    }
    
    try {
        // Clear any previous recording frames
        recordedFrames = [];
        lastFrameTime = performance.now();
        
        // Start recording
        isRecording = true;
        
        // Start frame capture loop
        requestAnimationFrame(captureFrames);
        
        // Update UI
        updateUIForRecording(true);
        showRecordingAlert('Recording started successfully', 'success');
        
        // Start recording timer
        recordingStartTime = new Date();
        recordingInterval = setInterval(updateRecordingTime, 1000);
        
    } catch (e) {
        console.error('Error starting recording:', e);
        showRecordingAlert('Error starting recording: ' + e.message, 'danger');
        isRecording = false;
    }
}

// Frame capture loop
function captureFrames() {
    if (isRecording) {
        frameCapture();
        requestAnimationFrame(captureFrames);
    }
}

// Stop video recording
function stopRecording() {
    if (!isRecording) {
        showRecordingAlert('No active recording to stop.', 'warning');
        return;
    }
    
    try {
        isRecording = false;
        
        // Create timestamp for filename
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const filename = `video_cam_${currentCameraNum}_${timestamp}.mjpeg`;
        
        // Create a single blob with all frames
        if (recordedFrames.length > 0) {
            console.log(`Captured ${recordedFrames.length} frames`);
            const recordingDuration = (performance.now() - recordingStartTime) / 1000;
            const actualFps = recordedFrames.length / recordingDuration;
            console.log(`Recording duration: ${recordingDuration.toFixed(2)}s, Actual FPS: ${actualFps.toFixed(2)}`);
            
            const blob = new Blob(recordedFrames, { type: 'image/jpeg' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            document.body.appendChild(a);
            a.style.display = 'none';
            a.href = url;
            a.download = filename;
            a.click();
            
            setTimeout(() => {
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                recordedFrames = []; // Clear frames
            }, 100);
            
            showRecordingAlert(`Recording saved successfully (${actualFps.toFixed(1)} FPS)`, 'success');
        } else {
            showRecordingAlert('Error: No frames were captured', 'danger');
        }
        
        // Update UI
        updateUIForRecording(false);
        
        // Stop recording timer
        clearInterval(recordingInterval);
        
    } catch (e) {
        console.error('Error stopping recording:', e);
        showRecordingAlert('Error stopping recording: ' + e.message, 'danger');
    }
}

// Update UI based on recording state
function updateUIForRecording(isRecording) {
    const startButton = document.getElementById('startRecordingButton');
    const stopButton = document.getElementById('stopRecordingButton');
    const recordingStatus = document.getElementById('recordingStatus');
    
    if (isRecording) {
        startButton.disabled = true;
        stopButton.disabled = false;
        recordingStatus.style.display = 'block';
    } else {
        startButton.disabled = false;
        stopButton.disabled = true;
        recordingStatus.style.display = 'none';
        document.getElementById('recordingTime').textContent = '00:00';
    }
}

// Update recording time display
function updateRecordingTime() {
    const now = new Date();
    const elapsedSeconds = Math.floor((now - recordingStartTime) / 1000);
    const minutes = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
    const seconds = (elapsedSeconds % 60).toString().padStart(2, '0');
    
    document.getElementById('recordingTime').textContent = `${minutes}:${seconds}`;
}

// Show recording alert message
function showRecordingAlert(message, type) {
    const alertElement = document.getElementById('recordingAlert');
    alertElement.className = `alert alert-${type}`;
    alertElement.textContent = message;
    alertElement.style.display = 'block';
    
    // Hide alert after 5 seconds
    setTimeout(() => {
        alertElement.style.display = 'none';
    }, 5000);
} 