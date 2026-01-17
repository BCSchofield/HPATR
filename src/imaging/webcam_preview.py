"""
HPATR Webcam Preview and Settings
Opens a live video feed from a USB webcam with adjustable settings.
Use this to position the camera and adjust resolution, brightness, etc.
"""

import cv2
import numpy as np


class WebcamPreview:
    """Live webcam preview with adjustable settings"""
    
    def __init__(self, camera_index=0):
        """
        Initialize webcam preview.
        
        Args:
            camera_index (int): Index of the camera (default: 0)
        """
        self.camera_index = camera_index
        self.cap = None
        self.window_name = "Webcam Preview - Press 'q' to quit, 's' to save"
        self.settings_window = "Camera Settings"
        
        # Default settings
        self.width = 1920
        self.height = 1080
        self.brightness = 128
        self.contrast = 32
        self.saturation = 32
        self.hue = 0
        self.gain = 0
        self.exposure = -6  # Auto exposure
        
    def initialize_camera(self):
        """Initialize and configure the camera"""
        self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera at index {self.camera_index}")
        
        # Set initial resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        
        # Get actual resolution (camera may adjust to nearest supported)
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.width = actual_width
        self.height = actual_height
        
        print(f"Camera initialized at {self.width}x{self.height}")
        print(f"Available properties:")
        print(f"  Brightness: {self.cap.get(cv2.CAP_PROP_BRIGHTNESS)}")
        print(f"  Contrast: {self.cap.get(cv2.CAP_PROP_CONTRAST)}")
        print(f"  Saturation: {self.cap.get(cv2.CAP_PROP_SATURATION)}")
        print(f"  Hue: {self.cap.get(cv2.CAP_PROP_HUE)}")
        print(f"  Gain: {self.cap.get(cv2.CAP_PROP_GAIN)}")
        print(f"  Exposure: {self.cap.get(cv2.CAP_PROP_EXPOSURE)}")
        
        # Apply initial settings
        self.apply_settings()
    
    def apply_settings(self):
        """Apply current settings to camera"""
        if self.cap is None:
            return
        
        # Set properties (values may be normalized 0-1 or specific ranges depending on camera)
        self.cap.set(cv2.CAP_PROP_BRIGHTNESS, self.brightness / 255.0)
        self.cap.set(cv2.CAP_PROP_CONTRAST, self.contrast / 255.0)
        self.cap.set(cv2.CAP_PROP_SATURATION, self.saturation / 255.0)
        self.cap.set(cv2.CAP_PROP_HUE, self.hue / 180.0)
        self.cap.set(cv2.CAP_PROP_GAIN, self.gain)
        self.cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure)
    
    def create_trackbars(self):
        """Create trackbars for adjusting camera settings"""
        cv2.namedWindow(self.settings_window)
        
        # Create trackbars (0-255 for most, exposure is special)
        cv2.createTrackbar("Brightness", self.settings_window, self.brightness, 255, self.on_brightness_change)
        cv2.createTrackbar("Contrast", self.settings_window, self.contrast, 255, self.on_contrast_change)
        cv2.createTrackbar("Saturation", self.settings_window, self.saturation, 255, self.on_saturation_change)
        cv2.createTrackbar("Hue", self.settings_window, self.hue + 180, 360, self.on_hue_change)
        cv2.createTrackbar("Gain", self.settings_window, int(self.gain * 10), 100, self.on_gain_change)
        cv2.createTrackbar("Exposure", self.settings_window, int((self.exposure + 13) * 10), 260, self.on_exposure_change)
        
        # Resolution presets
        cv2.createTrackbar("Resolution", self.settings_window, 0, 3, self.on_resolution_change)
    
    def on_brightness_change(self, val):
        """Callback for brightness trackbar"""
        self.brightness = val
        self.apply_settings()
    
    def on_contrast_change(self, val):
        """Callback for contrast trackbar"""
        self.contrast = val
        self.apply_settings()
    
    def on_saturation_change(self, val):
        """Callback for saturation trackbar"""
        self.saturation = val
        self.apply_settings()
    
    def on_hue_change(self, val):
        """Callback for hue trackbar"""
        self.hue = val - 180  # Center at 0
        self.apply_settings()
    
    def on_gain_change(self, val):
        """Callback for gain trackbar"""
        self.gain = val / 10.0
        self.apply_settings()
    
    def on_exposure_change(self, val):
        """Callback for exposure trackbar"""
        self.exposure = (val / 10.0) - 13  # Range from -13 to 13
        self.apply_settings()
    
    def on_resolution_change(self, val):
        """Callback for resolution preset trackbar"""
        resolutions = [
            (640, 480),   # VGA
            (1280, 720),  # HD
            (1920, 1080), # Full HD
            (3840, 2160)  # 4K (if supported)
        ]
        
        if val < len(resolutions):
            new_width, new_height = resolutions[val]
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, new_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, new_height)
            
            # Get actual resolution
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.width = actual_width
            self.height = actual_height
            print(f"Resolution changed to {self.width}x{self.height}")
    
    def add_info_overlay(self, frame):
        """Add information overlay to the frame"""
        overlay = frame.copy()
        
        # Get current settings
        info_lines = [
            f"Resolution: {self.width}x{self.height}",
            f"Brightness: {self.brightness}",
            f"Contrast: {self.contrast}",
            f"Saturation: {self.saturation}",
            f"Hue: {self.hue}",
            f"Gain: {self.gain:.1f}",
            f"Exposure: {self.exposure:.1f}",
            "",
            "Controls:",
            "  'q' - Quit",
            "  's' - Save current frame",
            "  'r' - Reset settings",
        ]
        
        # Draw semi-transparent background
        y_offset = 10
        for i, line in enumerate(info_lines):
            text_size = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(overlay, (5, y_offset - 15), (text_size[0] + 10, y_offset + 5), (0, 0, 0), -1)
            cv2.putText(overlay, line, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            y_offset += 20
        
        # Blend overlay
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        return frame
    
    def save_frame(self, frame, filename=None):
        """Save current frame to file"""
        from datetime import datetime
        import os
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"webcam_snapshot_{timestamp}.png"
        
        success = cv2.imwrite(filename, frame)
        if success:
            print(f"Frame saved to: {filename}")
        else:
            print(f"Failed to save frame to: {filename}")
        return success
    
    def reset_settings(self):
        """Reset all settings to defaults"""
        self.brightness = 128
        self.contrast = 32
        self.saturation = 32
        self.hue = 0
        self.gain = 0
        self.exposure = -6
        
        # Update trackbars
        cv2.setTrackbarPos("Brightness", self.settings_window, self.brightness)
        cv2.setTrackbarPos("Contrast", self.settings_window, self.contrast)
        cv2.setTrackbarPos("Saturation", self.settings_window, self.saturation)
        cv2.setTrackbarPos("Hue", self.settings_window, self.hue + 180)
        cv2.setTrackbarPos("Gain", self.settings_window, int(self.gain * 10))
        cv2.setTrackbarPos("Exposure", self.settings_window, int((self.exposure + 13) * 10))
        
        self.apply_settings()
        print("Settings reset to defaults")
    
    def run(self):
        """Run the preview loop"""
        try:
            self.initialize_camera()
            self.create_trackbars()
            
            print("\n" + "="*50)
            print("Webcam Preview Started")
            print("="*50)
            print("Controls:")
            print("  'q' - Quit")
            print("  's' - Save current frame")
            print("  'r' - Reset all settings to defaults")
            print("  Use trackbars in 'Camera Settings' window to adjust")
            print("="*50 + "\n")
            
            while True:
                ret, frame = self.cap.read()
                
                if not ret:
                    print("Error: Failed to read frame")
                    break
                
                # Add info overlay
                frame_with_info = self.add_info_overlay(frame.copy())
                
                # Display frame
                cv2.imshow(self.window_name, frame_with_info)
                
                # Handle keyboard input
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'):
                    print("Quitting...")
                    break
                elif key == ord('s'):
                    self.save_frame(frame)
                elif key == ord('r'):
                    self.reset_settings()
        
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Release resources"""
        if self.cap is not None:
            self.cap.release()
        cv2.destroyAllWindows()
        print("Camera released and windows closed")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Live webcam preview with adjustable settings")
    parser.add_argument("--camera", "-c", type=int, default=0,
                       help="Camera index (default: 0)")
    
    args = parser.parse_args()
    
    preview = WebcamPreview(camera_index=args.camera)
    preview.run()
