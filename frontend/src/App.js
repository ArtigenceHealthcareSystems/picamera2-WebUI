import React, { useState, useEffect, useRef } from 'react';
import { Box, Button, Typography, CircularProgress } from '@mui/material';
import { styled } from '@mui/material/styles';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import StopIcon from '@mui/icons-material/Stop';

const ViewfinderContainer = styled(Box)(({ theme }) => ({
  position: 'relative',
  width: '100%',
  maxWidth: '1200px',
  margin: '0 auto',
  backgroundColor: '#000',
  aspectRatio: '16/9',
  overflow: 'hidden',
  borderRadius: theme.spacing(1),
  boxShadow: theme.shadows[4],
}));

const CameraFeed = styled('img')({
  width: '100%',
  height: '100%',
  objectFit: 'contain',
});

const ControlsContainer = styled(Box)(({ theme }) => ({
  position: 'absolute',
  bottom: theme.spacing(2),
  left: '50%',
  transform: 'translateX(-50%)',
  display: 'flex',
  gap: theme.spacing(2),
  padding: theme.spacing(1),
  backgroundColor: 'rgba(0, 0, 0, 0.5)',
  borderRadius: theme.spacing(2),
}));

const RecordButton = styled(Button)(({ theme, recording }) => ({
  backgroundColor: recording ? '#ff4444' : '#ffffff',
  color: recording ? '#ffffff' : '#000000',
  '&:hover': {
    backgroundColor: recording ? '#ff6666' : '#f0f0f0',
  },
}));

const RecordingIndicator = styled(Box)(({ theme }) => ({
  position: 'absolute',
  top: theme.spacing(2),
  right: theme.spacing(2),
  display: 'flex',
  alignItems: 'center',
  gap: theme.spacing(1),
  padding: theme.spacing(0.5, 1),
  backgroundColor: 'rgba(255, 0, 0, 0.7)',
  borderRadius: theme.spacing(1),
  color: '#ffffff',
  animation: 'blink 1.5s infinite',
  '@keyframes blink': {
    '0%': { opacity: 1 },
    '50%': { opacity: 0.3 },
    '100%': { opacity: 1 },
  },
}));

const Timer = styled(Typography)({
  fontFamily: 'monospace',
  fontWeight: 'bold',
});

const FpsDisplay = styled(Typography)({
  position: 'absolute',
  top: '10px',
  left: '10px',
  color: '#fff',
  backgroundColor: 'rgba(0, 0, 0, 0.5)',
  padding: '4px 8px',
  borderRadius: '4px',
  fontFamily: 'monospace',
});

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [fps, setFps] = useState(0);
  const [backendFps, setBackendFps] = useState(0);
  const [recordingFps, setRecordingFps] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  
  const canvasRef = useRef(null);
  const animationFrameRef = useRef(null);
  const recordingTimerRef = useRef(null);
  const frameCountRef = useRef(0);
  const recordingStartTime = useRef(0);
  const workerRef = useRef(null);
  const recordingStateRef = useRef(false);
  const lastRecordingUpdateRef = useRef(0);
  
  // Simple array to store image data URLs
  const framesRef = useRef([]);
  
  // Create and initialize the Web Worker for recording
  useEffect(() => {
    // Create a more sophisticated worker that can handle encoding hints
    const workerCode = `
      // Recording state
      let frames = [];
      let isRecording = false;
      let frameCount = 0;
      let lastUpdateTime = 0;
      let processingQueue = [];
      let isProcessing = false;
      
      // Process frames in the background
      async function processFrameQueue() {
        if (isProcessing || processingQueue.length === 0) return;
        
        isProcessing = true;
        
        // Process frames in batches
        const batch = processingQueue.splice(0, 5);
        for (const frame of batch) {
          frames.push(frame);
          frameCount++;
          
          // Report progress
          const now = performance.now();
          if (frameCount % 30 === 0) {
            const elapsedSecs = (now - lastUpdateTime) / 1000;
            const currentFps = Math.round(30 / elapsedSecs);
            lastUpdateTime = now;
            
            self.postMessage({ 
              type: 'progress', 
              count: frameCount,
              fps: currentFps
            });
          }
          
          // Yield to prevent blocking
          if (frameCount % 10 === 0) {
            await new Promise(resolve => setTimeout(resolve, 0));
          }
        }
        
        isProcessing = false;
        
        // Continue processing
        if (processingQueue.length > 0) {
          processFrameQueue();
        }
      }
      
      // Message handler
      self.onmessage = function(e) {
        const { type, data, config } = e.data;
        
        switch(type) {
          case 'start':
            frames = [];
            isRecording = true;
            frameCount = 0;
            lastUpdateTime = performance.now();
            processingQueue = [];
            isProcessing = false;
            self.postMessage({ type: 'started' });
            break;
            
          case 'frame':
            if (isRecording) {
              processingQueue.push(data);
              if (!isProcessing) {
                processFrameQueue();
              }
            }
            break;
            
          case 'stop':
            isRecording = false;
            processFrameQueue().then(() => {
              self.postMessage({ 
                type: 'complete', 
                frames: frames,
                count: frameCount
              });
              frames = [];
            });
            break;
        }
      };
    `;
    
    // Create worker
    const blob = new Blob([workerCode], { type: 'application/javascript' });
    const workerUrl = URL.createObjectURL(blob);
    const worker = new Worker(workerUrl);
    workerRef.current = worker;
    
    // Set up message handler
    worker.onmessage = (e) => {
      const { type, frames, count, fps } = e.data;
      
      if (type === 'progress') {
        console.log(`Recorded ${count} frames, current FPS: ${fps}`);
        setRecordingFps(fps);
      } else if (type === 'complete') {
        console.log(`Recording complete with ${count} frames`);
        setRecordingFps(0);
        // Use Pi's hardware encoding
        createPiHardwareEncodedVideo(frames, count);
      }
    };
    
    // Clean up
    URL.revokeObjectURL(workerUrl);
    return () => {
      if (workerRef.current) {
        workerRef.current.terminate();
        workerRef.current = null;
      }
    };
  }, []);

  // Create a video using Raspberry Pi's hardware encoding capabilities
  const createPiHardwareEncodedVideo = async (frames, frameCount) => {
    try {
      console.log('Creating hardware-accelerated video using Pi GPU...');
      setIsLoading(true);
      
      // Calculate actual FPS
      const duration = (Date.now() - recordingStartTime.current) / 1000;
      const fps = Math.round(frameCount / duration);
      console.log(`Actual recording FPS: ${fps}`);
      
      // Create a timestamp for the video file
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const videoFilename = `video_cam_0_${timestamp}_HW.mp4`;
      
      // First, we need to save all frames as temporary JPEG files on the server
      console.log('Uploading frames to server...');
      
      // Create a FormData object to send frames in batches
      const batchSize = 50;
      let currentBatch = 0;
      const totalBatches = Math.ceil(frameCount / batchSize);
      
      for (let batchStart = 0; batchStart < frameCount; batchStart += batchSize) {
        currentBatch++;
        const batchEnd = Math.min(batchStart + batchSize, frameCount);
        console.log(`Uploading batch ${currentBatch}/${totalBatches} (frames ${batchStart}-${batchEnd-1})...`);
        
        const formData = new FormData();
        formData.append('fps', fps.toString());
        formData.append('timestamp', timestamp);
        formData.append('batchNumber', currentBatch.toString());
        formData.append('totalBatches', totalBatches.toString());
        
        // Add frames to this batch
        for (let i = batchStart; i < batchEnd; i++) {
          // Convert data URL to Blob
          const dataUrl = frames[i];
          const base64 = dataUrl.split(',')[1];
          const byteString = atob(base64);
          const ab = new ArrayBuffer(byteString.length);
          const ia = new Uint8Array(ab);
          
          for (let j = 0; j < byteString.length; j++) {
            ia[j] = byteString.charCodeAt(j);
          }
          
          const blob = new Blob([ab], { type: 'image/jpeg' });
          
          // Add frame to form data with frame number for ordering
          formData.append('frames', blob, `frame_${i.toString().padStart(6, '0')}.jpg`);
        }
        
        // Upload this batch
        await fetch('/api/upload_frames', {
          method: 'POST',
          body: formData
        });
        
        // Give UI a chance to update
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      
      console.log('All frames uploaded. Starting hardware encoding...');
      
      // Now trigger the server to encode the video using Pi's hardware
      const encodingResponse = await fetch('/api/encode_video', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          timestamp,
          fps,
          frameCount,
          filename: videoFilename
        })
      });
      
      if (!encodingResponse.ok) {
        throw new Error('Server encoding failed: ' + await encodingResponse.text());
      }
      
      const encodingResult = await encodingResponse.json();
      
      if (!encodingResult.success) {
        throw new Error('Encoding error: ' + encodingResult.error);
      }
      
      console.log('Hardware encoding complete. Downloading video...');
      
      // Download the encoded video
      const a = document.createElement('a');
      a.href = `/api/download_video/${videoFilename}`;
      a.download = videoFilename;
      document.body.appendChild(a);
      a.click();
      
      // Clean up
      setTimeout(() => {
        document.body.removeChild(a);
      }, 1000);
      
      setIsLoading(false);
      
      console.log(`Pi hardware-accelerated recording complete: ${frameCount} frames at ${fps} FPS`);
      
      // Clean up temporary files on server
      fetch('/api/cleanup_temp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ timestamp })
      });
      
    } catch (error) {
      console.error('Error creating Pi hardware-accelerated video:', error);
      alert('Error: ' + error.message);
      setIsLoading(false);
    }
  };

  // Main rendering and frame capture - optimized for low CPU usage
  useEffect(() => {
    // Track recording state
    recordingStateRef.current = isRecording;
    
    // Set up canvas and image
    const canvas = document.createElement('canvas');
    canvasRef.current = canvas;
    
    // Set up image loading with low priority
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = '/video_feed_0';
    img.loading = 'eager'; // Hint to browser to load this immediately
    
    // FPS tracking with high performance timer
    const fpsData = {
      frameCount: 0,
      lastUpdate: performance.now(),
      frames: []
    };
    
    // Use requestAnimationFrame timing for better performance
    let lastFrameTime = 0;
    
    // Low impact frame update function
    const updateFrame = (timestamp) => {
      // Calculate time since last frame
      const elapsed = timestamp - lastFrameTime;
      lastFrameTime = timestamp;
      
      // Track FPS with a sliding window for more accurate measurement
      fpsData.frameCount++;
      fpsData.frames.push(elapsed);
      // Keep only the last 20 frames for calculating FPS
      if (fpsData.frames.length > 20) {
        fpsData.frames.shift();
      }
      
      if (img.complete && img.naturalWidth) {
        // Set canvas size if needed
        if (canvas.width !== img.naturalWidth || canvas.height !== img.naturalHeight) {
          canvas.width = img.naturalWidth;
          canvas.height = img.naturalHeight;
          console.log(`Canvas size set to ${canvas.width}x${canvas.height}`);
        }
        
        // Draw image to canvas (low impact operation)
        const ctx = canvas.getContext('2d', { 
          alpha: false,
          desynchronized: true // Use desynchronized rendering for better performance
        });
        ctx.drawImage(img, 0, 0);
        
        // If recording, capture frame with minimal impact
        if (recordingStateRef.current && workerRef.current) {
          try {
            // Use the most efficient method to get the frame
            if (img.src.startsWith('blob:') || img.src.startsWith('data:image/jpeg')) {
              // Use image source directly
              workerRef.current.postMessage({
                type: 'frame',
                data: img.src
              });
            } else {
              // Use canvas with 1.0 quality as requested
              const dataUrl = canvas.toDataURL('image/jpeg', 1.0);
              workerRef.current.postMessage({
                type: 'frame',
                data: dataUrl
              });
            }
            
            frameCountRef.current++;
          } catch (error) {
            console.error('Error capturing frame:', error);
          }
        }
        
        // Update FPS display at most every 500ms
        const now = performance.now();
        if (now - fpsData.lastUpdate > 500) {
          // Calculate average frame time from sliding window
          const avgFrameTime = fpsData.frames.reduce((a, b) => a + b, 0) / fpsData.frames.length;
          const calculatedFps = Math.round(1000 / avgFrameTime);
          
          setFps(calculatedFps);
          fpsData.lastUpdate = now;
          fpsData.frameCount = 0;
        }
        
        // Load next frame with minimal impact
        img.src = '/video_feed_0?t=' + Date.now(); // Add timestamp to prevent caching
      }
      
      // Schedule next frame
      animationFrameRef.current = requestAnimationFrame(updateFrame);
    };
    
    // Start the update loop
    animationFrameRef.current = requestAnimationFrame(updateFrame);
    
    // Cleanup function
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
      }
    };
  }, [isRecording]); // Re-run if recording state changes
  
  // Fetch backend FPS periodically
  useEffect(() => {
    const fetchBackendFps = async () => {
      try {
        const response = await fetch('/get_fps_0');
        const data = await response.json();
        if (data.success) {
          setBackendFps(data.fps);
        }
      } catch (error) {
        console.error('Error fetching backend FPS:', error);
      }
    };
    
    // Fetch initially and then every 2 seconds
    fetchBackendFps();
    const interval = setInterval(fetchBackendFps, 2000);
    
    return () => clearInterval(interval);
  }, []);
  
  // Timer functions
  const startTimer = () => {
    setRecordingTime(0);
    const startTime = Date.now();
    recordingTimerRef.current = setInterval(() => {
      setRecordingTime(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
  };
  
  const stopTimer = () => {
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
  };
  
  const formatTime = (seconds) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
  };
  
  // Start recording function
  const handleStartRecording = () => {
    if (isRecording) return;
    
    setIsLoading(true);
    try {
      // Reset frame counter and FPS
      frameCountRef.current = 0;
      recordingStartTime.current = Date.now();
      lastRecordingUpdateRef.current = Date.now();
      setRecordingFps(0);
      
      // Start recording in worker
      if (workerRef.current) {
        workerRef.current.postMessage({ type: 'start' });
        console.log('Started recording in worker');
      } else {
        throw new Error('Recording worker not available');
      }
      
      // Start recording
      setIsRecording(true);
      startTimer();
      console.log('Recording started');
    } catch (error) {
      console.error('Error starting recording:', error);
      alert('Failed to start recording: ' + error.message);
    } finally {
      setIsLoading(false);
    }
  };
  
  // Stop recording function
  const handleStopRecording = () => {
    if (!isRecording) return;
    
    setIsLoading(true);
    console.log('Stopping recording...');
    
    try {
      // Stop recording in UI
      setIsRecording(false);
      stopTimer();
      
      // Tell worker to stop recording and process frames
      if (workerRef.current) {
        workerRef.current.postMessage({ type: 'stop' });
        console.log('Sent stop signal to worker');
      } else {
        throw new Error('Recording worker not available');
      }
      
      // Note: actual video creation happens when the worker responds
      // with the 'complete' message, which calls createPiHardwareEncodedVideo
      
    } catch (error) {
      console.error('Error stopping recording:', error);
      alert('Failed to save recording: ' + error.message);
      setRecordingFps(0); // Reset recording FPS on error
      setIsLoading(false);
    }
  };

  return (
    <div className="App">
      <div className="camera-container">
        <img 
          src="/video_feed_0" 
          alt="Camera Feed" 
          className="camera-feed"
        />
        
        {/* Overlay FPS display */}
        <div className="fps-overlay top-left">
          {fps} FPS
        </div>
        
        {/* Recording indicator and timer */}
        {isRecording && (
          <div className="recording-overlay top-right">
            <div className="recording-dot"></div>
            <div className="recording-time">{formatTime(recordingTime)}</div>
          </div>
        )}
        
        {/* Additional FPS information */}
        <div className="fps-details-overlay bottom-left">
          <div>Display: {fps} FPS</div>
          <div>Backend: {backendFps} FPS</div>
          {isRecording && <div className="recording-fps">Recording: {recordingFps} FPS</div>}
        </div>
        
        {/* Recording control button */}
        <div className="controls-overlay">
          <button 
            onClick={isRecording ? handleStopRecording : handleStartRecording}
            disabled={isLoading}
            className={isRecording ? 'stop-recording-btn' : 'start-recording-btn'}
          >
            {isRecording ? 'STOP RECORDING' : 'START RECORDING'}
          </button>
        </div>
      </div>
      
      <style jsx>{`
        .App {
          position: relative;
          width: 100%;
          height: 100vh;
          overflow: hidden;
          background: #000;
          display: flex;
          justify-content: center;
          align-items: center;
        }
        
        .camera-container {
          position: relative;
          max-width: 100%;
          max-height: 100vh;
        }
        
        .camera-feed {
          display: block;
          max-width: 100%;
          max-height: 100vh;
        }
        
        /* Overlay positioning */
        .fps-overlay {
          position: absolute;
          background: rgba(0, 0, 0, 0.7);
          color: white;
          padding: 5px 10px;
          border-radius: 4px;
          font-family: monospace;
          font-size: 16px;
        }
        
        .top-left {
          top: 10px;
          left: 10px;
        }
        
        .top-right {
          top: 10px;
          right: 10px;
        }
        
        .bottom-left {
          bottom: 10px;
          left: 10px;
        }
        
        .fps-details-overlay {
          position: absolute;
          background: rgba(0, 0, 0, 0.7);
          color: white;
          padding: 8px;
          border-radius: 4px;
          font-family: monospace;
          font-size: 14px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        
        .recording-overlay {
          display: flex;
          align-items: center;
          background: rgba(204, 0, 0, 0.8);
          color: white;
          padding: 5px 10px;
          border-radius: 4px;
          font-family: monospace;
        }
        
        .recording-dot {
          width: 12px;
          height: 12px;
          background-color: #ff0000;
          border-radius: 50%;
          margin-right: 8px;
          animation: blink 1s infinite;
        }
        
        .recording-fps {
          color: #ff4444;
        }
        
        .controls-overlay {
          position: absolute;
          bottom: 20px;
          left: 50%;
          transform: translateX(-50%);
        }
        
        .start-recording-btn, .stop-recording-btn {
          padding: 10px 20px;
          border: none;
          border-radius: 4px;
          font-weight: bold;
          cursor: pointer;
          font-size: 16px;
          transition: all 0.2s;
        }
        
        .start-recording-btn {
          background-color: #4CAF50;
          color: white;
        }
        
        .stop-recording-btn {
          background-color: #f44336;
          color: white;
        }
        
        button:disabled {
          background-color: #cccccc;
          cursor: not-allowed;
        }
        
        @keyframes blink {
          0% { opacity: 1; }
          50% { opacity: 0.5; }
          100% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}

export default App; 