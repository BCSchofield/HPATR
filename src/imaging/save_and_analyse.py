#!/usr/bin/env python3
"""
HPATR Image Processing Pipeline
Main script for processing droplet images with Canny + Watershed + optimization.
"""
import os
import shutil
from datetime import datetime
import cv2
import sys
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config loader
from config_loader import get_imaging_config

# Import processing functions (relative import)
from imaging.expansion_detection import process_image
from imaging.expansion_detection import create_position_optimization_visualization

# TODO LIST - Future Improvements
# =============================
# 1. Integrate with phantom camera (Taking video, stopping video, reading video for brightest frame, saving video to hard drive)
# =============================

def copy_input_to_lacie(input_source, destination_folder):
    """Copy input file to Input/ subfolder in LaCie"""
    input_subfolder = os.path.join(destination_folder, "Input")
    os.makedirs(input_subfolder, exist_ok=True)
    
    # Get the file extension from the source
    _, file_extension = os.path.splitext(input_source)
    input_destination = os.path.join(input_subfolder, f"input{file_extension}")
    shutil.copy2(input_source, input_destination)
    
    print(f"Copied input file to: {input_destination}")
    return input_destination

def create_outputs_folder(main_folder):
    """Create Outputs/ subfolder for Canny_W_Watershed results"""
    outputs_folder = os.path.join(main_folder, "Outputs")
    os.makedirs(outputs_folder, exist_ok=True)
    print(f"Created outputs folder: {outputs_folder}")
    return outputs_folder

def save_processed_images_to_lacie(processed_results, outputs_folder):
    """Save all expansion_detection outputs to LaCie"""
    try:
        # Save final optimized image
        final_image_path = os.path.join(outputs_folder, "FINAL_OPTIMIZED_RESULT.png")
        plt.figure(figsize=(12, 8))
        plt.imshow(processed_results['final_image'])
        plt.title(f"Final Optimized Result - {len(processed_results['optimized_circles'])} Droplets")
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(final_image_path, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"Saved final optimized image: {final_image_path}")
        
        # Save comprehensive CSV
        csv_path = os.path.join(outputs_folder, "FINAL_ANALYSIS.csv")
        df = pd.DataFrame(processed_results['optimization_data'])
        df.to_csv(csv_path, index=False)
        print(f"Saved comprehensive analysis: {csv_path}")
        
        # Save Canny edges image
        if 'canny_edges' in processed_results:
            canny_edges_path = os.path.join(outputs_folder, "CANNY_EDGES.png")
            cv2.imwrite(canny_edges_path, processed_results['canny_edges'])
            print(f"Saved Canny edges: {canny_edges_path}")
        
        # Save Canny circles visualization
        canny_viz = cv2.imread(processed_results.get('input_path', ''))
        if canny_viz is not None:
            canny_viz = cv2.cvtColor(canny_viz, cv2.COLOR_BGR2RGB)
            for circle in processed_results['canny_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(canny_viz, (x, y), r, (0, 255, 0), 2)  # Green for Canny
            canny_path = os.path.join(outputs_folder, "CANNY_DETECTION.png")
            cv2.imwrite(canny_path, cv2.cvtColor(canny_viz, cv2.COLOR_RGB2BGR))
            print(f"Saved Canny detection: {canny_path}")
        
        # Save Watershed circles visualization
        watershed_viz = cv2.imread(processed_results.get('input_path', ''))
        if watershed_viz is not None:
            watershed_viz = cv2.cvtColor(watershed_viz, cv2.COLOR_BGR2RGB)
            for circle in processed_results['watershed_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(watershed_viz, (x, y), r, (255, 0, 0), 2)  # Red for Watershed
            watershed_path = os.path.join(outputs_folder, "WATERSHED_DETECTION.png")
            cv2.imwrite(watershed_path, cv2.cvtColor(watershed_viz, cv2.COLOR_RGB2BGR))
            print(f"Saved Watershed detection: {watershed_path}")
        
        # Save position movement visualization
        position_movement_viz = create_position_optimization_visualization(
            cv2.imread(processed_results.get('input_path', '')),
            processed_results['all_circles_before_optimization'],
            processed_results['size_optimized_circles'],
            processed_results['optimized_circles'],
            processed_results['position_optimization_data']
        )
        position_path = os.path.join(outputs_folder, "POSITION_MOVEMENT.png")
        cv2.imwrite(position_path, cv2.cvtColor(position_movement_viz, cv2.COLOR_RGB2BGR))
        print(f"Saved position movement visualization: {position_path}")
        
        # Create the wonderful 12-part comprehensive visualization
        debug_folder = os.path.join(outputs_folder, "debug_images")
        os.makedirs(debug_folder, exist_ok=True)
        
        # Standalone preprocessing pipeline overview (saved every run)
        try:
            # Prefer exact intermediates produced by process_image
            pp_debug = processed_results.get('preprocess_debug')
            pp_params = processed_results.get('preprocess_params', {})
            original_path = processed_results.get('input_path', '')
            original_img = cv2.imread(original_path)

            fig_pp, axes_pp = plt.subplots(2, 3, figsize=(10, 6))
            title_params = []
            if pp_params:
                title_params.append(f"denoise={pp_params.get('denoise_ksize')}")
                tile = pp_params.get('clahe_tile')
                title_params.append(f"clahe={pp_params.get('clahe_clip')},{tile}")
                title_params.append(f"gamma={pp_params.get('gamma')}")
                title_params.append(f"blur={pp_params.get('blur_ksize')}")
            fig_pp.suptitle('Preprocessing Pipeline' + (" ("+" | ".join(title_params)+")" if title_params else ''), fontsize=12)

            # Original
            if original_img is not None:
                axes_pp[0,0].imshow(cv2.cvtColor(original_img, cv2.COLOR_BGR2RGB))
            else:
                axes_pp[0,0].text(0.5,0.5,'Original not found',ha='center',va='center')
            axes_pp[0,0].set_title('Original'); axes_pp[0,0].axis('off')

            def show_gray(ax, img, title):
                if img is not None:
                    ax.imshow(img, cmap='gray')
                else:
                    ax.text(0.5,0.5,f'{title} missing',ha='center',va='center')
                ax.set_title(title); ax.axis('off')

            if isinstance(pp_debug, dict):
                show_gray(axes_pp[0,1], pp_debug.get('gray'), 'Gray')
                show_gray(axes_pp[0,2], pp_debug.get('denoised'), 'Median')
                show_gray(axes_pp[1,0], pp_debug.get('clahe'), 'CLAHE')
                show_gray(axes_pp[1,1], pp_debug.get('gamma_corrected'), 'Gamma')
                show_gray(axes_pp[1,2], pp_debug.get('blur'), 'Enhanced + Blur')
            else:
                # Fallback: recompute minimal view if preprocess_debug not available
                if original_img is not None:
                    gray = cv2.cvtColor(original_img, cv2.COLOR_BGR2GRAY)
                    denoised = cv2.medianBlur(gray, ksize=5)
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                    local_contrast = clahe.apply(denoised)
                    import numpy as np
                    inv = 1.0 / 0.75
                    lut = (np.linspace(0, 1, 256) ** inv * 255.0).astype(np.uint8)
                    gamma_corrected = cv2.LUT(local_contrast, lut)
                    enhanced = cv2.normalize(gamma_corrected, None, 0, 255, cv2.NORM_MINMAX)
                    blur = cv2.GaussianBlur(enhanced, (5, 5), 0)

                    show_gray(axes_pp[0,1], gray, 'Gray')
                    show_gray(axes_pp[0,2], denoised, 'Median')
                    show_gray(axes_pp[1,0], local_contrast, 'CLAHE')
                    show_gray(axes_pp[1,1], gamma_corrected, 'Gamma')
                    show_gray(axes_pp[1,2], blur, 'Enhanced + Blur')
                else:
                    for ax, title in zip(axes_pp.flatten()[1:], ['Gray','Median','CLAHE','Gamma','Enhanced + Blur']):
                        ax.text(0.5,0.5,f'{title} unavailable',ha='center',va='center')
                        ax.set_title(title); ax.axis('off')

            plt.tight_layout()
            preprocessing_path = os.path.join(debug_folder, 'PREPROCESSING_OVERVIEW.png')
            plt.savefig(preprocessing_path, dpi=200, bbox_inches='tight')
            plt.close(fig_pp)
            print(f"Saved preprocessing overview: {preprocessing_path}")
        except Exception as e:
            print(f"[WARNING] Failed to create preprocessing overview: {e}")
        
        # Create a figure to show all steps (4 rows, 3 columns) - sized to fit screen
        fig, axes = plt.subplots(4, 3, figsize=(15, 12))
        fig.suptitle('Complete Droplet Detection & Optimization Pipeline', fontsize=14)
        
        # Load the original image
        original_img = cv2.imread(processed_results.get('input_path', ''))
        if original_img is not None:
            original_img = cv2.cvtColor(original_img, cv2.COLOR_BGR2RGB)
            
            # Row 1: Original and Detection Methods
            axes[0,0].imshow(original_img)
            axes[0,0].set_title('Original Image')
            axes[0,0].axis('off')
            
            # Canny detection
            canny_viz = original_img.copy()
            for circle in processed_results['canny_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(canny_viz, (x, y), r, (0, 255, 0), 2)  # Green for Canny
            axes[0,1].imshow(canny_viz)
            axes[0,1].set_title(f'Canny Detection ({len(processed_results["canny_circles"])} circles)')
            axes[0,1].axis('off')
            
            # Watershed detection
            watershed_viz = original_img.copy()
            for circle in processed_results['watershed_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(watershed_viz, (x, y), r, (255, 0, 0), 2)  # Red for Watershed
            axes[0,2].imshow(watershed_viz)
            axes[0,2].set_title(f'Watershed Detection ({len(processed_results["watershed_circles"])} circles)')
            axes[0,2].axis('off')
            
            # Row 2: Combined Detection and Optimization Steps
            # Combined detection
            combined_viz = original_img.copy()
            for circle in processed_results['canny_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(combined_viz, (x, y), r, (0, 255, 0), 2)  # Green for Canny
            for circle in processed_results['watershed_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(combined_viz, (x, y), r, (255, 0, 0), 2)  # Red for Watershed
            axes[1,0].imshow(combined_viz)
            axes[1,0].set_title('Combined Detection (Before Optimization)')
            axes[1,0].axis('off')
            
            # Size optimized circles
            size_opt_viz = original_img.copy()
            for circle in processed_results['size_optimized_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(size_opt_viz, (x, y), r, (255, 255, 0), 2)  # Yellow for size-optimized
            axes[1,1].imshow(size_opt_viz)
            axes[1,1].set_title('After Size Optimization')
            axes[1,1].axis('off')
            
            # Position movement visualization
            axes[1,2].imshow(position_movement_viz)
            axes[1,2].set_title('Position Optimization Movement')
            axes[1,2].axis('off')
            
            # Row 3: Final Results
            axes[2,0].imshow(processed_results['final_image'])
            axes[2,0].set_title('Final Optimized Result')
            axes[2,0].axis('off')
            
            # Diameter histogram
            if len(df) > 0:
                axes[2,1].hist(df['optimized_diameter_px'], bins=20, color='skyblue', edgecolor='black')
                axes[2,1].set_title('Optimized Diameter Distribution')
                axes[2,1].set_xlabel('Diameter (pixels)')
                axes[2,1].set_ylabel('Count')
            else:
                axes[2,1].text(0.5, 0.5, 'No droplets detected', ha='center', va='center', transform=axes[2,1].transAxes)
                axes[2,1].set_title('Diameter Distribution')
            
            # Radius change histogram
            if len(df) > 0:
                axes[2,2].hist(df['radius_change_percent'], bins=20, color='orange', edgecolor='black')
                axes[2,2].set_title('Radius Change Distribution')
                axes[2,2].set_xlabel('Radius Change (%)')
                axes[2,2].set_ylabel('Count')
                axes[2,2].axvline(x=0, color='red', linestyle='--')
            else:
                axes[2,2].text(0.5, 0.5, 'No optimization data', ha='center', va='center', transform=axes[2,2].transAxes)
                axes[2,2].set_title('Radius Change Distribution')
            
            # Row 4: Analysis and Statistics
            # Detection method breakdown
            canny_count = processed_results['circle_sources'].count('Canny')
            watershed_count = processed_results['circle_sources'].count('Watershed')
            axes[3,0].pie([canny_count, watershed_count], labels=['Canny', 'Watershed'], 
                         colors=['lightgreen', 'lightcoral'], autopct='%1.1f%%')
            axes[3,0].set_title('Detection Method Breakdown')
            
            # Position movement statistics
            moved_count = sum(1 for pos_data in processed_results['position_optimization_data'] if pos_data['movement_distance'] > 0)
            total_count = len(processed_results['position_optimization_data'])
            axes[3,1].pie([moved_count, total_count - moved_count], labels=['Moved', 'Stationary'], 
                         colors=['red', 'green'], autopct='%1.1f%%')
            axes[3,1].set_title('Position Movement Breakdown')
            
            # Final black percentage distribution
            if len(df) > 0:
                axes[3,2].hist(df['final_black_percentage'], bins=20, color='lightgreen', edgecolor='black')
                axes[3,2].set_title('Final Black Percentage Distribution')
                axes[3,2].set_xlabel('Black Pixels (%)')
                axes[3,2].set_ylabel('Count')
                axes[3,2].axvline(x=98, color='red', linestyle='--', label='Target (98%)')
                axes[3,2].legend()
            else:
                axes[3,2].text(0.5, 0.5, 'No data available', ha='center', va='center', transform=axes[3,2].transAxes)
                axes[3,2].set_title('Final Black Percentage Distribution')
        
        plt.tight_layout()
        
        # Save the comprehensive visualization with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%m_%d_%H_%M")
        filename = f"COMPLETE_PIPELINE_VISUALIZATION_{timestamp}.png"
        save_path = os.path.join(debug_folder, filename)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Saved comprehensive pipeline visualization: {save_path}")
        
        # Close the figure to free memory
        plt.close()
        
        # Create watershed debug visualization (similar to MAC_Canny_w_Watershed.py output)
        if 'watershed_debug_images' in processed_results and processed_results['watershed_debug_images']:
            print("Creating watershed debug visualization...")
            
            # Create watershed debug figure (4x3 grid)
            fig_ws, axes_ws = plt.subplots(4, 3, figsize=(15, 12))
            fig_ws.suptitle('Watershed Processing Pipeline Debug', fontsize=14)
            
            # Row 1: Original and preprocessing
            axes_ws[0,0].imshow(processed_results['watershed_debug_images']['original'])
            axes_ws[0,0].set_title('Original Image')
            axes_ws[0,0].axis('off')
            
            axes_ws[0,1].imshow(processed_results['watershed_debug_images']['threshold'], cmap='gray')
            axes_ws[0,1].set_title('Threshold')
            axes_ws[0,1].axis('off')
            
            axes_ws[0,2].imshow(processed_results['watershed_debug_images']['opening'], cmap='gray')
            axes_ws[0,2].set_title('Morphological Opening')
            axes_ws[0,2].axis('off')
            
            # Row 2: Distance transform and markers
            axes_ws[1,0].imshow(processed_results['watershed_debug_images']['sure_background'], cmap='gray')
            axes_ws[1,0].set_title('Sure Background')
            axes_ws[1,0].axis('off')
            
            axes_ws[1,1].imshow(processed_results['watershed_debug_images']['distance_transform'], cmap='hot')
            axes_ws[1,1].set_title('Distance Transform')
            axes_ws[1,1].axis('off')
            
            axes_ws[1,2].imshow(processed_results['watershed_debug_images']['sure_foreground'], cmap='gray')
            axes_ws[1,2].set_title('Sure Foreground')
            axes_ws[1,2].axis('off')
            
            # Row 3: Unknown region and markers
            axes_ws[2,0].imshow(processed_results['watershed_debug_images']['unknown_region'], cmap='gray')
            axes_ws[2,0].set_title('Unknown Region')
            axes_ws[2,0].axis('off')
            
            # Show detailed markers visualization if available
            if 'markers_visualization' in processed_results['watershed_debug_images']:
                axes_ws[2,1].imshow(processed_results['watershed_debug_images']['markers_visualization'])
                axes_ws[2,1].set_title('Markers Visualization (Yellow=Connected, Cyan=Hough)')
            else:
                axes_ws[2,1].imshow(processed_results['watershed_debug_images']['markers'], cmap='nipy_spectral')
                axes_ws[2,1].set_title('Markers')
            axes_ws[2,1].axis('off')
            
            axes_ws[2,2].imshow(processed_results['watershed_debug_images']['watershed_result'], cmap='nipy_spectral')
            axes_ws[2,2].set_title('Watershed Result')
            axes_ws[2,2].axis('off')
            
            # Row 4: Canny edges and final comparison
            axes_ws[3,0].imshow(processed_results['canny_edges'], cmap='gray')
            axes_ws[3,0].set_title('Canny Edges')
            axes_ws[3,0].axis('off')
            
            # Combined detection visualization
            combined_viz = original_img.copy()
            for circle in processed_results['canny_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(combined_viz, (x, y), r, (0, 255, 0), 2)  # Green for Canny
            for circle in processed_results['watershed_circles']:
                x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
                cv2.circle(combined_viz, (x, y), r, (255, 0, 0), 2)  # Red for Watershed
            axes_ws[3,1].imshow(combined_viz)
            axes_ws[3,1].set_title('Combined Detection')
            axes_ws[3,1].axis('off')
            
            # Final result
            axes_ws[3,2].imshow(processed_results['final_image'])
            axes_ws[3,2].set_title('Final Optimized Result')
            axes_ws[3,2].axis('off')
            
            plt.tight_layout()
            
            # Save watershed debug visualization
            ws_filename = f"WATERSHED_DEBUG_VISUALIZATION_{timestamp}.png"
            ws_save_path = os.path.join(debug_folder, ws_filename)
            plt.savefig(ws_save_path, dpi=300, bbox_inches='tight')
            print(f"Saved watershed debug visualization: {ws_save_path}")
            
            plt.close()
        
        print(f"Saved comprehensive debug visualization to: {debug_folder}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error saving processed images: {e}")
        return False

def process_and_save_to_lacie(input_source_path):
    """Complete pipeline: copy input, process, save outputs"""
    try:
        print(f"Starting complete pipeline...")
        print(f"  Input source: {input_source_path}")
        
        # Load config
        config = get_imaging_config()
        output_root = config.get('output_root', '/Volumes/LaCie/Shadowgraph')
        
        # 1. Create main folder structure (timestamped)
        now = datetime.now()
        month_folder = now.strftime("%b_%Y")
        day_folder = now.strftime("%d_%b")
        timestamp_folder = now.strftime("%b_%d_%Y_%H_%M_%S")
        
        shadowgraph_path = output_root
        month_path = os.path.join(shadowgraph_path, month_folder)
        day_path = os.path.join(month_path, day_folder)
        final_folder_path = os.path.join(day_path, timestamp_folder)
        
        print(f"Creating folder structure...")
        print(f"  Shadowgraph folder: Shadowgraph")
        print(f"  Month folder: {month_folder}")
        print(f"  Day folder: {day_folder}")
        print(f"  Timestamp folder: {timestamp_folder}")
        
        # Create all folders
        os.makedirs(shadowgraph_path, exist_ok=True)
        os.makedirs(month_path, exist_ok=True)
        os.makedirs(day_path, exist_ok=True)
        os.makedirs(final_folder_path, exist_ok=True)
        
        print(f"Created main folder structure: {final_folder_path}")
        
        # 2. Copy input file to Input/ subfolder
        input_destination = copy_input_to_lacie(input_source_path, final_folder_path)
        
        # 3. Create Outputs/ subfolder
        outputs_folder = create_outputs_folder(final_folder_path)
        
        # 4. Run Canny_W_Watershed processing
        print(f"Running Canny_W_Watershed processing...")
        processed_results = process_image(input_destination, outputs_folder)
        processed_results['input_path'] = input_destination  # Add input path to results
        
        print(f"Processing complete!")
        
        # 5. Save all outputs to Outputs/ subfolder
        print(f"Saving all outputs to LaCie...")
        save_success = save_processed_images_to_lacie(processed_results, outputs_folder)
        
        if save_success:
            print(f"[SUCCESS] Complete pipeline finished successfully!")
            
            # Automatically open the annotated image to show results
            try:
                import matplotlib.pyplot as plt
                annotated_image_path = os.path.join(outputs_folder, "annotated_droplets_combined.png")
                
                print(f"Opening annotated image for review...")
                plt.figure(figsize=(10, 10))
                plt.title('Annotated Droplets (Watershed + Canny)')
                plt.imshow(processed_results['final_image'])
                plt.axis('off')
                plt.show()
                print(f"Annotated image displayed successfully")
                
            except Exception as e:
                print(f"[WARNING] Could not display image: {e}")
                print(f"   Image saved to: {os.path.join(outputs_folder, 'FINAL_OPTIMIZED_RESULT.png')}")
            
            # Show the complete folder structure
            print(f"\n📂 Complete folder structure created:")
            print(f"  {output_root}/")
            print(f"  └── {month_folder}/")
            print(f"      └── {day_folder}/")
            print(f"          └── {timestamp_folder}/")
            print(f"              ├── Input/")
            print(f"              │   └── input.tiff")
            print(f"              └── Outputs/")
            print(f"                  ├── FINAL_OPTIMIZED_RESULT.png")
            print(f"                  ├── FINAL_ANALYSIS.csv")
            print(f"                  ├── CANNY_EDGES.png")
            print(f"                  ├── CANNY_DETECTION.png")
            print(f"                  ├── WATERSHED_DETECTION.png")
            print(f"                  ├── POSITION_MOVEMENT.png")
            print(f"                  └── debug_images/")
            print(f"                      ├── COMPLETE_PIPELINE_VISUALIZATION_MM_DD_HH_MM.png")
            print(f"                      └── WATERSHED_DEBUG_VISUALIZATION_MM_DD_HH_MM.png")
            
            return True
        else:
            print(f"[ERROR] Failed to save processed outputs")
            return False
        
    except Exception as e:
        print(f"[ERROR] Error in complete pipeline: {e}")
        return False

# Removed check_paths() - no longer needed with config system

# Removed save_to_lacie_drive() - functionality moved to process_and_save_to_lacie()

def main():
    """Main function to run the image processing pipeline"""
    print("HPATR Image Processing Pipeline")
    print("=" * 60)
    
    # Load config
    config = get_imaging_config()
    default_input_dir = config.get('default_input_dir', '/Volumes/LaCie/Phantom/Flashed_Output')
    default_input_file = config.get('default_input_file', 'flashed_output.tiff')
    output_root = config.get('output_root', '/Volumes/LaCie/Shadowgraph')
    
    # Check if output root exists
    if not os.path.exists(output_root):
        print(f"[WARNING] Output root not found: {output_root}")
        print("   Creating directory...")
        os.makedirs(output_root, exist_ok=True)
    
    print(f"Output root: {output_root}")
    
    # Determine input source (use command line arg if provided, else config default)
    if len(sys.argv) > 1:
        input_source = sys.argv[1]
        print(f"  Using command line input: {input_source}")
    else:
        input_source = os.path.join(default_input_dir, default_input_file)
        print(f"  Using config default: {input_source}")
    
    # Check if input file exists
    if not os.path.exists(input_source):
        print(f"[ERROR] Input file not found: {input_source}")
        print(f"   Please check config/paths.yaml or provide input file as argument")
        return
    
    print(f"Input file found: {input_source}")
    
    # Run the complete pipeline
    print(f"\nStarting complete pipeline...")
    success = process_and_save_to_lacie(input_source)
    
    if success:
        print("\n[SUCCESS] Complete pipeline finished successfully!")
    else:
        print("\n[ERROR] Pipeline failed!")

if __name__ == "__main__":
    main()