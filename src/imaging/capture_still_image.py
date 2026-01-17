"""
HPATR Webcam Still Image Capture
Captures a single still image from a USB webcam using OpenCV.
"""

import cv2
import os
from datetime import datetime


def capture_still_image(camera_index=0, output_path=None, resolution=None):
    """
    Capture a still image from a USB webcam.
    
    Args:
        camera_index (int): Index of the camera (default: 0 for first camera)
        output_path (str): Path to save the image. If None, uses timestamp.
        resolution (tuple): Optional (width, height) resolution. If None, uses camera default.
    
    Returns:
        str: Path to the saved image, or None if capture failed
    """
    # Initialize camera
    cap = cv2.VideoCapture(camera_index)
    
    if not cap.isOpened():
        print(f"Error: Could not open camera at index {camera_index}")
        return None
    
    # Set resolution if specified
    if resolution:
        width, height = resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        print(f"Setting resolution to {width}x{height}")
    
    # Read a few frames to allow camera to adjust (warm-up)
    for _ in range(5):
        ret, _ = cap.read()
        if not ret:
            print("Warning: Failed to read initial frames")
    
    # Capture the frame
    ret, frame = cap.read()
    
    if not ret:
        print("Error: Failed to capture frame")
        cap.release()
        return None
    
    # Get actual resolution used
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Captured frame at {actual_width}x{actual_height}")
    
    # Release camera
    cap.release()
    
    # Generate output path if not provided
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"webcam_capture_{timestamp}.png"
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path) if os.path.dirname(output_path) else "."
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    # Save the image
    success = cv2.imwrite(output_path, frame)
    
    if success:
        print(f"Image saved successfully to: {output_path}")
        return output_path
    else:
        print(f"Error: Failed to save image to {output_path}")
        return None


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Capture a still image from USB webcam")
    parser.add_argument("--camera", "-c", type=int, default=0,
                       help="Camera index (default: 0)")
    parser.add_argument("--output", "-o", type=str, default=None,
                       help="Output file path (default: timestamped filename)")
    parser.add_argument("--width", "-w", type=int, default=None,
                       help="Image width in pixels")
    parser.add_argument("--height", "-H", type=int, default=None,
                       help="Image height in pixels")
    
    args = parser.parse_args()
    
    # Set resolution if both width and height provided
    resolution = None
    if args.width and args.height:
        resolution = (args.width, args.height)
    elif args.width or args.height:
        print("Warning: Both width and height must be specified. Using camera default.")
    
    # Capture image
    result = capture_still_image(
        camera_index=args.camera,
        output_path=args.output,
        resolution=resolution
    )
    
    if result:
        print(f"\n✓ Capture successful!")
    else:
        print(f"\n✗ Capture failed!")
        exit(1)
