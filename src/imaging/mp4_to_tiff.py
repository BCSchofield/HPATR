"""
HPATR MP4 to TIFF Converter
Converts MP4 videos to TIFF frames and finds the brightest frame.
"""
import cv2
import os
import sys
import numpy as np

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config loader
from config_loader import get_mp4_config

def video_to_tiff_frames(video_path, output_folder):
    """
    Convert MP4 video to individual TIFF frames=
    
    Args:
        video_path (str): Path to the input MP4 video file
        output_folder (str): Folder to save the TIFF frames
    """
    # Check if video file exists
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        return False
    
    # Create output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)
    
    # Open the video file
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return False
    
    # Get video properties
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0
    
    print(f"Video info:")
    print(f"  Input: {video_path}")
    print(f"  Total frames: {total_frames}")
    print(f"  FPS: {fps:.2f}")
    print(f"  Duration: {duration:.2f} seconds")
    print(f"  Output folder: {output_folder}")
    print(f"\nConverting frames...")
    
    frame_count = 0
    success = True
    
    while success:
        # Read a frame
        success, frame = cap.read()
        
        if success:
            # Create filename with zero-padded frame number
            frame_filename = f"frame_{frame_count:06d}.tiff"
            frame_path = os.path.join(output_folder, frame_filename)
            
            # Save frame as TIFF
            cv2.imwrite(frame_path, frame)
            
            # Print progress every 100 frames
            if frame_count % 100 == 0:
                print(f"  Processed frame {frame_count}/{total_frames}")
            
            frame_count += 1
        else:
            break
    
    # Release the video capture object
    cap.release()
    
    print(f"\nConversion complete!")
    print(f"  Total frames saved: {frame_count}")
    print(f"  Frames saved to: {output_folder}")
    
    return True

def find_brightest_frame(tiff_folder, output_path):
    """
    Find the brightest TIFF frame and save it as 'flashed_output.tiff'
    
    Args:
        tiff_folder (str): Folder containing TIFF frames
        output_path (str): Path to save the brightest frame
    """
    print(f"\n🔍 Finding brightest frame...")
    print(f"  Input folder: {tiff_folder}")
    print(f"  Output: {output_path}")
    
    # Check if input folder exists
    if not os.path.exists(tiff_folder):
        print(f"Error: TIFF folder not found at {tiff_folder}")
        return False
    
    # Create output folder if it doesn't exist
    os.makedirs(output_path, exist_ok=True)
    
    # Get all TIFF files
    tiff_files = [f for f in os.listdir(tiff_folder) if f.lower().endswith('.tiff') or f.lower().endswith('.tif')]
    
    if not tiff_files:
        print(f"Error: No TIFF files found in {tiff_folder}")
        return False
    
    print(f"  Found {len(tiff_files)} TIFF files")
    print(f"  Analyzing brightness...")
    
    brightest_frame = None
    brightest_value = -1
    brightest_filename = None
    
    # Analyze each frame
    for i, filename in enumerate(tiff_files):
        file_path = os.path.join(tiff_folder, filename)
        
        # Read the image
        img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
        
        if img is not None:
            # Calculate average brightness
            brightness = np.mean(img)
            
            # Update if this is the brightest so far
            if brightness > brightest_value:
                brightest_value = brightness
                brightest_frame = img
                brightest_filename = filename
            
            # Show progress every 50 files
            if (i + 1) % 50 == 0:
                print(f"    Analyzed {i + 1}/{len(tiff_files)} files")
    
    if brightest_frame is not None:
        # Save the brightest frame
        output_file = os.path.join(output_path, "flashed_output.tiff")
        cv2.imwrite(output_file, brightest_frame)
        
        print(f"\n✅ Brightest frame found and saved!")
        print(f"  Brightest frame: {brightest_filename}")
        print(f"  Average brightness: {brightest_value:.2f}")
        print(f"  Saved to: {output_file}")
        
        return True
    else:
        print(f"Error: Could not process any TIFF files")
        return False

def main():
    """Main function to run the video conversion and brightest frame detection"""
    print("🚀 HPATR MP4 to TIFF Converter + Brightest Frame Finder")
    print("=" * 60)
    
    # Load config
    config = get_mp4_config()
    default_video_path = config.get('default_video_path', '/Volumes/LaCie/Phantom/Video/5fps_First_Cine_Trial.mp4')
    default_tiff_folder = config.get('default_tiff_folder', '/Volumes/LaCie/Phantom/TIFF_Output')
    default_flashed_output = config.get('default_flashed_output', '/Volumes/LaCie/Phantom/Flashed_Output')
    
    # Use command line arguments if provided, otherwise use config defaults
    if len(sys.argv) == 3:
        video_path = sys.argv[1]
        output_folder = sys.argv[2]
        print(f"Using command line arguments:")
        print(f"  Video: {video_path}")
        print(f"  Output: {output_folder}")
        print()
        
        # Convert video to frames
        success = video_to_tiff_frames(video_path, output_folder)
        if not success:
            return
            
    elif len(sys.argv) == 1:
        print(f"Using config paths:")
        print(f"  Video: {default_video_path}")
        print(f"  TIFF Output: {default_tiff_folder}")
        print(f"  Flashed Output: {default_flashed_output}")
        print()
        
        # Check if TIFF files already exist
        if os.path.exists(default_tiff_folder) and os.listdir(default_tiff_folder):
            print("TIFF files already exist. Skipping video conversion.")
        else:
            # Convert video to frames
            success = video_to_tiff_frames(default_video_path, default_tiff_folder)
            if not success:
                return
        
        # Find brightest frame
        success = find_brightest_frame(default_tiff_folder, default_flashed_output)
        
    else:
        print("Usage options:")
        print("1. Run with config defaults: python mp4_to_tiff.py")
        print("2. Specify paths: python mp4_to_tiff.py <input_video.mp4> <output_folder>")
        print(f"\nConfig defaults:")
        print(f"  Video: {default_video_path}")
        print(f"  TIFF output: {default_tiff_folder}")
        print(f"  Flashed output: {default_flashed_output}")
        print(f"\nTo change defaults, edit config/paths.yaml")
        return
    
    print("\n🎉 All operations completed successfully!")

if __name__ == "__main__":
    main() 