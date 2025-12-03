import customtkinter as ctk
from tkinter import messagebox
import serial
import threading
import time
import os
import json
import pandas as pd
from datetime import datetime
from serial.tools import list_ports
import openpyxl
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
import matplotlib
import numpy as np
import platform
from PIL import Image, ImageTk
import sys

# Add src directory to path for config imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config_loader import get_gui_config, resolve_path, find_lacie_drive
    GUI_CONFIG = get_gui_config()
except ImportError:
    # Fallback if config not available
    GUI_CONFIG = {}
    print("[WARNING] Config loader not available, using defaults")
    # Define fallback functions
    def resolve_path(path_str, lacie_base=None):
        return path_str
    def find_lacie_drive():
        return None

# Phantom SDK detection and import HELPsz
PHANTOM_SDK_AVAILABLE = False
try:
    from pyphantom import Phantom, utils, cine
    PHANTOM_SDK_AVAILABLE = True
    print(" Phantom SDK (pyphantom) detected and loaded")
except ImportError as e:
    print(f"[WARNING] Phantom SDK (pyphantom) not available: {e}")
    print("  Camera functionality will be limited. Install pyphantom to enable full camera control.")

# Py`VISA` detection and import (for Tektronix AFG1062)
PYVISA_AVAILABLE = False
try:
    import pyvisa
    PYVISA_AVAILABLE = True
    print(" PyVISA detected and loaded")
except ImportError:
    print("[WARNING] PyVISA not available - AFG1062 functionality will be disabled")
    print("  Install with: pip install pyvisa")
    print("  Note: You may also need to install VISA drivers from:")
    print("    - National Instruments: https://www.ni.com/en-us/support/downloads/drivers/download.ni-visa.html")
    print("    - Or Tektronix VISA: https://www.tek.com/en/support/software/visa")

# Set appearance mode and color theme
ctk.set_appearance_mode("dark")  # Modes: "System" (default), "Dark", "Light"
ctk.set_default_color_theme("dark-blue")  # Themes: "blue" (default), "green", "dark-blue"

# TODO LIST - Future Improvements 
# =============================
# 1. Adding in box for pressure controller controlling
# 2. Make notes section larger
# 3. Edit notes page to work better (more info, maybe moving to LACIE drive))
# =============================

def log_serial(message, log_file=None):
    """Log serial messages to file"""
    if log_file is None:
        # Use config default or fallback
        log_file = GUI_CONFIG.get('serial_log_file', 'serial_log.txt')
    abs_path = os.path.abspath(log_file)
    if not os.path.exists(log_file):
        print(f"Serial log will be written to: {abs_path}")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

# ========== Subsystem Classes ==========

class ArduinoController:
    def __init__(self, port, baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def connect(self):
        try:
            print(f"Attempting to connect to {self.port}")
            self.ser = serial.Serial(self.port, self.baudrate, timeout=5)
            time.sleep(2)
            
            # Read until ARDUINO_READY is seen, ignoring other lines (e.g., PRESSURE_READING)
            start_time = time.time()
            timeout_s = 8  # allow a few seconds for periodic handshake
            detected = False
            
            # Drain any existing buffered bytes to start fresh
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass
            
            while time.time() - start_time < timeout_s and not detected:
                # Use 'utf-8' with 'replace' to handle Unicode characters gracefully
                line = self.ser.readline().decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                log_serial(f"Received on connect: {line}")
                print(f"DEBUG: On connect got '{line}'")
                if "ARDUINO_READY" in line:
                    detected = True
                    break
                # If a lot of chatter (e.g., PRESSURE_READING), keep looping
                time.sleep(0.05)
            
            if not detected:
                raise RuntimeError("No Arduino detected on this port.")
                    
        except serial.SerialException as e:
            if "Resource busy" in str(e):
                raise RuntimeError(f"Port {self.port} is busy. Close Arduino IDE and try again.")
            else:
                raise RuntimeError(f"Could not open serial port {self.port}: {e}")

    def send_motor_command(self, speed, distance):
        command = f"SPEED:{speed};DIST:{distance}\n"
        print(f"Sending command: {command.strip()}")
        print(f"Command bytes: {command.encode()}")
        self.ser.write(command.encode())
        log_serial(f"Sent: {command.strip()}")

        time.sleep(1)
        print("Checking for Arduino responses...")
        while self.ser.in_waiting > 0:
            response = self.ser.readline().decode().strip()
            if response:
                log_serial(f"Arduino response: {response}")
                print(f"Arduino: {response}")

    def send_pressure_command(self, pressure):
        command = f"PRESSURE:{pressure}\n"
        print(f"Sending pressure command: {command.strip()}")
        self.ser.write(command.encode())
        log_serial(f"Sent: {command.strip()}")

    def send_pressure_off_command(self):
        command = "PRESSURE_OFF\n"
        print(f"Sending pressure off command: {command.strip()}")
        self.ser.write(command.encode())
        log_serial(f"Sent: {command.strip()}")

    def disconnect(self):
        if hasattr(self, 'ser') and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed")

    def reset_state(self):
        try:
            if hasattr(self, 'ser') and self.ser.is_open:
                self.ser.write("RESET:1\n".encode())
                print("Sent RESET command to Arduino")
                
                start_time = time.time()
                timeout = 5
                reset_complete = False
                
                while time.time() - start_time < timeout and not reset_complete:
                    if self.ser.in_waiting > 0:
                        response = self.ser.readline().decode().strip()
                        if response:
                            print(f"Reset response: {response}")
                            if "ARDUINO_READY" in response:
                                reset_complete = True
                                print("Arduino reset completed successfully")
                                break
                    time.sleep(0.1)
                
                if not reset_complete:
                    print("Warning: Arduino reset timeout - may not be ready for next experiment")
                else:
                    print("Arduino state reset and ready for next experiment")
                    
        except Exception as e:
            print(f"Reset error: {e}")

# ========== Phantom Camera Controller ==========

class PhantomController:
    """Wrapper class for Phantom SDK camera control"""
    
    def __init__(self):
        self.ph = None
        self.cam = None
        self.current_cine = None
        self.is_connected = False
        self.is_recording = False
        self.recording_started = False
        
    def connect(self, ip_address=None, camera_index=0):
        """Connect to a Phantom camera
        
        Args:
            ip_address: Optional IP address string (e.g., "100.100.100.1")
            camera_index: Camera index to connect to (default: 0)
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if not PHANTOM_SDK_AVAILABLE:
            raise RuntimeError("Phantom SDK (pyphantom) is not installed")
        
        try:
            # Create Phantom object
            self.ph = Phantom()
            
            # Discover cameras
            discovered = self.ph.discover(print_list=False)
            cam_count = self.ph.camera_count
            
            print(f"Found {cam_count} camera(s)")
            
            if cam_count == 0:
                # No cameras found - add simulated camera for testing
                print("No cameras found, adding simulated camera")
                self.ph.add_simulated_camera()
                cam_count = self.ph.camera_count
            
            # Connect to camera by index
            if camera_index >= cam_count:
                camera_index = 0
                print(f"Camera index out of range, using index 0")
            
            self.cam = self.ph.Camera(camera_index)
            self.is_connected = True
            
            # Get camera info
            try:
                model = self.cam.get_selector_string(utils.CamSelector.gsModel)
                ip = self.cam.get_selector_string(utils.CamSelector.gsIPAddress)
                print(f"Connected to camera: {model} at {ip}")
            except:
                print("Connected to camera (info unavailable)")
            
            return True
            
        except Exception as e:
            print(f"Error connecting to camera: {e}")
            self.disconnect()
            raise
    
    def configure(self, width, height, fps, exposure_us, partition_count=1, post_trigger_frames=0):
        """Configure camera settings
        
        Note: The camera may automatically adjust frame rate and exposure limits
        based on resolution. This method sets resolution first, then attempts to
        set frame rate and exposure. If values are out of range, the camera will
        reject them and raise an exception.
        
        Args:
            width: Image width in pixels
            height: Image height in pixels
            fps: Frame rate (frames per second) - may be adjusted by camera
            exposure_us: Exposure time in microseconds - must be < 1/fps
            partition_count: Number of partitions (default: 1)
            post_trigger_frames: Post-trigger frames (default: 0)
        
        Returns:
            dict: Actual values set by camera (may differ from requested)
        """
        if not self.is_connected or not self.cam:
            raise RuntimeError("Camera not connected")
        
        try:
            # Set resolution FIRST - this may change available frame rate limits
            self.cam.resolution = (int(width), int(height))
            actual_resolution = self.cam.resolution
            print(f"Resolution set to: {actual_resolution[0]}x{actual_resolution[1]}")
            
            # Set partition count
            self.cam.partition_count = int(partition_count)
            actual_partitions = self.cam.partition_count
            
            # Set post-trigger frames
            self.cam.post_trigger_frames = int(post_trigger_frames)
            actual_post_trigger = self.cam.post_trigger_frames
            
            # Try to set frame rate (camera may adjust if out of range)
            try:
                self.cam.frame_rate = float(fps)
                actual_fps = self.cam.frame_rate
                if abs(actual_fps - float(fps)) > 0.1:
                    print(f"Warning: Frame rate adjusted from {fps} to {actual_fps} fps")
            except Exception as e:
                raise RuntimeError(f"Invalid frame rate {fps} fps for this resolution: {e}")
            
            # Try to set exposure (must be less than frame period = 1/fps)
            max_exposure = (1.0 / actual_fps) * 1e6  # Convert to microseconds
            if exposure_us >= max_exposure:
                raise RuntimeError(
                    f"Exposure {exposure_us}μs exceeds maximum for {actual_fps} fps "
                    f"(max: {max_exposure:.1f}μs = {1.0/actual_fps*1000:.2f}ms)"
                )
            
            try:
                self.cam.exposure = float(exposure_us)
                actual_exposure = self.cam.exposure
                if abs(actual_exposure - float(exposure_us)) > 1.0:
                    print(f"Warning: Exposure adjusted from {exposure_us} to {actual_exposure}μs")
            except Exception as e:
                raise RuntimeError(f"Invalid exposure {exposure_us}μs: {e}")
            
            # Return actual values set by camera
            actual_values = {
                'resolution': actual_resolution,
                'frame_rate': actual_fps,
                'exposure': actual_exposure,
                'partition_count': actual_partitions,
                'post_trigger_frames': actual_post_trigger
            }
            
            print(f"Camera configured: {actual_resolution[0]}x{actual_resolution[1]} @ "
                  f"{actual_fps:.1f} fps, exposure: {actual_exposure:.1f}μs")
            return actual_values
            
        except RuntimeError:
            # Re-raise our custom errors
            raise
        except Exception as e:
            print(f"Error configuring camera: {e}")
            raise RuntimeError(f"Camera configuration failed: {e}")
    
    def start_recording(self):
        """Start recording (arm the camera)"""
        if not self.is_connected or not self.cam:
            raise RuntimeError("Camera not connected")
        
        try:
            self.cam.record()
            self.is_recording = True
            self.recording_started = False
            print("Camera recording started (armed)")
            return True
        except Exception as e:
            print(f"Error starting recording: {e}")
            self.is_recording = False
            raise
    
    def trigger(self):
        """Trigger the camera to capture"""
        if not self.is_connected or not self.cam:
            raise RuntimeError("Camera not connected")
        
        if not self.is_recording:
            raise RuntimeError("Camera not recording - call start_recording() first")
        
        try:
            self.cam.trigger()
            self.recording_started = True
            print("Camera triggered")
            return True
        except Exception as e:
            print(f"Error triggering camera: {e}")
            raise
    
    def save_recording(self, output_path, cine_index=1, file_format='cine', frame_range=None):
        """Save the recorded cine to file
        
        Args:
            output_path: Full path to save file (without extension)
            cine_index: Cine index in camera RAM (default: 1)
            file_format: File format ('cine', 'tiff', 'avi', etc.) or FileTypeEnum value
            frame_range: Optional tuple (start_frame, end_frame) or FrameRange object
        """
        if not self.is_connected or not self.cam:
            raise RuntimeError("Camera not connected")
        
        try:
            # Get cine object
            self.current_cine = self.cam.Cine(cine_index)
            
            # Determine file format
            if file_format == 'cine':
                fmt = utils.FileTypeEnum(0)  # CineRaw
            elif file_format == 'tiff' or file_format == 'tif':
                fmt = utils.FileTypeEnum(-8)  # TIFF sequence
            elif file_format == 'avi':
                fmt = utils.FileTypeEnum(-7)  # AVI
            else:
                fmt = utils.FileTypeEnum(0)  # Default to CineRaw
            
            # Set frame range
            if frame_range is None:
                # Save all frames
                save_range = utils.FrameRange(self.current_cine.range.first_image, 
                                            self.current_cine.range.last_image)
            elif isinstance(frame_range, tuple):
                save_range = utils.FrameRange(frame_range[0], frame_range[1])
            else:
                save_range = frame_range
            
            # Set save parameters
            self.current_cine.save_name = output_path
            self.current_cine.save_type = fmt
            self.current_cine.save_range = save_range
            
            # Save (blocking)
            self.current_cine.save()
            
            print(f"Recording saved to: {output_path}")
            return True
            
        except Exception as e:
            print(f"Error saving recording: {e}")
            raise
    
    def abort(self):
        """Abort current recording"""
        if not self.is_connected or not self.cam:
            return False
        
        try:
            # Stop recording if active
            if self.is_recording:
                # Clear RAM to stop recording
                self.cam.clear_ram()
                self.is_recording = False
                self.recording_started = False
                print("Recording aborted")
            return True
        except Exception as e:
            print(f"Error aborting recording: {e}")
            return False
    
    def ping(self):
        """Check camera connection status"""
        if not self.is_connected or not self.cam:
            return False
        
        try:
            # Try to get a simple property to verify connection
            _ = self.cam.frame_rate
            return True
        except Exception as e:
            print(f"Camera ping failed: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """Disconnect from camera"""
        try:
            if self.cam:
                self.cam.close()
                self.cam = None
            if self.ph:
                self.ph.close()
                self.ph = None
            self.is_connected = False
            self.is_recording = False
            self.recording_started = False
            self.current_cine = None
            print("Camera disconnected")
        except Exception as e:
            print(f"Error disconnecting camera: {e}")
    
    def get_camera_info(self):
        """Get camera information as a dictionary"""
        if not self.is_connected or not self.cam:
            return None
        
        try:
            info = {
                'model': self.cam.get_selector_string(utils.CamSelector.gsModel),
                'ip_address': self.cam.get_selector_string(utils.CamSelector.gsIPAddress),
                'resolution': self.cam.resolution,
                'frame_rate': self.cam.frame_rate,
                'exposure': self.cam.exposure,
                'partition_count': self.cam.partition_count,
            }
            return info
        except Exception as e:
            print(f"Error getting camera info: {e}")
            return None

# ========== Tektronix AFG1062 Controller ==========

class AFGController:
    """Controller class for Tektronix AFG1062 Arbitrary Function Generator"""
    
    def __init__(self):
        self.rm = None
        self.afg = None
        self.is_connected = False
        self.pulse_duration = 0.001  # Default 1ms pulse duration
        self.pulse_amplitude = 5.0   # Default 5V amplitude
        self.pulse_frequency = 1000  # Default 1kHz frequency
        
    def connect(self, resource_name=None):
        """Connect to AFG1062 via USB
        
        Args:
            resource_name: Optional VISA resource name (e.g., 'USB0::0x0699::0x0346::C010123::INSTR')
                          If None, will attempt to auto-detect
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if not PYVISA_AVAILABLE:
            raise RuntimeError("PyVISA is not installed. Install with: pip install pyvisa")
        
        try:
            # Initialize VISA resource manager
            self.rm = pyvisa.ResourceManager()
            
            # List available resources
            resources = self.rm.list_resources()
            print(f"Available VISA resources: {resources}")
            
            # Find AFG1062 (look for Tektronix vendor ID 0x0699)
            if resource_name:
                # Use provided resource name
                if resource_name in resources:
                    self.afg = self.rm.open_resource(resource_name)
                else:
                    raise RuntimeError(f"Resource '{resource_name}' not found")
            else:
                # Auto-detect AFG1062
                afg_found = False
                for res in resources:
                    if 'USB' in res.upper() or '0x0699' in res:
                        try:
                            self.afg = self.rm.open_resource(res)
                            # Try to identify as AFG1062
                            idn = self.afg.query('*IDN?')
                            print(f"Found device: {idn}")
                            if 'AFG1062' in idn or 'AFG' in idn:
                                afg_found = True
                                break
                        except:
                            if self.afg:
                                self.afg.close()
                            self.afg = None
                            continue
                
                if not afg_found:
                    raise RuntimeError("AFG1062 not found. Please connect via USB and ensure drivers are installed.")
            
            # Set timeout
            self.afg.timeout = 5000  # 5 second timeout
            
            # Don't reset - preserve user settings
            # If you need a reset, uncomment: self.afg.write('*RST')
            
            # Verify connection
            idn = self.afg.query('*IDN?')
            print(f"Connected to: {idn}")
            
            self.is_connected = True
            return True
            
        except Exception as e:
            print(f"Error connecting to AFG1062: {e}")
            self.disconnect()
            raise
    
    def configure_pulse(self, duration_seconds, amplitude_volts=5.0, frequency_hz=1000, channel=1):
        """Configure square wave pulse settings (single pulse on trigger)
        
        Args:
            duration_seconds: Pulse duration in seconds (e.g., 0.001 for 1ms)
            amplitude_volts: Pulse amplitude in volts (default: 5.0V)
            frequency_hz: Not used for square wave pulse (kept for compatibility)
            channel: Channel number (1 or 2, default: 1)
        """
        if not self.is_connected or not self.afg:
            raise RuntimeError("AFG1062 not connected")
        
        if channel not in [1, 2]:
            raise ValueError("Channel must be 1 or 2")
        
        try:
            # Store settings
            self.pulse_duration = duration_seconds
            self.pulse_amplitude = amplitude_volts
            self.channel = channel
            
            # Channel prefix for SCPI commands (SOUR1: or SOUR2:)
            ch_prefix = f'SOUR{channel}:'
            
            # Set function to SQUARE wave
            self.afg.write(f'{ch_prefix}FUNC SQUARE')
            
            # For a square wave pulse that's HIGH for duration_seconds:
            # Set period = 2 * duration_seconds (so high time = low time = duration_seconds)
            # Then 1 cycle in burst mode = 2 * duration_seconds total
            # High portion = duration_seconds, which is what we want
            period = 2.0 * duration_seconds
            frequency = 1.0 / period
            self.afg.write(f'{ch_prefix}FREQ {frequency}')
            
            # Set amplitude
            self.afg.write(f'{ch_prefix}VOLT {amplitude_volts}')
            
            # Set offset to amplitude/2 (so square wave goes from 0 to amplitude)
            # Actually, let's set it so the low is 0V and high is amplitude
            self.afg.write(f'{ch_prefix}VOLT:OFFS {amplitude_volts/2.0}')
            
            # Enable BURST mode with 1 cycle (single pulse)
            self.afg.write(f'{ch_prefix}BURS:STAT ON')
            self.afg.write(f'{ch_prefix}BURS:MODE TRIG')  # Burst mode: triggered
            self.afg.write(f'{ch_prefix}BURS:NCYC 1')  # 1 cycle = single pulse
            self.afg.write(f'{ch_prefix}BURS:TRIG:SOUR MAN')  # Burst trigger source: manual/software
            
            # Set the main trigger source to MANUAL (required for software triggering)
            self.afg.write(f'{ch_prefix}TRIG:SOUR MAN')  # Manual trigger source (for software trigger)
            
            # Verify configuration
            try:
                burst_stat = self.afg.query(f'{ch_prefix}BURS:STAT?')
                burst_mode = self.afg.query(f'{ch_prefix}BURS:MODE?')
                trig_source = self.afg.query(f'{ch_prefix}TRIG:SOUR?')
                print(f"Burst status: {burst_stat.strip()}, Mode: {burst_mode.strip()}, Trigger: {trig_source.strip()}")
            except Exception as e:
                print(f"Could not query configuration: {e}")
            
            print(f"AFG1062 CH{channel} configured: Square wave, {duration_seconds*1000:.3f}ms pulse, {amplitude_volts}V")
            
        except Exception as e:
            print(f"Error configuring AFG1062: {e}")
            raise
    
    def enable_output(self, channel=1):
        """Enable AFG output (but in burst mode, won't output until triggered)
        
        Args:
            channel: Channel number (1 or 2, default: 1)
        """
        if not self.is_connected or not self.afg:
            raise RuntimeError("AFG1062 not connected")
        
        if channel not in [1, 2]:
            raise ValueError("Channel must be 1 or 2")
        
        try:
            self.afg.write(f'SOUR{channel}:OUTP ON')
            print(f"AFG1062 CH{channel} output enabled (burst mode - waits for trigger)")
        except Exception as e:
            print(f"Error enabling AFG1062 output: {e}")
            raise
    
    def disable_output(self, channel=1):
        """Disable AFG output
        
        Args:
            channel: Channel number (1 or 2, default: 1)
        """
        if not self.is_connected or not self.afg:
            return
        
        if channel not in [1, 2]:
            return
        
        try:
            self.afg.write(f'SOUR{channel}:OUTP OFF')
            print(f"AFG1062 CH{channel} output disabled")
        except Exception as e:
            print(f"Error disabling AFG1062 output: {e}")
    
    def trigger(self, channel=1):
        """Send software trigger to AFG (triggers single pulse in burst mode)
        
        Args:
            channel: Channel number (1 or 2, default: 1)
        """
        if not self.is_connected or not self.afg:
            raise RuntimeError("AFG1062 not connected")
        
        if channel not in [1, 2]:
            raise ValueError("Channel must be 1 or 2")
        
        try:
            ch_prefix = f'SOUR{channel}:'
            
            # Ensure output is enabled (critical for burst mode)
            output_state = self.afg.query(f'{ch_prefix}OUTP?')
            print(f"Output state before trigger: {output_state.strip()}")
            if 'OFF' in output_state.upper():
                self.afg.write(f'{ch_prefix}OUTP ON')
                print(f"Output was off, enabled it")
                time.sleep(0.1)  # Give it time to enable
            
            # Verify burst mode is on
            burst_stat = self.afg.query(f'{ch_prefix}BURS:STAT?')
            burst_mode = self.afg.query(f'{ch_prefix}BURS:MODE?')
            burst_ncyc = self.afg.query(f'{ch_prefix}BURS:NCYC?')
            print(f"Burst status: {burst_stat.strip()}, Mode: {burst_mode.strip()}, Cycles: {burst_ncyc.strip()}")
            
            if 'OFF' in burst_stat.upper():
                self.afg.write(f'{ch_prefix}BURS:STAT ON')
                print(f"Burst was off, enabled it")
                time.sleep(0.1)
            
            # Send trigger command - use global *TRG command (recommended for manual trigger)
            # This is the standard SCPI command for manual triggering
            self.afg.write('*TRG')
            print(f"AFG1062 CH{channel} triggered via *TRG")
            
            # Small delay to ensure command is processed
            time.sleep(0.01)
            
        except Exception as e:
            print(f"Error triggering AFG1062: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def disconnect(self):
        """Disconnect from AFG1062"""
        try:
            if self.afg:
                # Disable output on both channels before disconnecting (if channel info available)
                try:
                    if hasattr(self, 'channel'):
                        self.afg.write(f'SOUR{self.channel}:OUTP OFF')
                    else:
                        # Try both channels if we don't know which was used
                        self.afg.write('SOUR1:OUTP OFF')
                        self.afg.write('SOUR2:OUTP OFF')
                except:
                    pass  # Ignore errors when disabling output
                self.afg.close()
                self.afg = None
            if self.rm:
                self.rm.close()
                self.rm = None
            self.is_connected = False
            print("AFG1062 disconnected")
        except Exception as e:
            print(f"Error disconnecting AFG1062: {e}")

# ========== Modern GUI Application ==========

class ModernExperimentControlApp:
    def get_serial_ports(self):
        ports = serial.tools.list_ports.comports()
        result = []
        for p in ports:
            dev = p.device  # e.g., "COM3", "/dev/tty.usbmodem..."
            desc = (p.description or "").lower()
            if dev.upper().startswith("COM") or "usb" in desc or "serial" in desc:
                result.append(dev)
        return result
    
    def refresh_ports(self):
        ports = self.get_serial_ports()
        self.arduino_port.configure(values=ports)
        
        if ports:
            self.arduino_port.set(ports[0])
            print(f"Refreshed and auto-selected port: {ports[0]}")
        else:
            print("No serial ports available after refresh")
    
    def __init__(self, master):
        self.master = master
        master.title("Atomisation Control Panel")
        
        # Set window icon
        self.temp_ico_path = None  # Track temporary ICO file for cleanup
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "Dashboard_Icon.png")
            if os.path.exists(icon_path):
                # Load image with PIL and resize to standard icon size
                pil_image = Image.open(icon_path)
                # Convert to ICO format for Windows
                ico_path = os.path.join(os.path.dirname(__file__), "Dashboard_Icon_temp.ico")
                pil_image.save(ico_path, format='ICO')
                self.temp_ico_path = ico_path  # Save for cleanup
                
                # Use iconbitmap for Windows compatibility
                master.wm_iconbitmap(ico_path)
                
                # Also set using wm_iconphoto for additional support
                pil_image = pil_image.resize((32, 32), Image.Resampling.LANCZOS)
                self.window_icon = ImageTk.PhotoImage(pil_image)
                master.iconphoto(False, self.window_icon)
                
                print(f" Window icon loaded: {icon_path}")
            else:
                print(f"[WARNING] Icon file not found: {icon_path}")
        except Exception as e:
            print(f"[WARNING] Could not load window icon: {e}")
        
        # Platform detection
        self.is_windows = platform.system() == "Windows"
        # Camera available if Windows AND SDK is installed
        self.camera_available = self.is_windows and PHANTOM_SDK_AVAILABLE
        
        # Initialize Phantom camera controller
        self.phantom_camera = None
        if PHANTOM_SDK_AVAILABLE:
            try:
                self.phantom_camera = PhantomController()
                print(" PhantomController initialized")
            except Exception as e:
                print(f"[WARNING] Failed to initialize PhantomController: {e}")
                self.camera_available = False
        else:
            print("[WARNING] Phantom SDK not available - camera controls will be disabled")
        
        # Center window on screen and bring to front
        window_width = 1500
        window_height = 1020  # Fixed height instead of screen-based
        screen_width = master.winfo_screenwidth()
        screen_height = master.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2 - 50  # Move up by 100px
        master.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Force window to front with multiple methods
        master.lift()
        master.attributes('-topmost', True)
        master.focus_force()
        master.grab_set()
        master.after(100, lambda: master.attributes('-topmost', False))
        master.after(100, lambda: master.grab_release())

        # Variables
        self.arduino_port = ctk.StringVar()
        self.motor_speed = ctk.StringVar()
        self.motor_distance = ctk.StringVar()
        self.cumulative_distance = 0.0
        self.status = ctk.StringVar(value="Awaiting input...")
        self.pressure_value = ctk.StringVar()
        self.nozzle_number = ctk.StringVar()
        self.orifice_size = ctk.StringVar()
        
        # Persistent Arduino connection
        self.arduino = None
        self.serial_reader_thread = None
        self.serial_reading_active = False
        
        # Pressure monitoring data
        # live_buffer: Always maintained, rolling 6 seconds for real-time display
        # experiment_data: Only during experiments, used for saving
        self.pressure_data = {
            'live_buffer': {'timestamps': [], 'pressures': []},  # Always-on rolling buffer
            'experiment_data': {'timestamps': [], 'pressures': []},  # Experiment-only for saving
            'experiment_active': False,
            'experiment_start_time': None,
            'live_buffer_start_time': None,  # Track when live buffer started
            'saved_graph_filename': None
        }
        # Initialize live buffer start time (will be set on first reading)
        self.pressure_data['live_buffer_start_time'] = time.time()

        # Camera Control Variables
        self.cam_ip = ctk.StringVar()
        self.cam_fps = ctk.StringVar()
        self.cam_exposure_us = ctk.StringVar()
        self.cam_width = ctk.StringVar()
        self.cam_height = ctk.StringVar()
        self.cam_seconds = ctk.StringVar()
        self.cam_output = ctk.StringVar()
        self.camera_status = ctk.StringVar(value="Camera: idle")
        self.pipeline_enabled = ctk.BooleanVar(value=False)  # Pipeline checkbox

        # AFG1062 Control Variables
        self.afg_available = PYVISA_AVAILABLE
        self.afg_controller = None
        if PYVISA_AVAILABLE:
            try:
                self.afg_controller = AFGController()
                print(" AFGController initialized")
            except Exception as e:
                print(f"[WARNING] Failed to initialize AFGController: {e}")
                self.afg_available = False
        else:
            print("[WARNING] PyVISA not available - AFG1062 controls will be disabled")
        
        self.afg_pulse_duration = ctk.StringVar(value="0.001")  # Default 1ms
        self.afg_channel = ctk.StringVar(value="CH1")  # Default to CH1
        self.afg_status = ctk.StringVar(value="AFG: Not connected")
        self.afg_resource_name = ctk.StringVar()  # For manual resource entry

        # Load persisted camera settings
        self.load_camera_settings()

        # Create main layout
        self.create_layout()

        # Auto-connect to Arduino if port is available
        ports = self.get_serial_ports()
        if ports:
            self.connect_to_arduino()

    def create_layout(self):
        # Main container with symmetric padding
        main_frame = ctk.CTkFrame(self.master)
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Create horizontal container for left image panel and right controls
        content_frame = ctk.CTkFrame(main_frame)
        content_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Left column: Shadowgraph result image display
        self.create_shadowgraph_image_panel(content_frame)

        # Right column: Create main frame for all controls (no scrolling)
        controls_frame = ctk.CTkFrame(content_frame)
        controls_frame.pack(side="right", fill="both", expand=True, padx=(10, 0), pady=5)

        # Arduino Connection Section
        self.create_arduino_section(controls_frame)
        
        # Separator - truly centered
        separator1 = ctk.CTkFrame(controls_frame, height=2, fg_color="gray")
        separator1.pack(fill="x", pady=5)
        
        # Pressure and Motor Control Sections (side-by-side)
        self.create_pressure_motor_section(controls_frame)
        
        # Separator - truly centered
        separator2 = ctk.CTkFrame(controls_frame, height=2, fg_color="gray")
        separator2.pack(fill="x", pady=5)
        
        # Experiment Parameters Section
        self.create_experiment_section(controls_frame)
        
        # Separator - truly centered
        separator3 = ctk.CTkFrame(controls_frame, height=2, fg_color="gray")
        separator3.pack(fill="x", pady=5)
        
        # Camera Control and Control Panel Sections (side-by-side)
        self.create_camera_control_section(controls_frame)
        
        # Separator - truly centered
        separator4 = ctk.CTkFrame(controls_frame, height=2, fg_color="gray")
        separator4.pack(fill="x", pady=5)
        
        # AFG1062 Control Section
        self.create_afg_section(controls_frame)
        
        # Separator - truly centered
        separator4b = ctk.CTkFrame(controls_frame, height=2, fg_color="gray")
        separator4b.pack(fill="x", pady=5)
        
        # Status and Progress Section
        self.create_status_section(controls_frame)
        
        # Separator - truly centered
        separator5 = ctk.CTkFrame(controls_frame, height=2, fg_color="gray")
        separator5.pack(fill="x", pady=5)

    def find_latest_shadowgraph_result(self):
        """Find the latest FINAL_OPTIMIZED_RESULT.png by checking latest folders (more efficient)"""
        try:
            # Get shadowgraph base path from config or use LaCie drive detection
            try:
                from config_loader import get_imaging_config
                config = get_imaging_config()
                shadowgraph_base = config.get('output_root', None)
                if shadowgraph_base:
                    shadowgraph_base = resolve_path(shadowgraph_base)
            except:
                shadowgraph_base = None
            
            # If not in config, try to find it using LaCie drive
            if not shadowgraph_base or not os.path.exists(shadowgraph_base):
                lacie_base = find_lacie_drive()
                if lacie_base:
                    shadowgraph_base = os.path.join(lacie_base, "Shadowgraph")
                else:
                    # Fallback to D:\Shadowgraph
                    shadowgraph_base = "D:\\Shadowgraph"
            
            if not os.path.exists(shadowgraph_base):
                print(f"[DEBUG] Shadowgraph base path does not exist: {shadowgraph_base}")
                return None
            
            # Find latest month folder (by modification time)
            month_folders = []
            for item in os.listdir(shadowgraph_base):
                month_path = os.path.join(shadowgraph_base, item)
                if os.path.isdir(month_path):
                    month_folders.append((month_path, os.path.getmtime(month_path)))
            
            if not month_folders:
                print(f"[DEBUG] No month folders found in {shadowgraph_base}")
                return None
            
            # Sort by modification time (latest first)
            month_folders.sort(key=lambda x: x[1], reverse=True)
            
            # Check each month folder (starting with latest) until we find a result
            for month_path, _ in month_folders:
                # Find latest day folder in this month
                day_folders = []
                for item in os.listdir(month_path):
                    day_path = os.path.join(month_path, item)
                    if os.path.isdir(day_path):
                        day_folders.append((day_path, os.path.getmtime(day_path)))
                
                if not day_folders:
                    continue
                
                # Sort by modification time (latest first)
                day_folders.sort(key=lambda x: x[1], reverse=True)
                
                # Check each day folder (starting with latest)
                for day_path, _ in day_folders:
                    # Find latest timestamp folder in this day
                    timestamp_folders = []
                    for item in os.listdir(day_path):
                        timestamp_path = os.path.join(day_path, item)
                        if os.path.isdir(timestamp_path):
                            timestamp_folders.append((timestamp_path, os.path.getmtime(timestamp_path)))
                    
                    if not timestamp_folders:
                        continue
                    
                    # Sort by modification time (latest first)
                    timestamp_folders.sort(key=lambda x: x[1], reverse=True)
                    
                    # Check each timestamp folder (starting with latest)
                    for timestamp_path, _ in timestamp_folders:
                        # Check for Outputs subfolder and FINAL_OPTIMIZED_RESULT.png
                        outputs_path = os.path.join(timestamp_path, "Outputs")
                        if os.path.isdir(outputs_path):
                            result_file = os.path.join(outputs_path, "FINAL_OPTIMIZED_RESULT.png")
                            if os.path.exists(result_file):
                                print(f"[DEBUG] Found latest shadowgraph result: {result_file}")
                                return result_file
            
            print(f"[DEBUG] No FINAL_OPTIMIZED_RESULT.png found in {shadowgraph_base}")
            return None
            
        except Exception as e:
            print(f"Error finding latest shadowgraph result: {e}")
            import traceback
            traceback.print_exc()
            return None

    def create_shadowgraph_image_panel(self, parent):
        """Create left panel to display latest shadowgraph result image"""
        # Left column frame for image display
        image_panel = ctk.CTkFrame(parent, width=500)
        image_panel.pack(side="left", fill="y", padx=(0, 10), pady=5)
        image_panel.pack_propagate(False)  # Maintain fixed width
        
        # Title at the top
        title = ctk.CTkLabel(image_panel, text="Latest Shadowgraph Result", 
                            font=ctk.CTkFont(size=12, weight="bold"))
        title.pack(pady=(10, 5))
        
        # Refresh button
        refresh_btn = ctk.CTkButton(image_panel, text="Refresh", 
                                   command=self.refresh_shadowgraph_image,
                                   width=100, height=30)
        refresh_btn.pack(pady=(0, 10))
        
        # Image display frame below title and button - fills width
        image_frame = ctk.CTkFrame(image_panel)
        image_frame.pack(fill="x", padx=5, pady=(0, 10))
        
        # Label to display image (will be updated) - fills width
        self.shadowgraph_image_label = ctk.CTkLabel(image_frame, text="Loading...")
        self.shadowgraph_image_label.pack(fill="x", padx=0, pady=0)
        
        # Error message label (below image, initially hidden)
        self.pipeline_error_label = ctk.CTkLabel(image_panel, text="", 
                                                 font=ctk.CTkFont(size=10),
                                                 text_color="red", wraplength=480)
        self.pipeline_error_label.pack(pady=(0, 10), padx=5)
        
        # Store reference to image panel for updates
        self.shadowgraph_image_panel = image_panel
        
        # Load initial image
        self.refresh_shadowgraph_image()

    def refresh_shadowgraph_image(self):
        """Refresh the shadowgraph result image display"""
        try:
            latest_file = self.find_latest_shadowgraph_result()
            
            if latest_file and os.path.exists(latest_file):
                # Load and resize image for display
                pil_image = Image.open(latest_file)
                
                # Get the size of the image panel (fixed width - column is 500px)
                panel_width = 490  # Column width (500px) minus padding (10px total)
                max_height = 800  # Maximum height for display
                
                # Calculate scaling to fit width while maintaining aspect ratio
                img_width, img_height = pil_image.size
                scale_w = panel_width / img_width  # Scale to fill width
                scale_h = max_height / img_height
                scale = min(scale_w, scale_h)  # Use width scaling to fill column width
                
                new_width = int(img_width * scale)
                new_height = int(img_height * scale)
                
                # Resize image
                pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Convert to CTkImage for display
                ctk_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(new_width, new_height))
                
                # Store reference to prevent garbage collection
                self.shadowgraph_image_label.image = ctk_image
                
                # Get timestamp folder name for display
                timestamp_folder = os.path.basename(os.path.dirname(os.path.dirname(latest_file)))
                
                # Update label with image (no text when image is displayed)
                self.shadowgraph_image_label.configure(image=ctk_image, text="")
                
                print(f"Displaying shadowgraph result from: {timestamp_folder}")
                
            else:
                self.shadowgraph_image_label.configure(
                    image=None, 
                    text="No shadowgraph result found\n\nCheck D:\\Shadowgraph folder\n\nClick Refresh to update"
                )
                if hasattr(self.shadowgraph_image_label, 'image'):
                    self.shadowgraph_image_label.image = None
                
        except Exception as e:
            print(f"Error refreshing shadowgraph image: {e}")
            import traceback
            traceback.print_exc()
            self.shadowgraph_image_label.configure(
                image=None,
                text=f"Error loading image:\n{str(e)}"
            )
            if hasattr(self.shadowgraph_image_label, 'image'):
                self.shadowgraph_image_label.image = None

    def create_arduino_section(self, parent):
        # Arduino Connection Frame - smaller
        arduino_frame = ctk.CTkFrame(parent)
        arduino_frame.pack(fill="x", pady=(0, 5))
        
        arduino_title = ctk.CTkLabel(arduino_frame, text="Arduino Connection", 
                                   font=ctk.CTkFont(size=12, weight="bold"))
        arduino_title.pack(pady=(5, 2))
        
        # Port selection - PORT box fills remaining space
        port_frame = ctk.CTkFrame(arduino_frame)
        port_frame.pack(fill="x", padx=5, pady=2)
        
        ctk.CTkLabel(port_frame, text="Port:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.arduino_port = ctk.CTkComboBox(port_frame, values=self.get_serial_ports(), 
                                          state="readonly", height=25)
        self.arduino_port.pack(side="left", fill="x", expand=True, padx=2)
        
        refresh_btn = ctk.CTkButton(port_frame, text="Refresh", 
                                  command=self.refresh_ports, width=80, height=25)
        refresh_btn.pack(side="right", padx=2)
        
        # Auto-select first available port
        ports = self.get_serial_ports()
        if ports:
            self.arduino_port.set(ports[0])
    
    def disable_widget_recursive(self, widget):
        """Recursively disable all widgets in a container"""
        try:
            # Disable the widget itself
            if hasattr(widget, 'configure'):
                try:
                    widget.configure(state="disabled")
                except:
                    pass
        except:
            pass
        
        # Recursively disable children
        try:
            for child in widget.winfo_children():
                self.disable_widget_recursive(child)
        except:
            pass

    def on_notes_focus_in(self, event):
        """Handle focus in on notes textbox"""
        current_text = self.notes_text.get("1.0", "end-1c")
        if current_text == self.notes_placeholder:
            self.notes_text.delete("1.0", "end")
            self.notes_text.configure(text_color=("black", "white"))
    
    def on_notes_focus_out(self, event):
        """Handle focus out on notes textbox"""
        current_text = self.notes_text.get("1.0", "end-1c")
        if not current_text.strip():
            self.notes_text.insert("1.0", self.notes_placeholder)
            self.notes_text.configure(text_color="gray")

    def create_pressure_motor_section(self, parent):
        # Container frame for side-by-side layout
        container_frame = ctk.CTkFrame(parent)
        container_frame.pack(fill="x", pady=(0, 5))
        
        # Pressure Control Frame (left side) - expandable width
        pressure_frame = ctk.CTkFrame(container_frame)
        pressure_frame.pack(side="left", fill="both", expand=True, padx=(0, 0))
        
        pressure_title = ctk.CTkLabel(pressure_frame, text="Pressure", 
                                    font=ctk.CTkFont(size=12, weight="bold"))
        pressure_title.pack(pady=(5, 2))
        
        # Pressure input and controls - smaller
        pressure_controls = ctk.CTkFrame(pressure_frame)
        pressure_controls.pack(fill="x", padx=5, pady=2)
        
        ctk.CTkLabel(pressure_controls, text="Pressure (BAR):", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.pressure_entry = ctk.CTkEntry(pressure_controls, textvariable=self.pressure_value, 
                                         width=80, height=25, placeholder_text="0.0-26.4")
        self.pressure_entry.pack(side="left", padx=2)
        
        set_pressure_btn = ctk.CTkButton(pressure_controls, text="Set Pressure", 
                                       command=self.set_pressure, width=90, height=25)
        set_pressure_btn.pack(side="left", padx=2)
        
        pressure_off_btn = ctk.CTkButton(pressure_controls, text="Pressure Off", 
                                       command=self.pressure_off, width=90, height=25,
                                       fg_color="red", hover_color="darkred")
        pressure_off_btn.pack(side="right", padx=2)
        
        # Current pressure display - smaller
        current_pressure_frame = ctk.CTkFrame(pressure_frame)
        current_pressure_frame.pack(fill="x", padx=5, pady=2)
        
        ctk.CTkLabel(current_pressure_frame, text="Current Pressure:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.current_pressure_label = ctk.CTkLabel(current_pressure_frame, text="0.0 BAR", 
                                                 font=ctk.CTkFont(size=10, weight="bold"))
        self.current_pressure_label.pack(side="left", padx=2)

        # Motor Control Frame (right side) - expandable width
        motor_frame = ctk.CTkFrame(container_frame)
        motor_frame.pack(side="right", fill="both", expand=True, padx=(0, 0))
        
        motor_title = ctk.CTkLabel(motor_frame, text="Motor", 
                                 font=ctk.CTkFont(size=12, weight="bold"))
        motor_title.pack(pady=(5, 2))
        
        # Motor parameters - smaller
        motor_params = ctk.CTkFrame(motor_frame)
        motor_params.pack(fill="x", padx=5, pady=2)
        
        # Speed - smaller
        speed_frame = ctk.CTkFrame(motor_params)
        speed_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(speed_frame, text="Speed (steps/s):", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.motor_speed_entry = ctk.CTkEntry(speed_frame, textvariable=self.motor_speed, 
                                            height=25, placeholder_text="e.g., 1000")
        self.motor_speed_entry.pack(side="left", fill="x", expand=True, padx=2)
        
        # Distance - smaller
        distance_frame = ctk.CTkFrame(motor_params)
        distance_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(distance_frame, text="Distance (mm):", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.motor_distance_entry = ctk.CTkEntry(distance_frame, textvariable=self.motor_distance, 
                                               height=25, placeholder_text="e.g., 10.0")
        self.motor_distance_entry.pack(side="left", fill="x", expand=True, padx=2)
        
        # Total distance traveled - smaller
        total_frame = ctk.CTkFrame(motor_params)
        total_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(total_frame, text="Total Distance:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.cumulative_distance_label = ctk.CTkLabel(total_frame, 
                                                    text="0.0 mm (72.5 mm remaining)",
                                                    font=ctk.CTkFont(size=10, weight="bold"))
        self.cumulative_distance_label.pack(side="left", padx=2)
        # Ensure initial color reflects thresholds (green at start)
        self.update_cumulative_distance_display()

    def create_experiment_section(self, parent):
        # Experiment Parameters Frame - smaller
        experiment_frame = ctk.CTkFrame(parent)
        experiment_frame.pack(fill="x", pady=(0, 5))
        
        experiment_title = ctk.CTkLabel(experiment_frame, text="Experiment Parameters", 
                                      font=ctk.CTkFont(size=12, weight="bold"))
        experiment_title.pack(pady=(5, 2))
        
        # Main container for side-by-side layout - smaller
        main_params_frame = ctk.CTkFrame(experiment_frame)
        main_params_frame.pack(fill="x", padx=5, pady=2)
        
        # Left side - Nozzle and Orifice - smaller
        left_params_frame = ctk.CTkFrame(main_params_frame)
        left_params_frame.pack(side="left", fill="y", padx=(0, 5))
        
        # Nozzle number - smaller
        nozzle_frame = ctk.CTkFrame(left_params_frame)
        nozzle_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(nozzle_frame, text="Nozzle No.:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.nozzle_entry = ctk.CTkEntry(nozzle_frame, textvariable=self.nozzle_number, 
                                       width=60, height=25, placeholder_text="e.g., 1")
        self.nozzle_entry.pack(side="left", padx=2)
        
        # Orifice size - smaller
        orifice_frame = ctk.CTkFrame(left_params_frame)
        orifice_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(orifice_frame, text="Orifice Size:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.orifice_entry = ctk.CTkComboBox(orifice_frame, 
                                           values=["1mm", "1.2mm", "1.4mm", "1.6mm", "1.8mm", "2mm"],
                                           state="readonly", width=60, height=25)
        self.orifice_entry.pack(side="left", padx=2)
        
        # Right side - Notes - smaller
        right_params_frame = ctk.CTkFrame(main_params_frame)
        right_params_frame.pack(side="right", fill="both", expand=True)
        
        # Notes - smaller
        notes_frame = ctk.CTkFrame(right_params_frame)
        notes_frame.pack(fill="both", expand=True, pady=1)
        ctk.CTkLabel(notes_frame, text="Notes:", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=(5, 2), pady=(2, 0))
        self.notes_text = ctk.CTkTextbox(notes_frame, height=50)
        self.notes_text.pack(fill="both", expand=True, padx=5, pady=(0, 2))
        self.notes_text.insert("1.0", "Fluid Composition, Temperature, Notes...")
        self.notes_text.configure(text_color="gray")
        
        # Add placeholder text behavior
        self.notes_placeholder = "Fluid Composition, Temperature, Notes..."
        self.notes_text.bind("<FocusIn>", self.on_notes_focus_in)
        self.notes_text.bind("<FocusOut>", self.on_notes_focus_out)
        
        # Save to Excel button - centered
        save_btn = ctk.CTkButton(notes_frame, text="Save to Excel", 
                               command=self.save_to_excel, width=100, height=25)
        save_btn.pack(pady=(2, 0))

    def create_camera_control_section(self, parent):
        # Container frame for side-by-side layout
        container_frame = ctk.CTkFrame(parent)
        container_frame.pack(fill="x", pady=(0, 5))
        
        # Camera Control Frame (left side) - expandable width
        camera_frame = ctk.CTkFrame(container_frame)
        camera_frame.pack(side="left", fill="both", expand=True, padx=(0, 0))
        
        # Always create the normal camera controls first
        camera_title = ctk.CTkLabel(camera_frame, text="Camera", 
                                  font=ctk.CTkFont(size=12, weight="bold"))
        camera_title.pack(pady=(5, 2))
        
        # Camera controls - smaller
        cam_controls = ctk.CTkFrame(camera_frame)
        cam_controls.pack(fill="x", padx=5, pady=2)
        
        # IP and Connect - smaller
        ip_frame = ctk.CTkFrame(cam_controls)
        ip_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(ip_frame, text="IP:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(ip_frame, textvariable=self.cam_ip, width=100, height=25).pack(side="left", padx=2)
        ctk.CTkButton(ip_frame, text="Connect", command=self.cam_connect, width=100, height=25).pack(side="right", padx=2)
        
        # FPS and Exposure - smaller
        fps_frame = ctk.CTkFrame(cam_controls)
        fps_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(fps_frame, text="FPS:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(fps_frame, textvariable=self.cam_fps, width=60, height=25).pack(side="left", padx=2)
        ctk.CTkLabel(fps_frame, text="Exposure (μs):", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(fps_frame, textvariable=self.cam_exposure_us, width=80, height=25).pack(side="left", padx=2)
        ctk.CTkButton(fps_frame, text="Ping", command=self.cam_ping, width=100, height=25).pack(side="right", padx=2)
        
        # Width and Height - smaller
        wh_frame = ctk.CTkFrame(cam_controls)
        wh_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(wh_frame, text="Width:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(wh_frame, textvariable=self.cam_width, width=60, height=25).pack(side="left", padx=2)
        ctk.CTkLabel(wh_frame, text="Height:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(wh_frame, textvariable=self.cam_height, width=60, height=25).pack(side="left", padx=2)
        
        # Seconds to Record and Output - smaller
        frames_frame = ctk.CTkFrame(cam_controls)
        frames_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(frames_frame, text="Seconds to Record:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(frames_frame, textvariable=self.cam_seconds, width=60, height=25, 
                    placeholder_text="e.g., 0.5").pack(side="left", padx=2)
        ctk.CTkLabel(frames_frame, text="Output:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(frames_frame, textvariable=self.cam_output, width=150, height=25).pack(side="left", padx=2)
        ctk.CTkButton(frames_frame, text="Apply Config", command=self.cam_config, width=100, height=25).pack(side="right", padx=2)
        
        # Capture button and status - smaller
        capture_frame = ctk.CTkFrame(cam_controls)
        capture_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(capture_frame, textvariable=self.camera_status, font=ctk.CTkFont(size=9)).pack(side="left", padx=(5, 2))
        ctk.CTkButton(capture_frame, text="Abort", command=self.cam_abort, width=60, height=25).pack(side="left", padx=2)
        
        # Pipeline checkbox (to the left of Capture button)
        pipeline_checkbox = ctk.CTkCheckBox(capture_frame, text="Pipeline", 
                                           variable=self.pipeline_enabled, width=80, height=25)
        pipeline_checkbox.pack(side="right", padx=(0, 5))
        
        self.cam_capture_btn = ctk.CTkButton(capture_frame, text="Capture", 
                                           command=self._cam_capture_handler, width=90, height=25,
                                           fg_color="red", hover_color="darkred")
        self.cam_capture_btn.pack(side="right", padx=2)
        
        # Disable camera controls for Mac users
        if not self.camera_available:
            # Disable all camera controls
            for widget in camera_frame.winfo_children():
                self.disable_widget_recursive(widget)
            
            # Add disabled message at the bottom
            disabled_label = ctk.CTkLabel(camera_frame, 
                                        text="[WARNING] Windows SDK Required For Camera Functionality",
                                        font=ctk.CTkFont(size=14, weight="bold"),
                                        text_color="orange")
            disabled_label.pack(pady=15)

        # Control Panel Frame (right side) - expandable width
        control_frame = ctk.CTkFrame(container_frame)
        control_frame.pack(side="right", fill="both", expand=True, padx=(0, 0))
        
        control_title = ctk.CTkLabel(control_frame, text="Control Panel", 
                                   font=ctk.CTkFont(size=12, weight="bold"))
        control_title.pack(pady=(5, 2))
        
        # Buttons - smaller
        buttons_frame = ctk.CTkFrame(control_frame)
        buttons_frame.pack(fill="x", padx=5, pady=2)
        
        # Home button - smaller
        self.home_button = ctk.CTkButton(buttons_frame, text="🏠 HOME", 
                                       command=self.home_motor, width=80, height=25,
                                       fg_color="orange", hover_color="darkorange")
        self.home_button.pack(side="left", padx=2)

        # Cleaning button with safety confirmation - placed to the left of START
        self.cleaning_in_progress = False
        self.clean_button = ctk.CTkButton(buttons_frame, text="🧼 CLEANING", 
                                        command=self.start_cleaning, width=110, height=25,
                                        fg_color="#5555AA", hover_color="#444488")
        self.clean_button.pack(side="left", padx=2)
        
        # Homed indicator - smaller
        self.homed_label = ctk.CTkLabel(buttons_frame, text="NO", 
                                      font=ctk.CTkFont(size=10, weight="bold"),
                                      text_color="red")
        self.homed_label.pack(side="left", padx=(5, 2))
        
        # Start button - smaller, right-aligned
        self.start_button = ctk.CTkButton(buttons_frame, text="START EXPERIMENT", 
                                        command=self.start_experiment, width=150, height=25,
                                        fg_color="green", hover_color="darkgreen",
                                        font=ctk.CTkFont(size=10, weight="bold"))
        self.start_button.pack(side="right", padx=2)
        
        # Pressure Graph - much smaller, inside control panel
        # Create matplotlib figure - ultra small with more detail
        self.fig, self.ax = plt.subplots(figsize=(2.16, 1.152))
        self.ax.set_xlabel('Time (s)', fontsize=8)
        self.ax.set_ylabel('Pressure (BAR)', fontsize=8)
        self.ax.grid(True, alpha=0.3, linewidth=0.3)
        
        # Add more detailed grid lines
        self.ax.set_xticks(range(0, 61, 10))  # Every 10 seconds
        self.ax.set_yticks(range(0, 21, 5))   # Every 5 BAR
        self.ax.tick_params(axis='both', which='major', labelsize=5)
        
        # Initialize empty line with thinner line
        self.pressure_line, = self.ax.plot([], [], 'b-', linewidth=0.5, label='Pressure')
        self.ax.legend(fontsize=3, loc='upper right')
        
        # Set initial axis limits with tighter margins
        self.ax.set_xlim(0, 60)
        self.ax.set_ylim(0, 20)
        
        # Remove extra padding
        self.fig.tight_layout(pad=0.1)
        
        # Create canvas widget - ultra small
        self.canvas = FigureCanvasTkAgg(self.fig, control_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(pady=1)

    def create_afg_section(self, parent):
        """Create AFG1062 control section"""
        afg_frame = ctk.CTkFrame(parent)
        afg_frame.pack(fill="x", pady=(0, 5))
        
        afg_title = ctk.CTkLabel(afg_frame, text="Tektronix AFG1062", 
                                font=ctk.CTkFont(size=12, weight="bold"))
        afg_title.pack(pady=(5, 2))
        
        # AFG controls
        afg_controls = ctk.CTkFrame(afg_frame)
        afg_controls.pack(fill="x", padx=5, pady=2)
        
        # Channel selection and Connect
        channel_frame = ctk.CTkFrame(afg_controls)
        channel_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(channel_frame, text="Channel:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkOptionMenu(channel_frame, values=["CH1", "CH2"], variable=self.afg_channel, width=60, height=25).pack(side="left", padx=2)
        ctk.CTkButton(channel_frame, text="Connect", command=self.afg_connect, width=100, height=25).pack(side="right", padx=2)
        
        # Pulse duration
        duration_frame = ctk.CTkFrame(afg_controls)
        duration_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(duration_frame, text="Pulse Duration (s):", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        ctk.CTkEntry(duration_frame, textvariable=self.afg_pulse_duration, width=80, height=25, 
                    placeholder_text="e.g., 0.001").pack(side="left", padx=2)
        
        # Apply Config, Test, and Disconnect
        config_frame = ctk.CTkFrame(afg_controls)
        config_frame.pack(fill="x", pady=1)
        ctk.CTkButton(config_frame, text="Apply Config", command=self.afg_configure, width=90, height=25).pack(side="left", padx=2)
        ctk.CTkButton(config_frame, text="Test", command=self.afg_test, width=90, height=25, 
                     fg_color=("gray75", "gray25"), hover_color=("gray65", "gray35")).pack(side="left", padx=2)
        ctk.CTkButton(config_frame, text="Disconnect", command=self.afg_disconnect, width=90, height=25).pack(side="right", padx=2)
        
        # Status
        status_frame = ctk.CTkFrame(afg_controls)
        status_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(status_frame, textvariable=self.afg_status, font=ctk.CTkFont(size=9)).pack(side="left", padx=(5, 2))
        
        # Disable AFG controls if PyVISA not available
        if not self.afg_available:
            for widget in afg_frame.winfo_children():
                self.disable_widget_recursive(widget)
            
            disabled_label = ctk.CTkLabel(afg_frame, 
                                        text="[WARNING] PyVISA Required - Install with: pip install pyvisa",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        text_color="orange")
            disabled_label.pack(pady=10)

    def create_status_section(self, parent):
        # Status and Progress Frame - smaller
        status_frame = ctk.CTkFrame(parent)
        status_frame.pack(fill="x", pady=(0, 5))
        
        status_title = ctk.CTkLabel(status_frame, text="Status", 
                                  font=ctk.CTkFont(size=12, weight="bold"))
        status_title.pack(pady=(5, 2))
        
        # Status label - smaller
        self.status_label = ctk.CTkLabel(status_frame, textvariable=self.status,
                                       font=ctk.CTkFont(size=10, weight="bold"),
                                       text_color="white")
        self.status_label.pack(pady=2)
        
        # Progress bar - spans full width
        progress_frame = ctk.CTkFrame(status_frame)
        progress_frame.pack(fill="x", padx=5, pady=2)
        
        ctk.CTkLabel(progress_frame, text="Movement Progress:", font=ctk.CTkFont(size=10)).pack(side="left", padx=(5, 2))
        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=2)
        self.progress_bar.set(0)
        
        self.progress_label = ctk.CTkLabel(progress_frame, text="0%",
                                         font=ctk.CTkFont(size=10, weight="bold"))
        self.progress_label.pack(side="right", padx=2)

    def create_graph_section(self, parent):
        # Pressure Graph Frame - smaller
        graph_frame = ctk.CTkFrame(parent)
        graph_frame.pack(fill="x", pady=(0, 5))
        
        graph_title = ctk.CTkLabel(graph_frame, text="📈 Pressure Monitoring", 
                                 font=ctk.CTkFont(size=12, weight="bold"))
        graph_title.pack(pady=(5, 2))
        
        # Create matplotlib figure - smaller
        self.fig, self.ax = plt.subplots(figsize=(4, 2))
        self.ax.set_title('Pressure Over Time', fontsize=10, fontweight='bold')
        self.ax.set_xlabel('Time (s)', fontsize=8)
        self.ax.set_ylabel('Pressure (BAR)', fontsize=8)
        self.ax.grid(True, alpha=0.3)
        
        # Initialize empty line
        self.pressure_line, = self.ax.plot([], [], 'b-', linewidth=2, label='Pressure')
        self.ax.legend(fontsize=8)
        
        # Set initial axis limits
        self.ax.set_xlim(0, 60)
        self.ax.set_ylim(0, 20)
        
        # Create canvas widget - smaller
        self.canvas = FigureCanvasTkAgg(self.fig, graph_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(pady=5)

    # All the existing methods from the original class...
    # (I'll include the key methods, but you can copy the rest from your original file)
    
    def connect_to_arduino(self):
        """Establish persistent connection to Arduino"""
        try:
            port = self.arduino_port.get()
            if not port:
                print("No port selected for connection")
                return False
            
            if self.arduino and hasattr(self.arduino, 'ser') and self.arduino.ser.is_open:
                print("Already connected to Arduino")
                return True
            
            print(f"Connecting to Arduino on {port}...")
            self.arduino = ArduinoController(port)
            self.arduino.connect()
            
            # Start serial reader thread
            self.serial_reading_active = True
            self.serial_reader_thread = threading.Thread(
                target=self.serial_reader_loop,
                daemon=True
            )
            self.serial_reader_thread.start()
            
            self.status.set("Connected to Arduino")
            print(" Connected to Arduino - persistent connection established")
            return True
            
        except Exception as e:
            self.status.set(f"Connection error: {e}")
            print(f"Failed to connect to Arduino: {e}")
            self.arduino = None
            return False

    def serial_reader_loop(self):
        """Background thread to continuously read serial data"""
        while self.serial_reading_active and self.arduino and hasattr(self.arduino, 'ser') and self.arduino.ser and self.arduino.ser.is_open:
            try:
                if self.arduino.ser.in_waiting > 0:
                    # Use 'ignore' or 'replace' to handle Unicode characters gracefully
                    response = self.arduino.ser.readline().decode('utf-8', errors='replace').strip()
                    if response:
                        self.handle_serial_response(response)
                time.sleep(0.05)
            except serial.SerialException as e:
                print(f"Serial connection lost: {e}")
                # Don't break immediately - try to reconnect
                time.sleep(1)
                continue
            except UnicodeDecodeError as e:
                # Handle encoding errors gracefully - skip this line and continue
                print(f"Unicode decode error (skipping line): {e}")
                continue
            except Exception as e:
                # Log error but don't break - try to continue reading
                print(f"Serial reader error (continuing): {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
                continue
        print("Serial reader thread stopped")

    def handle_serial_response(self, response):
        """Parse and handle incoming serial messages"""
        log_serial(f"Response: {response}")
        print(f"Arduino: {response}")
        
        # Handle different message types
        if response.startswith("CAM:"):
            cam_msg = response[4:].strip()
            if cam_msg.startswith("OK:"):
                self.master.after(0, lambda: self.camera_status.set(f"Camera OK - {cam_msg[3:].strip()}"))
            elif cam_msg.startswith("STARTED:"):
                self.master.after(0, lambda: self.camera_status.set("Capture started"))
            elif cam_msg.startswith("PROGRESS:"):
                try:
                    part = cam_msg.split("frames_written=")[1]
                    self.master.after(0, lambda p=part: self.camera_status.set(f"Camera progress: {p}"))
                except Exception:
                    pass
            elif cam_msg.startswith("DONE:"):
                self.master.after(0, lambda: self.camera_status.set(cam_msg))
            elif cam_msg.startswith("ERROR:"):
                self.master.after(0, lambda: self.camera_status.set(cam_msg))
            return

        if "Homing Complete!" in response:
            print("Homing completed! Setting homing flag")
            self.homing_completed = True
        elif "PRESSURE_SET:" in response:
            self.master.after(0, lambda: self.status.set(f"Pressure set confirmed"))
        elif "PRESSURE_DISABLED" in response:
            self.master.after(0, lambda: self.status.set("Pressure OFF confirmed"))
            # If pressure is turned off during an experiment, stop monitoring
            self.master.after(0, self.stop_pressure_monitoring)
        elif "PRESSURE_READING:" in response:
            try:
                pressure = float(response.split(":")[1])
                # Update on-screen current pressure
                self.master.after(0, lambda p=pressure: self.current_pressure_label.configure(text=f"{p:.1f} BAR"))
                # Always update live graph (always-on rolling display)
                self.master.after(0, lambda p=pressure: self.add_live_pressure_data_point(p))
                # If experiment is active, also save to experiment buffer
                if self.pressure_data.get('experiment_active'):
                    self.master.after(0, lambda p=pressure: self.add_experiment_pressure_data_point(p))
            except:
                pass
        elif "MOVEMENT_COMPLETE" in response:
            print("Movement completed! Setting completion flag")
            self.experiment_completed = True
            self.master.after(0, lambda: self.progress_bar.set(1.0))
            self.master.after(0, lambda: self.progress_label.configure(text="100%"))
            self.master.after(0, self.auto_save_pressure_graph)
            self.master.after(0, self.stop_pressure_monitoring)
            # If a cleaning move was in progress, set cumulative distance to 78mm
            if getattr(self, 'cleaning_in_progress', False):
                self.cleaning_in_progress = False
                self.cumulative_distance = 78.0
                self.master.after(0, self.update_cumulative_distance_display)
        elif "DEBUG: Movement progress:" in response or "Movement progress:" in response:
            if "%" in response:
                try:
                    percent_start = response.rfind(" ") + 1
                    percent_end = response.find("%")
                    progress = int(response[percent_start:percent_end])
                    self.master.after(0, lambda p=progress: self.update_progress(p))
                except:
                    pass

    def update_progress(self, progress):
        """Update progress bar from serial reader thread"""
        self.progress_bar.set(progress / 100.0)
        self.progress_label.configure(text=f"{progress}%")

    def start_experiment(self):
        """Start experiment with full validation"""
        try:
            motor_speed = int(self.motor_speed.get())
            motor_distance = int(self.motor_distance.get())
            arduino_port = self.arduino_port.get()
            
            # Validate new fields
            pressure = self.pressure_value.get()
            nozzle_number = self.nozzle_number.get()
            orifice_size = self.orifice_entry.get()
            
            # Validate pressure is between 0-26.4 BAR
            if pressure:
                try:
                    pressure_float = float(pressure)
                    if pressure_float < 0 or pressure_float > 26.4:
                        messagebox.showerror("Input Error", "Pressure must be between 0 and 26.4 BAR.")
                        return
                except ValueError:
                    messagebox.showerror("Input Error", "Pressure must be a valid number.")
                    return
            
            # Validate other fields are not empty
            if not nozzle_number.strip():
                messagebox.showerror("Input Error", "Please enter a nozzle number.")
                return
            if not orifice_size.strip():
                messagebox.showerror("Input Error", "Please enter an orifice size.")
                return
            
            # Validate cumulative distance doesn't exceed 72.5mm limit
            try:
                motor_distance_float = float(motor_distance)
                if motor_distance_float < 0:
                    messagebox.showerror("Input Error", "Motor distance must be positive.")
                    return
                
                # Check if this movement would exceed the 73mm limit
                new_cumulative = self.cumulative_distance + motor_distance_float
                if new_cumulative > 73.0:
                    messagebox.showerror("Input Error", 
                        f"Movement would exceed 73.0mm limit!\n\n"
                        f"Current cumulative distance: {self.cumulative_distance:.1f} mm\n"
                        f"Requested movement: {motor_distance_float:.1f} mm\n"
                        f"Would result in: {new_cumulative:.1f} mm\n\n"
                        f"Maximum allowed movement: {73.0 - self.cumulative_distance:.1f} mm")
                    return
                    
            except ValueError:
                messagebox.showerror("Input Error", "Motor distance must be a valid number.")
                return
                
        except ValueError:
            messagebox.showerror("Input Error", "Please enter valid numbers for all fields.")
            return
        
        print(f"Starting experiment - Speed: {motor_speed}, Distance: {motor_distance}")
        print("Starting experiment - disabling start button")
        self.start_button.configure(state="disabled")

        # Update homed indicator during experiment
        self.update_home_button_color(False)

        # Begin pressure monitoring for rolling graph
        self.start_pressure_monitoring()

        # Run the experiment in a separate thread
        threading.Thread(
            target=self.run_experiment,
            args=(arduino_port, motor_speed, motor_distance),
            daemon=True
        ).start()

    def run_experiment(self, arduino_port, motor_speed, motor_distance):
        """Run experiment with full Arduino communication"""
        try:
            print(f"=== STARTING EXPERIMENT ===")
            print(f"Port: {arduino_port}, Speed: {motor_speed}, Distance: {motor_distance}")
            
            # Check persistent connection
            if not self.arduino or not self.arduino.ser or not self.arduino.ser.is_open:
                self.status.set("Connecting to Arduino...")
                if not self.connect_to_arduino():
                    self.status.set("Failed to connect to Arduino")
                    return
            
            self.status.set("Sending motor command to Arduino...")
            print("Sending motor command...")
            self.arduino.send_motor_command(motor_speed, motor_distance)
            print("Motor command sent")
            
            # Reset progress bar
            self.master.after(0, lambda: self.progress_bar.set(0))
            self.master.after(0, lambda: self.progress_label.configure(text="0%"))
            
            # Wait for completion message
            print("Waiting for movement to complete...")
            self.status.set("Motor moving...")
            
            start_time = time.time()
            timeout = 300  # 5 minutes timeout
            self.experiment_completed = False
            
            # Wait for completion flag to be set by serial reader
            while time.time() - start_time < timeout and not self.experiment_completed:
                time.sleep(0.1)
            
            if not self.experiment_completed:
                print("Timeout waiting for completion")
                self.status.set("Movement timeout - check motor status")
                # Force progress bar to 100% even on timeout
                self.master.after(0, lambda: self.progress_bar.set(1.0))
                self.master.after(0, lambda: self.progress_label.configure(text="100%"))
                # Auto-save pressure graph when experiment completes (timeout)
                self.master.after(0, self.auto_save_pressure_graph)
            
            # Stop pressure monitoring once experiment completes or times out
            self.master.after(0, self.stop_pressure_monitoring)
            
            print("Experiment completed, starting reset process...")
            # Reset Arduino state for next experiment
            print("Resetting Arduino state for next experiment...")
            self.arduino.reset_state()
            time.sleep(1)  # Give Arduino time to process reset
            self.status.set("Experiment complete!")
            print("Reset process completed, experiment marked as complete")
        except Exception as e:
            self.status.set(f"Error: {e}")
            log_serial(f"Error: {e}")
            print(f"Error occurred: {e}")
        finally:
            print("Experiment finished - re-enabling start button")
            self.start_button.configure(state="normal")
            
            # Reset progress bar and status
            self.progress_bar.set(0)
            self.progress_label.configure(text="0%")
            
            # Update cumulative distance first
            try:
                experiment_distance = float(self.motor_distance.get())
                self.cumulative_distance += experiment_distance
                self.update_cumulative_distance_display()
            except ValueError:
                pass  # If distance is not a valid number, skip update
            
            # Now update status with the updated cumulative distance
            self.status.set(f"Ready for next experiment. Total distance: {self.cumulative_distance:.1f} mm")
            
            # Update homed indicator based on total distance
            self.update_home_button_color(self.cumulative_distance == 0.0)

    def home_motor(self):
        """Send homing command to Arduino"""
        try:
            arduino_port = self.arduino_port.get()
            if not arduino_port:
                messagebox.showerror("Input Error", "Please select an Arduino port first.")
                return
                
            self.home_button.configure(state="disabled")
            self.status.set("Homing motor...")
            
            # Run homing in a separate thread
            threading.Thread(
                target=self.run_homing,
                args=(arduino_port,),
                daemon=True
            ).start()
            
        except Exception as e:
            self.status.set(f"Error: {e}")
            self.home_button.configure(state="normal")
            print(f"Home error: {e}")

    def run_homing(self, arduino_port):
        """Run the homing sequence"""
        try:
            # Check persistent connection
            if not self.arduino or not self.arduino.ser or not self.arduino.ser.is_open:
                if not self.connect_to_arduino():
                    self.master.after(0, lambda: self.status.set("Failed to connect to Arduino"))
                    return
            
            # Send homing command through persistent connection
            self.arduino.ser.write("HOME:1\n".encode())
            time.sleep(1)  # Wait for command to be processed
            
            # Wait for homing to complete
            print("Waiting for homing to complete...")
            self.homing_completed = False
            start_time = time.time()
            timeout = 60  # 1 minute timeout for homing
            
            while time.time() - start_time < timeout and not self.homing_completed:
                time.sleep(0.1)
            
            if self.homing_completed:
                self.master.after(0, lambda: self.status.set("Homing complete!"))
                
                # Reset cumulative distance when homing is successful
                self.cumulative_distance = 0.0
                self.master.after(0, lambda: self.update_cumulative_distance_display())
                
                self.update_home_button_color(True)
                print("Homing completed successfully - start button should be available")
            else:
                self.master.after(0, lambda: self.status.set("Homing timeout - check motor"))
                self.update_home_button_color(False)
                print("Homing failed - start button may not be available")
            
        except Exception as e:
            self.master.after(0, lambda: self.status.set(f"Homing error: {e}"))
            print(f"Homing error: {e}")
        finally:
            self.master.after(0, lambda: self.home_button.configure(state="normal"))
            print("Home button re-enabled")

    def update_home_button_color(self, is_homed):
        """Update the homed label to YES (green) or NO (red)"""
        try:
            is_homed = (self.cumulative_distance == 0.0)
        except Exception:
            pass
        if is_homed:
            self.homed_label.configure(text="YES", text_color="green")
        else:
            self.homed_label.configure(text="NO", text_color="red")

    def update_cumulative_distance_display(self):
        """Update the cumulative distance label with color coding and remaining distance"""
        remaining = 72.5 - self.cumulative_distance
        
        if remaining >= 35:
            color = "green"
        elif remaining >= 10:
            color = "orange"
        else:
            color = "red"
            
        self.cumulative_distance_label.configure(
            text=f"{self.cumulative_distance:.1f} mm ({remaining:.1f} mm remaining)",
            text_color=color
        )

    def set_pressure(self):
        """Set pressure on the Alicat controller"""
        try:
            pressure = float(self.pressure_value.get())
            if pressure < 0 or pressure > 26.4:
                messagebox.showerror("Input Error", "Pressure must be between 0 and 26.4 BAR.")
                return
            
            if not self.arduino or not self.arduino.ser or not self.arduino.ser.is_open:
                messagebox.showerror("Connection Error", "Not connected to Arduino. Please reconnect.")
                self.connect_to_arduino()
                return
            
            # Send pressure command immediately through persistent connection
            self.arduino.send_pressure_command(pressure)
            self.status.set(f"Setting pressure to {pressure} BAR...")
            
        except ValueError:
            messagebox.showerror("Input Error", "Please enter a valid pressure value.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to set pressure: {str(e)}")

    def start_cleaning(self):
        """Run cleaning move to absolute 78mm after safety confirmation"""
        try:
            # Safety confirmation
            proceed = messagebox.askyesno(
                "Safety Check",
                "Please REMOVE the front of the pressure syringe before cleaning.\n\nClick YES to confirm and proceed."
            )
            if not proceed:
                return
            
            # Check connection
            if not self.arduino or not self.arduino.ser or not self.arduino.ser.is_open:
                self.status.set("Connecting to Arduino...")
                if not self.connect_to_arduino():
                    self.status.set("Failed to connect to Arduino")
                    return
            
            # Send CLEAN command
            self.cleaning_in_progress = True
            if hasattr(self, 'start_button'):
                self.start_button.configure(state="disabled")
            self.status.set("Cleaning: moving to 78mm...")
            self.arduino.ser.write("CLEAN:1\n".encode())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start cleaning: {str(e)}")

    def pressure_off(self):
        """Turn off pressure control"""
        try:
            if not self.arduino or not self.arduino.ser or not self.arduino.ser.is_open:
                messagebox.showerror("Connection Error", "Not connected to Arduino. Please reconnect.")
                self.connect_to_arduino()
                return
            
            # Send pressure off command immediately through persistent connection
            self.arduino.send_pressure_off_command()
            self.status.set("Turning pressure OFF...")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to turn off pressure: {str(e)}")

    def save_to_excel(self):
        """Save experiment data to Excel file with full validation (matches test_pressure_graph.py style)"""
        try:
            # Get current values from GUI
            motor_speed = self.motor_speed.get()
            motor_distance = self.motor_distance.get()
            notes = self.notes_text.get("1.0", "end-1c").strip()
            pressure = self.pressure_value.get()
            nozzle_number = self.nozzle_number.get()
            orifice_size = self.orifice_entry.get()
            
            # Validate inputs - require all fields except Arduino Port
            if not motor_speed or not motor_distance or not pressure or not nozzle_number or not orifice_size:
                messagebox.showerror("Input Error", "Please fill in all fields before saving:\n\n• Motor Speed\n• Motor Distance\n• Pressure (BAR)\n• Nozzle No. Used\n• Orifice Size")
                return
            
            # Validate notes length (require at least 10 characters, ignore placeholder text)
            if notes == "Fluid Composition, Temperature, Notes..." or len(notes) < 10:
                actual_length = 0 if notes == "Fluid Composition, Temperature, Notes..." else len(notes)
                messagebox.showerror("Input Error", f"Please provide more detailed notes.\n\nCurrent notes: {actual_length} characters\nRequired: At least 10 characters")
                return
            
            # Additional validation for pressure range
            try:
                pressure_float = float(pressure)
                if pressure_float < 0 or pressure_float > 26.4:
                    messagebox.showerror("Input Error", "Pressure must be between 0 and 26.4 BAR.")
                    return
            except ValueError:
                messagebox.showerror("Input Error", "Pressure must be a valid number.")
                return

            # Headers and corresponding row data
            headers = [
                'Timestamp',
                'Motor Speed (steps/s)',
                'Motor Distance (mm)',
                'Dist Travelled (mm)',
                'Pressure (BAR)',
                'Nozzle No. Used',
                'Orifice Size (mm)',
                'Notes',
                'Pressure Graph'
            ]

            timestamp_display = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
            timestamp_file = timestamp_display.replace(":", "-").replace(" ", "_")
            row_values = [
                timestamp_display,
                motor_speed,
                motor_distance,
                self.cumulative_distance,
                pressure,
                nozzle_number,
                orifice_size,
                notes,
                ''
            ]

            # Use config for experiment log directory
            experiment_log_dir = GUI_CONFIG.get('experiment_log_dir', os.getcwd())
            os.makedirs(experiment_log_dir, exist_ok=True)
            excel_file = os.path.join(experiment_log_dir, "experiment_log.xlsx")
            print(f"Excel file path: {excel_file}")
            print(f"Current working directory: {os.getcwd()}")

            # Use openpyxl to append without deleting previous images
            from openpyxl import Workbook, load_workbook
            from openpyxl.styles import Alignment, Font
            from openpyxl.utils import get_column_letter
            from openpyxl.drawing.image import Image

            if os.path.exists(excel_file):
                wb = load_workbook(excel_file)
                if 'Experiment_Data' in wb.sheetnames:
                    ws = wb['Experiment_Data']
                else:
                    ws = wb.create_sheet('Experiment_Data')
                    ws.append(headers)
            else:
                wb = Workbook()
                ws = wb.active
                ws.title = 'Experiment_Data'
                ws.append(headers)

            # Insert new row at the top (row 2, after headers)
            ws.insert_rows(2)

            # Move all existing images down by one row to maintain their positions
            for image in ws._images[:]:  # Copy list to avoid modification during iteration
                # Get current anchor position
                anchor = image.anchor
                if hasattr(anchor, '_from') and hasattr(anchor._from, 'row'):
                    # Move image down by one row
                    anchor._from.row += 1
                elif hasattr(anchor, 'row'):
                    anchor.row += 1

            # Move all existing charts down by one row to maintain their positions
            if hasattr(ws, '_charts'):
                for chart in ws._charts[:]:  # Work on a copy
                    try:
                        ch_anchor = chart.anchor
                        # TwoCellAnchor with _from and _to
                        if hasattr(ch_anchor, '_from') and hasattr(ch_anchor._from, 'row'):
                            ch_anchor._from.row += 1
                        if hasattr(ch_anchor, '_to') and hasattr(ch_anchor._to, 'row'):
                            ch_anchor._to.row += 1
                        # Fallback single cell anchor
                        if hasattr(ch_anchor, 'row'):
                            ch_anchor.row += 1
                    except Exception:
                        # If anchor structure unexpected, skip gracefully
                        pass
            
            # Write the new data to row 2
            for col_idx, value in enumerate(row_values, start=1):
                ws.cell(row=2, column=col_idx, value=value)

            # The new row is always row 2
            new_row = 2

            # Auto-size columns
            center_alignment = Alignment(horizontal='center', vertical='center')
            left_alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
            bold_font = Font(bold=True, size=12)

            for col_idx, col in enumerate(ws.iter_cols(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column), start=1):
                max_length = 0
                for cell in col:
                    cell_value = '' if cell.value is None else str(cell.value)
                    max_length = max(max_length, len(cell_value))
                    # Apply alignment and formatting
                    if cell.row == 1:
                        cell.font = bold_font  # Make header row bold and 12pt
                    
                    if col_idx == headers.index('Notes') + 1:
                        cell.alignment = left_alignment
                    else:
                        cell.alignment = center_alignment
                adjusted_width = min(max_length + 2, 80)
                ws.column_dimensions[get_column_letter(col_idx)].width = adjusted_width

            # Ensure the 'Pressure Graph' column is wide enough (reduced by 30%)
            graph_col_idx = headers.index('Pressure Graph') + 1
            ws.column_dimensions[get_column_letter(graph_col_idx)].width = 42  # 60 * 0.7 = 42

            # Make all data rows tall enough to house a graph
            for r in range(2, ws.max_row + 1):
                ws.row_dimensions[r].height = 225

            # Create simple chart from CSV data if available
            if self.pressure_data['saved_graph_filename'] and os.path.exists(self.pressure_data['saved_graph_filename']):
                try:
                    # Read CSV data
                    df_chart = pd.read_csv(self.pressure_data['saved_graph_filename'])
                    
                    # Use non-interactive backend for chart creation
                    matplotlib.use('Agg')  # Use non-interactive backend
                    plt.close('all')  # Close any existing figures to prevent memory issues
                    
                    # Calculate width based on test duration (60s = 8 inches, scale proportionally)
                    test_duration = df_chart['Time (s)'].max()
                    base_width = 8  # Base width for 60 seconds
                    base_duration = 60  # Base duration in seconds
                    
                    # Scale width based on duration with 1.5x spacing for time values
                    chart_width = max(base_width, (test_duration / base_duration) * base_width * 1.5)
                    chart_height = 4.15  # Increased to ~4.15 inches to fill Excel cell (was 75%, now 100%)
                    
                    # Create figure with full size to fill Excel cell
                    fig, ax = plt.subplots(figsize=(chart_width, chart_height))
                    
                    # Plot with red line (thicker for visibility in Excel)
                    ax.plot(df_chart['Time (s)'], df_chart['Pressure (BAR)'], 
                           color='red', linewidth=2.0)
                    
                    # Set axis labels (larger font for better visibility)
                    ax.set_xlabel('Time (s)', fontsize=12)
                    ax.set_ylabel('Pressure (BAR)', fontsize=12)
                    
                    # Set axis limits to start at 0,0 (bottom left)
                    ax.set_xlim(left=0)
                    ax.set_ylim(bottom=0)
                    
                    # Set time axis to 10-second intervals
                    max_time = df_chart['Time (s)'].max()
                    time_ticks = np.arange(0, max_time + 10, 10)  # 0, 10, 20, 30, etc.
                    ax.set_xticks(time_ticks)
                    
                    # Add horizontal gridlines only (for pressure reference lines)
                    ax.grid(True, axis='y', alpha=0.3, linestyle='-', linewidth=0.5)
                    ax.tick_params(axis='both', which='major', labelsize=10)
                    
                    # Remove borders
                    for spine in ax.spines.values():
                        spine.set_visible(False)
                    
                    # Save as high-resolution image
                    chart_filename = f"temp_chart_{timestamp_display.replace(' ', '_').replace(':', '-')}.png"
                    plt.savefig(chart_filename, dpi=150, bbox_inches='tight', 
                               facecolor='white', edgecolor='none')
                    
                    # Insert image into Excel - size to fill the cell
                    img = Image(chart_filename)
                    
                    # Excel column width 42 units ≈ 315 pixels (42 * 7.5)
                    # Excel row height 225 points = 225 pixels
                    # Scale image to fill the cell (increase by ~33% to go from 75% to 100%)
                    img_width = int(420 * (chart_width / base_width))  # Scale width based on duration, increased from 315
                    img_height = 300  # Increased from 225 to fill cell properly
                    
                    img.width = img_width
                    img.height = img_height
                    
                    chart_cell = f"{get_column_letter(graph_col_idx)}{new_row}"
                    ws.add_image(img, chart_cell)
                    
                    print(f"Simple red chart created and inserted at {chart_cell}")
                    print(f"Chart dimensions: {chart_width:.1f}\" x {chart_height}\" (test duration: {test_duration:.1f}s)")
                    print(f"Image dimensions: {img_width} x {img_height} pixels")
                    
                except Exception as e:
                    print(f"Could not create chart: {e}")
                    print(f"Error details: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    print("Excel file will be saved without chart")

            # Save the workbook with diagnostics
            try:
                wb.save(excel_file)
                print(f"Excel file saved successfully: {excel_file}")
                
                # Clean up temp file AFTER Excel is saved
                if 'chart_filename' in locals():
                    try:
                        os.remove(chart_filename)
                    except:
                        pass
                
                # Final cleanup to prevent segmentation faults
                try:
                    plt.close('all')
                    plt.clf()
                    plt.cla()
                    import gc
                    gc.collect()
                except:
                    pass
                    
            except Exception as e:
                print(f"Error saving Excel file: {e}")
                import traceback
                traceback.print_exc()
                raise

            messagebox.showinfo("Success", f"Experiment data saved to {excel_file}")
            
            # Clear notes after successful save
            self.notes_text.delete("1.0", "end")
            self.notes_text.insert("1.0", "Fluid Composition, Temperature, Notes...")
            self.notes_text.configure(text_color="gray")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save test data: {str(e)}")
            print(f"Excel save error: {e}")
        
        finally:
            try:
                plt.close('all')
                plt.clf()
                plt.cla()
                import gc
                gc.collect()
            except:
                pass

    def cam_connect(self):
        """Connect to camera using Phantom SDK"""
        if not self.camera_available:
            self.camera_status.set("Camera not available - SDK not installed")
            messagebox.showerror("SDK Error", 
                               "Phantom SDK (pyphantom) is not installed.\n\n"
                               "Please install the SDK to enable camera functionality.")
            return
        
        if not self.phantom_camera:
            self.phantom_camera = PhantomController()
        
        try:
            ip = self.cam_ip.get().strip()
            # Connect to camera (IP is informational, we connect by index)
            self.phantom_camera.connect(camera_index=0)
            self.camera_status.set(f"Connected to camera at {ip}")
            print(f"Camera connected successfully")
        except Exception as e:
            error_msg = f"Failed to connect to camera: {str(e)}"
            self.camera_status.set(f"Connection error: {str(e)}")
            messagebox.showerror("Connection Error", error_msg)
            print(f"Camera connection error: {e}")

    def cam_config(self):
        """Configure camera settings using Phantom SDK"""
        if not self.camera_available:
            self.camera_status.set("Camera not available - SDK not installed")
            return
        
        if not self.phantom_camera or not self.phantom_camera.is_connected:
            self.camera_status.set("Camera not connected - connect first")
            messagebox.showwarning("Not Connected", "Please connect to camera first")
            return
        
        try:
            fps = int(self.cam_fps.get())
            exposure = int(self.cam_exposure_us.get())
            width = int(self.cam_width.get())
            height = int(self.cam_height.get())
            seconds = float(self.cam_seconds.get())
        except ValueError:
            self.camera_status.set("Invalid config values")
            messagebox.showerror("Input Error", "Please enter valid numbers for all configuration values")
            return
        
        # Calculate post-trigger frames from seconds
        post_trigger_frames = int(seconds * fps)
        
        # Validate that the duration is possible
        if post_trigger_frames <= 0:
            self.camera_status.set("Invalid recording duration")
            messagebox.showerror("Input Error", "Recording duration must be greater than 0 seconds")
            return
        
        # Check if duration exceeds reasonable limits (warn if > 10 seconds)
        if seconds > 10:
            proceed = messagebox.askyesno(
                "Long Recording Duration",
                f"Recording duration of {seconds:.2f} seconds ({post_trigger_frames} frames) is quite long.\n\n"
                f"This may exceed camera memory limits depending on resolution and frame rate.\n\n"
                f"Continue anyway?"
            )
            if not proceed:
                return
        
        try:
            # Configure camera with post_trigger_frames - returns actual values (may differ from requested)
            actual_values = self.phantom_camera.configure(width, height, fps, exposure, post_trigger_frames=post_trigger_frames)
            
            # Update GUI with actual values set by camera
            actual_fps = actual_values.get('frame_rate', fps)
            actual_exposure = actual_values.get('exposure', exposure)
            actual_res = actual_values.get('resolution', (width, height))
            actual_post_trigger = actual_values.get('post_trigger_frames', post_trigger_frames)
            
            # Recalculate actual duration from actual frame rate and post_trigger_frames
            actual_duration = actual_post_trigger / actual_fps if actual_fps > 0 else seconds
            
            # Check if values were adjusted
            values_changed = False
            if abs(actual_fps - float(fps)) > 0.1:
                self.cam_fps.set(str(int(actual_fps)))
                values_changed = True
            if abs(actual_exposure - float(exposure)) > 1.0:
                self.cam_exposure_us.set(str(int(actual_exposure)))
                values_changed = True
            if abs(actual_duration - seconds) > 0.01:
                self.cam_seconds.set(f"{actual_duration:.3f}")
                values_changed = True
            
            # Update status message
            status_msg = f"Configured: {actual_res[0]}x{actual_res[1]} @ {actual_fps:.0f} fps, {actual_duration:.3f}s recording"
            if values_changed:
                status_msg += " (adjusted by camera)"
            self.camera_status.set(status_msg)
            
            # Show warning if values were adjusted
            if values_changed:
                warning_msg = "The camera adjusted some values:\n\n"
                if abs(actual_fps - float(fps)) > 0.1:
                    warning_msg += f"Frame Rate: {fps} → {actual_fps:.1f} fps\n"
                if abs(actual_exposure - float(exposure)) > 1.0:
                    warning_msg += f"Exposure: {exposure} → {actual_exposure:.1f}μs\n"
                if abs(actual_duration - seconds) > 0.01:
                    warning_msg += f"Recording Duration: {seconds:.3f}s → {actual_duration:.3f}s ({actual_post_trigger} frames)\n"
                warning_msg += "\nThese are the maximum values for this resolution."
                messagebox.showwarning("Values Adjusted", warning_msg)
            
            self.save_camera_settings()
            print("Camera configuration applied successfully")
        except Exception as e:
            error_msg = f"Failed to configure camera: {str(e)}"
            self.camera_status.set(error_msg)
            messagebox.showerror("Configuration Error", error_msg)
            print(f"Camera configuration error: {e}")

    def cam_record(self):
        """Start camera recording using Phantom SDK"""
        if not self.camera_available:
            self.camera_status.set("Camera not available - SDK not installed")
            return
        
        if not self.phantom_camera or not self.phantom_camera.is_connected:
            self.camera_status.set("Camera not connected - connect first")
            messagebox.showwarning("Not Connected", "Please connect to camera first")
            return
        
        try:
            seconds = float(self.cam_seconds.get())
            if seconds <= 0:
                raise ValueError("Duration must be positive")
        except ValueError:
            self.camera_status.set("Invalid recording duration")
            messagebox.showerror("Input Error", "Please enter a valid recording duration in seconds (e.g., 0.5)")
            return
        
        out = self.cam_output.get().strip()
        if not out:
            self.camera_status.set("Output path required")
            messagebox.showerror("Input Error", "Please enter an output path")
            return
        
        # Resolve any placeholders (like {lacie_drive}) in the path
        resolved_path = resolve_path(out)
        
        # Store output path and duration for saving later
        self.cam_output_path = resolved_path
        self.cam_seconds_to_record = seconds
        
        try:
            # Start recording (arm the camera)
            # Note: post_trigger_frames should already be set during cam_config
            self.phantom_camera.start_recording()
            self.camera_status.set(f"Recording armed - ready to trigger ({seconds:.3f}s)")
            self.cam_capture_btn.configure(text="Trigger", state="normal")
            self.save_camera_settings()
            print(f"Camera recording started (armed) - will record {seconds:.3f} seconds after trigger")
        except Exception as e:
            error_msg = f"Failed to start recording: {str(e)}"
            self.camera_status.set(error_msg)
            messagebox.showerror("Recording Error", error_msg)
            print(f"Camera recording error: {e}")

    def cam_abort(self):
        """Abort camera recording using Phantom SDK"""
        if not self.camera_available:
            self.camera_status.set("Camera not available - SDK not installed")
            return
        
        if not self.phantom_camera:
            return
        
        try:
            self.phantom_camera.abort()
            self.camera_status.set("Recording aborted")
            self.cam_capture_btn.configure(text="Capture", state="normal")
            print("Camera recording aborted")
        except Exception as e:
            error_msg = f"Failed to abort recording: {str(e)}"
            self.camera_status.set(error_msg)
            print(f"Camera abort error: {e}")

    def cam_ping(self):
        """Ping camera using Phantom SDK"""
        if not self.camera_available:
            self.camera_status.set("Camera not available - SDK not installed")
            return
        
        if not self.phantom_camera:
            self.camera_status.set("Camera controller not initialized")
            return
        
        try:
            if self.phantom_camera.ping():
                info = self.phantom_camera.get_camera_info()
                if info:
                    self.camera_status.set(f"Camera OK - {info.get('model', 'Unknown')} @ {info.get('ip_address', 'Unknown IP')}")
                else:
                    self.camera_status.set("Camera OK - connection verified")
                print("Camera ping successful")
            else:
                self.camera_status.set("Camera ping failed - not connected")
                messagebox.showwarning("Connection Error", "Camera is not connected")
        except Exception as e:
            error_msg = f"Camera ping error: {str(e)}"
            self.camera_status.set(error_msg)
            print(f"Camera ping error: {e}")
    
    def _cam_capture_handler(self):
        """Handle capture button click - either start recording or trigger"""
        if not self.phantom_camera or not self.phantom_camera.is_connected:
            # Not connected - do nothing
            return
        
        if not self.phantom_camera.is_recording:
            # Start recording
            self.cam_record()
        else:
            # Trigger and save
            self.cam_trigger()

    def cam_trigger(self):
        """Trigger camera capture and save recording"""
        if not self.camera_available:
            self.camera_status.set("Camera not available - SDK not installed")
            return
        
        if not self.phantom_camera or not self.phantom_camera.is_connected:
            self.camera_status.set("Camera not connected")
            return
        
        if not self.phantom_camera.is_recording:
            self.camera_status.set("Recording not started - start recording first")
            return
        
        try:
            # Trigger the camera
            self.phantom_camera.trigger()
            self.camera_status.set("Camera triggered - saving...")
            self.cam_capture_btn.configure(state="disabled")
            
            # Trigger AFG1062 at the midpoint of the recording
            if (self.afg_controller and self.afg_controller.is_connected):
                try:
                    # Get recording duration
                    seconds = getattr(self, 'cam_seconds_to_record', 0.5)
                    
                    # Calculate delay to trigger at midpoint (half of recording duration)
                    delay_seconds = seconds / 2.0
                    
                    # Get selected channel for AFG
                    channel_str = self.afg_channel.get()
                    channel_num = 1 if channel_str == "CH1" else 2
                    
                    # Schedule AFG trigger after delay
                    def trigger_afg_delayed():
                        try:
                            self.afg_controller.trigger(channel=channel_num)
                            print(f"AFG1062 triggered at midpoint ({delay_seconds:.3f}s after camera trigger)")
                        except Exception as afg_error:
                            print(f"Warning: Failed to trigger AFG1062: {afg_error}")
                    
                    # Use threading.Timer to trigger after delay
                    trigger_timer = threading.Timer(delay_seconds, trigger_afg_delayed)
                    trigger_timer.start()
                    print(f"AFG1062 trigger scheduled for {delay_seconds:.3f}s (midpoint of {seconds:.3f}s recording)")
                except Exception as afg_error:
                    print(f"Warning: Failed to schedule AFG1062 trigger: {afg_error}")
            
            # Wait a moment for recording to complete
            time.sleep(0.5)
            
            # Save the recording in a separate thread to avoid blocking
            threading.Thread(
                target=self._save_recording_thread,
                daemon=True
            ).start()
            
        except Exception as e:
            error_msg = f"Failed to trigger camera: {str(e)}"
            self.camera_status.set(error_msg)
            messagebox.showerror("Trigger Error", error_msg)
            print(f"Camera trigger error: {e}")
    
    def _save_recording_thread(self):
        """Thread function to save recording without blocking GUI"""
        try:
            # Get the recording duration
            seconds = getattr(self, 'cam_seconds_to_record', 0.5)
            
            # Wait for recording to complete (duration + small buffer)
            wait_time = seconds + 1.0  # Extra 1 second buffer
            print(f"Waiting {wait_time:.2f} seconds for recording to complete...")
            time.sleep(wait_time)
            
            # Get the base path (either from user input or default)
            raw_output_path = getattr(self, 'cam_output_path', None)
            if raw_output_path:
                # User specified a path - resolve it and use as base for timestamped folders
                base_path = resolve_path(raw_output_path)
                # If it looks like a full path with filename, use the directory as base
                if os.path.basename(base_path) and os.path.basename(base_path) != os.path.dirname(base_path):
                    # Has a filename component, use parent directory as base
                    base_path = os.path.dirname(base_path) if os.path.dirname(base_path) else base_path
            else:
                # Use default base path
                base_path = self.get_camera_output_base_path()
            
            # Create timestamped folder structure for this video (matching shadowgraph structure)
            # This creates: {base}/Month_Year/Day_Month/Timestamp/run.cine
            now = datetime.now()
            month_folder = now.strftime("%b_%Y")  # e.g., "Jan_2024"
            day_folder = now.strftime("%d_%b")    # e.g., "15_Jan"
            timestamp_folder = now.strftime("%b_%d_%Y_%H_%M_%S")  # e.g., "Jan_15_2024_14_30_45"
            
            # Build full path structure
            month_path = os.path.join(base_path, month_folder)
            day_path = os.path.join(month_path, day_folder)
            timestamp_path = os.path.join(day_path, timestamp_folder)
            
            # Create all folders
            os.makedirs(timestamp_path, exist_ok=True)
            
            # Return path with filename (without extension - save_recording will add .cine)
            output_path = os.path.join(timestamp_path, "run")
            print(f"Created timestamped camera output folder: {timestamp_path}")
            
            # Get the cine to check how many frames were actually recorded
            try:
                cine_obj = self.phantom_camera.cam.Cine(1)
                total_frames = cine_obj.range.last_image - cine_obj.range.first_image + 1
                actual_duration = total_frames / self.phantom_camera.cam.frame_rate
                print(f"Total frames recorded: {total_frames} ({actual_duration:.3f} seconds)")
                
                # Calculate how many frames to save (requested duration)
                frame_rate = self.phantom_camera.cam.frame_rate
                frames_to_save = int(seconds * frame_rate)
                
                # Get post_trigger_frames that was set during configuration
                post_trigger_frames = self.phantom_camera.cam.post_trigger_frames
                
                # Determine trigger point:
                # If post_trigger_frames was set and the camera recorded exactly that many frames after trigger,
                # then trigger point is at: last_image - post_trigger_frames + 1
                # However, if the camera recorded continuously before trigger, we need to find the actual trigger point
                # For now, we'll assume the trigger point is at the start of the post-trigger recording
                # which should be at: last_image - post_trigger_frames + 1
                
                if post_trigger_frames > 0 and post_trigger_frames <= total_frames:
                    # Trigger point is at the start of post-trigger recording
                    trigger_frame = cine_obj.range.last_image - post_trigger_frames + 1
                    print(f"Trigger point detected at frame {trigger_frame} (post_trigger_frames={post_trigger_frames})")
                else:
                    # Fallback: assume trigger is at first frame (if camera was just armed and triggered)
                    trigger_frame = cine_obj.range.first_image
                    print(f"Using first frame as trigger point (frame {trigger_frame})")
                
                # Calculate end frame: trigger_frame + frames_to_save - 1
                end_frame = trigger_frame + frames_to_save - 1
                
                # Make sure we don't exceed available frames
                if end_frame > cine_obj.range.last_image:
                    end_frame = cine_obj.range.last_image
                    frames_to_save = end_frame - trigger_frame + 1
                    actual_saved_duration = frames_to_save / frame_rate
                    print(f"Warning: Requested {seconds:.3f}s but only {actual_saved_duration:.3f}s available")
                
                # Save only the requested duration from trigger point
                frame_range = (trigger_frame, end_frame)
                print(f"Saving {frames_to_save} frames ({seconds:.3f}s) from frame {trigger_frame} to {end_frame}")
                
                # Check if pipeline is enabled
                pipeline_enabled = self.pipeline_enabled.get()
                
                if pipeline_enabled:
                    # Pipeline mode: Save directly as TIFF sequence to TIFF_Output folder
                    try:
                        from config_loader import get_mp4_config
                        config = get_mp4_config()
                        tiff_output_base = config.get('default_tiff_folder', None)
                        if tiff_output_base:
                            tiff_output_base = resolve_path(tiff_output_base)
                        else:
                            # Fallback: use LaCie drive
                            lacie_base = find_lacie_drive()
                            if lacie_base:
                                tiff_output_base = os.path.join(lacie_base, "Phantom", "TIFF_Output")
                            else:
                                tiff_output_base = "D:\\Phantom\\TIFF_Output"
                        
                        # Ensure TIFF_Output folder exists
                        os.makedirs(tiff_output_base, exist_ok=True)
                        
                        # Save as TIFF sequence directly
                        tiff_output_path = os.path.join(tiff_output_base, "run")
                        print(f"Pipeline enabled: Saving TIFF sequence to {tiff_output_base}")
                        self.phantom_camera.save_recording(tiff_output_path, cine_index=1, file_format='tiff', frame_range=frame_range)
                        
                        # Also save .cine file for backup
                        self.phantom_camera.save_recording(output_path, cine_index=1, file_format='cine', frame_range=frame_range)
                        
                        # Start pipeline processing in separate thread
                        threading.Thread(
                            target=self._run_pipeline_thread,
                            args=(tiff_output_base,),
                            daemon=True
                        ).start()
                        
                        actual_saved_duration = frames_to_save / frame_rate
                        status_msg = f"Recording saved + Pipeline started ({frames_to_save} frames, {actual_saved_duration:.3f}s)"
                    except Exception as pipeline_error:
                        print(f"Error in pipeline save: {pipeline_error}")
                        import traceback
                        traceback.print_exc()
                        # Fallback to normal .cine save
                        self.phantom_camera.save_recording(output_path, cine_index=1, file_format='cine', frame_range=frame_range)
                        actual_saved_duration = frames_to_save / frame_rate
                        status_msg = f"Recording saved (pipeline failed: {str(pipeline_error)})"
                else:
                    # Normal mode: Save as .cine file
                    self.phantom_camera.save_recording(output_path, cine_index=1, file_format='cine', frame_range=frame_range)
                    actual_saved_duration = frames_to_save / frame_rate
                    status_msg = f"Recording saved successfully ({frames_to_save} frames, {actual_saved_duration:.3f}s)"
                
            except Exception as cine_error:
                print(f"Error accessing cine object: {cine_error}")
                import traceback
                traceback.print_exc()
                # Fallback: save without checking frame count
                pipeline_enabled = self.pipeline_enabled.get()
                if pipeline_enabled:
                    # Try pipeline save
                    try:
                        from config_loader import get_mp4_config
                        config = get_mp4_config()
                        tiff_output_base = config.get('default_tiff_folder', None)
                        if tiff_output_base:
                            tiff_output_base = resolve_path(tiff_output_base)
                        else:
                            lacie_base = find_lacie_drive()
                            if lacie_base:
                                tiff_output_base = os.path.join(lacie_base, "Phantom", "TIFF_Output")
                            else:
                                tiff_output_base = "D:\\Phantom\\TIFF_Output"
                        os.makedirs(tiff_output_base, exist_ok=True)
                        tiff_output_path = os.path.join(tiff_output_base, "run")
                        self.phantom_camera.save_recording(tiff_output_path, cine_index=1, file_format='tiff')
                        self.phantom_camera.save_recording(output_path, cine_index=1, file_format='cine')
                        threading.Thread(target=self._run_pipeline_thread, args=(tiff_output_base,), daemon=True).start()
                        status_msg = f"Recording saved + Pipeline started ({seconds:.3f}s requested)"
                    except:
                        self.phantom_camera.save_recording(output_path, cine_index=1, file_format='cine')
                        status_msg = f"Recording saved (pipeline failed)"
                else:
                    self.phantom_camera.save_recording(output_path, cine_index=1, file_format='cine')
                    status_msg = f"Recording saved successfully ({seconds:.3f}s requested)"
            
            self.master.after(0, lambda: self.camera_status.set(status_msg))
            self.master.after(0, lambda: self.cam_capture_btn.configure(text="Capture", state="normal"))
            self.master.after(0, lambda: self.phantom_camera.abort())  # Clear recording state
            
            print(f"Recording saved to: {output_path}")
            
        except Exception as e:
            error_msg = f"Failed to save recording: {str(e)}"
            self.master.after(0, lambda: self.camera_status.set(error_msg))
            self.master.after(0, lambda: self.cam_capture_btn.configure(text="Capture", state="normal"))
            messagebox.showerror("Save Error", error_msg)
            print(f"Recording save error: {e}")
            import traceback
            traceback.print_exc()

    def _run_pipeline_thread(self, tiff_output_folder):
        """Run the full pipeline: find brightest frame → process → display result"""
        try:
            # Clear any previous error
            self.master.after(0, lambda: self.pipeline_error_label.configure(text=""))
            self.master.after(0, lambda: self.camera_status.set("Pipeline: Finding brightest frame..."))
            
            # Step 1: Find brightest frame from TIFF_Output
            print("\n[PIPELINE] Step 1: Finding brightest frame...")
            from config_loader import get_mp4_config
            config = get_mp4_config()
            flashed_output_folder = config.get('default_flashed_output', None)
            if flashed_output_folder:
                flashed_output_folder = resolve_path(flashed_output_folder)
            else:
                lacie_base = find_lacie_drive()
                if lacie_base:
                    flashed_output_folder = os.path.join(lacie_base, "Phantom", "Flashed_Output")
                else:
                    flashed_output_folder = "D:\\Phantom\\Flashed_Output"
            
            # Import find_brightest_frame function
            from imaging.mp4_to_tiff import find_brightest_frame
            
            # Find and save brightest frame (will overwrite if exists)
            success = find_brightest_frame(tiff_output_folder, flashed_output_folder)
            if not success:
                raise Exception("Failed to find brightest frame")
            
            flashed_output_path = os.path.join(flashed_output_folder, "flashed_output.tiff")
            if not os.path.exists(flashed_output_path):
                raise Exception(f"Brightest frame not found at {flashed_output_path}")
            
            print(f"[PIPELINE] Brightest frame saved to: {flashed_output_path}")
            self.master.after(0, lambda: self.camera_status.set("Pipeline: Processing image..."))
            
            # Step 2: Run save_and_analyse on flashed_output.tiff
            print("[PIPELINE] Step 2: Processing image with save_and_analyse...")
            from imaging.save_and_analyse import process_and_save_to_lacie
            
            success = process_and_save_to_lacie(flashed_output_path)
            if not success:
                raise Exception("Failed to process image with save_and_analyse")
            
            print("[PIPELINE] Image processing complete!")
            self.master.after(0, lambda: self.camera_status.set("Pipeline: Complete!"))
            
            # Step 3: Refresh shadowgraph image display
            print("[PIPELINE] Step 3: Refreshing GUI display...")
            time.sleep(0.5)  # Small delay to ensure file is written
            self.master.after(0, self.refresh_shadowgraph_image)
            
            print("[PIPELINE] Pipeline completed successfully!")
            
        except Exception as e:
            error_msg = f"Pipeline Error: {str(e)}"
            print(f"[PIPELINE ERROR] {error_msg}")
            import traceback
            traceback.print_exc()
            
            # Display error in left column
            self.master.after(0, lambda: self.pipeline_error_label.configure(text=error_msg))
            self.master.after(0, lambda: self.camera_status.set(f"Pipeline failed: {str(e)}"))

    def get_camera_output_base_path(self):
        """Get base path for camera videos (without timestamped folders)"""
        try:
            # Try to find LaCie drive and use Phantom/Video folder
            lacie_base = find_lacie_drive()
            if lacie_base:
                # Use LaCie drive with Phantom/Video base path
                base_path = resolve_path("{lacie_drive}/Phantom/Video", lacie_base)
                return base_path
            else:
                # Fallback: use local captures folder
                return './camera_settings/captures'
        except Exception as e:
            print(f"Warning: Could not determine camera output base path: {e}")
            return './camera_settings/captures'
    
    def get_timestamped_camera_output_path(self):
        """Get timestamped folder path for camera video (matching shadowgraph structure)"""
        try:
            # Get base path
            base_path = self.get_camera_output_base_path()
            
            # Create timestamped folder structure (same as shadowgraph)
            now = datetime.now()
            month_folder = now.strftime("%b_%Y")  # e.g., "Jan_2024"
            day_folder = now.strftime("%d_%b")    # e.g., "15_Jan"
            timestamp_folder = now.strftime("%b_%d_%Y_%H_%M_%S")  # e.g., "Jan_15_2024_14_30_45"
            
            # Build full path structure
            month_path = os.path.join(base_path, month_folder)
            day_path = os.path.join(month_path, day_folder)
            timestamp_path = os.path.join(day_path, timestamp_folder)
            
            # Create all folders
            os.makedirs(timestamp_path, exist_ok=True)
            
            # Return path with filename (without extension - save_recording will add .cine)
            output_path = os.path.join(timestamp_path, "run")
            print(f"Created timestamped camera output folder: {timestamp_path}")
            return output_path
        except Exception as e:
            print(f"Warning: Could not create timestamped camera output path: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to simple path
            fallback_path = './camera_settings/captures/run'
            os.makedirs(os.path.dirname(fallback_path), exist_ok=True)
            return fallback_path
    
    def get_default_camera_output_path(self):
        """Get default camera output path for display in GUI (base path)"""
        try:
            # Return base path for display - actual save will use timestamped folders
            # Users can see where videos will be saved, but each video gets its own timestamped folder
            base_path = self.get_camera_output_base_path()
            return base_path
        except Exception as e:
            print(f"Warning: Could not determine camera output path: {e}")
            return './camera_settings/captures'

    def save_camera_settings(self):
        """Save camera settings to JSON file"""
        try:
            # Use config for camera settings file path
            settings_file = GUI_CONFIG.get('camera_settings_file', 'src/gui/camera_settings.json')
            # Ensure directory exists
            settings_dir = os.path.dirname(settings_file)
            if settings_dir:
                os.makedirs(settings_dir, exist_ok=True)
            
            data = {
                'ip': self.cam_ip.get(),
                'fps': self.cam_fps.get(),
                'exposure_us': self.cam_exposure_us.get(),
                'width': self.cam_width.get(),
                'height': self.cam_height.get(),
                'seconds': self.cam_seconds.get(),
                'output': self.cam_output.get(),
            }
            with open(settings_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Camera settings save error: {e}")

    def load_camera_settings(self):
        """Load camera settings from JSON file"""
        try:
            # Use config for camera settings file path
            settings_file = GUI_CONFIG.get('camera_settings_file', 'src/gui/camera_settings.json')
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    data = json.load(f)
                self.cam_ip.set(data.get('ip', '100.100.100.1'))
                self.cam_fps.set(data.get('fps', '1000'))
                self.cam_exposure_us.set(data.get('exposure_us', '500'))
                self.cam_width.set(data.get('width', '640'))
                self.cam_height.set(data.get('height', '480'))
                # Handle migration from 'frames' to 'seconds' (convert old frames to seconds)
                if 'seconds' in data:
                    self.cam_seconds.set(data.get('seconds', '0.02'))
                elif 'frames' in data:
                    # Convert old frames value to seconds (assuming 1000 fps default)
                    old_frames = int(data.get('frames', '20'))
                    default_fps = int(data.get('fps', '1000'))
                    seconds = old_frames / default_fps if default_fps > 0 else 0.02
                    self.cam_seconds.set(f"{seconds:.3f}")
                else:
                    self.cam_seconds.set('0.02')
                # Prioritize LaCie drive path if available, otherwise use saved path
                try:
                    lacie_drive = find_lacie_drive()
                    print(f"[DEBUG] LaCie drive detection result: {lacie_drive}")
                    if lacie_drive:
                        # LaCie drive found - use it (preferred location)
                        default_path = self.get_default_camera_output_path()
                        print(f"[DEBUG] Setting camera output to LaCie path: {default_path}")
                        self.cam_output.set(default_path)
                    else:
                        # No LaCie drive - use saved path or fallback
                        saved_output = data.get('output', None)
                        if saved_output:
                            # Resolve any placeholders in saved path
                            resolved = resolve_path(saved_output)
                            print(f"[DEBUG] No LaCie drive found, using saved path: {resolved}")
                            self.cam_output.set(resolved)
                        else:
                            fallback = self.get_default_camera_output_path()
                            print(f"[DEBUG] No LaCie drive found, using fallback: {fallback}")
                            self.cam_output.set(fallback)
                except Exception as e:
                    print(f"[ERROR] Error detecting LaCie drive: {e}")
                    import traceback
                    traceback.print_exc()
                    # Fallback to saved path
                    saved_output = data.get('output', None)
                    if saved_output:
                        self.cam_output.set(resolve_path(saved_output))
                    else:
                        self.cam_output.set(self.get_default_camera_output_path())
            else:
                # reasonable defaults
                self.cam_ip.set('100.100.100.1')
                self.cam_fps.set('1000')
                self.cam_exposure_us.set('500')
                self.cam_width.set('640')
                self.cam_height.set('480')
                self.cam_seconds.set('0.02')  # 20 frames at 1000 fps = 0.02 seconds
                self.cam_output.set(self.get_default_camera_output_path())
        except Exception as e:
            print(f"Camera settings load error: {e}")

    def auto_save_pressure_graph(self):
        """Auto-save pressure data when experiment completes - saves CSV data instead of graph"""
        if len(self.pressure_data['experiment_data']['timestamps']) > 0:
            try:
                # Create pressure_graphs folder if it doesn't exist
                graphs_folder = "pressure_graphs"
                os.makedirs(graphs_folder, exist_ok=True)
                
                # Use the exact TIMESTAMP column format for title and filename (sanitize for filename)
                timestamp_display = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
                timestamp_file = timestamp_display.replace(":", "-").replace(" ", "_")

                # Save data as CSV instead of creating a graph
                csv_filename = os.path.join(graphs_folder, f"test_pressure_data_{timestamp_file}.csv")
                
                # Create CSV with time and pressure data
                import csv
                with open(csv_filename, 'w', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(['Time (s)', 'Pressure (BAR)'])  # Header
                    for i in range(len(self.pressure_data['experiment_data']['timestamps'])):
                        writer.writerow([
                            f"{self.pressure_data['experiment_data']['timestamps'][i]:.1f}",
                            f"{self.pressure_data['experiment_data']['pressures'][i]:.2f}"
                        ])
                
                self.pressure_data['saved_graph_filename'] = csv_filename
                print(f"Pressure data saved as CSV: {csv_filename}")
                
            except Exception as e:
                print(f"Error saving pressure data: {e}")
        else:
            print("No experiment pressure data to save")

    def update_pressure_graph(self):
        """Update the pressure graph with current data - shows last 6 seconds from live buffer"""
        # Always use live_buffer for display
        if len(self.pressure_data['live_buffer']['timestamps']) > 0:
            # Get current time for rolling window
            current_time = self.pressure_data['live_buffer']['timestamps'][-1]
            window_start = max(0, current_time - 6)  # Last 6 seconds
            
            # Filter data to show only last 6 seconds
            window_times = []
            window_pressures = []
            for i, timestamp in enumerate(self.pressure_data['live_buffer']['timestamps']):
                if timestamp >= window_start:
                    window_times.append(timestamp)
                    window_pressures.append(self.pressure_data['live_buffer']['pressures'][i])
            
            # Update the line data with windowed data
            self.pressure_line.set_data(window_times, window_pressures)
            
            # Set fixed window for live display (last 6 seconds)
            self.ax.set_xlim(window_start, current_time + 1)  # 1 second buffer
            
            # Y-axis: Scale to 1.2x the maximum pressure in the window
            if window_pressures:
                max_pressure = max(window_pressures)
                y_max = max_pressure * 1.2
                self.ax.set_ylim(0, y_max)
            
            # Redraw canvas
            self.canvas.draw_idle()
    
    def add_live_pressure_data_point(self, pressure_value):
        """Add a new pressure data point to the always-on live buffer"""
        # Use absolute time for live buffer (time since GUI started or since buffer was initialized)
        if self.pressure_data['live_buffer_start_time'] is None:
            self.pressure_data['live_buffer_start_time'] = time.time()
        current_time = time.time() - self.pressure_data['live_buffer_start_time']
        
        # Add to live buffer
        self.pressure_data['live_buffer']['timestamps'].append(current_time)
        self.pressure_data['live_buffer']['pressures'].append(pressure_value)
        
        # Clean up old data (keep only last 10 seconds worth to save memory)
        cutoff_time = current_time - 10
        while (len(self.pressure_data['live_buffer']['timestamps']) > 0 and 
               self.pressure_data['live_buffer']['timestamps'][0] < cutoff_time):
            self.pressure_data['live_buffer']['timestamps'].pop(0)
            self.pressure_data['live_buffer']['pressures'].pop(0)
        
        # Always update graph (always-on display)
        self.update_pressure_graph()
    
    def add_experiment_pressure_data_point(self, pressure_value):
        """Add a new pressure data point to experiment buffer (for saving)"""
        if self.pressure_data['experiment_active'] and self.pressure_data['experiment_start_time'] is not None:
            # Use relative time for experiment (time since experiment started)
            current_time = time.time() - self.pressure_data['experiment_start_time']
            self.pressure_data['experiment_data']['timestamps'].append(current_time)
            self.pressure_data['experiment_data']['pressures'].append(pressure_value)


    def start_pressure_monitoring(self):
        """Start experiment data recording (for saving) - live graph continues"""
        self.pressure_data['experiment_active'] = True
        self.pressure_data['experiment_data']['timestamps'] = []
        self.pressure_data['experiment_data']['pressures'] = []
        self.pressure_data['experiment_start_time'] = time.time()
        print("Experiment pressure recording started (live graph continues)")

    def stop_pressure_monitoring(self):
        """Stop experiment data recording (live graph continues)"""
        self.pressure_data['experiment_active'] = False
        print("Experiment pressure recording stopped (live graph continues)")

    def afg_connect(self):
        """Connect to AFG1062"""
        if not self.afg_available:
            self.afg_status.set("AFG not available - PyVISA not installed")
            messagebox.showerror("PyVISA Error", 
                               "PyVISA is not installed.\n\n"
                               "Install with: pip install pyvisa\n\n"
                               "You may also need VISA drivers from National Instruments or Tektronix.")
            return
        
        if not self.afg_controller:
            self.afg_controller = AFGController()
        
        try:
            resource_name = self.afg_resource_name.get().strip()
            if resource_name:
                self.afg_controller.connect(resource_name=resource_name)
            else:
                self.afg_controller.connect()  # Auto-detect
            
            self.afg_status.set("AFG: Connected")
            print("AFG1062 connected successfully")
        except Exception as e:
            error_msg = f"Failed to connect to AFG1062: {str(e)}"
            self.afg_status.set(f"Connection error: {str(e)}")
            messagebox.showerror("Connection Error", 
                               f"{error_msg}\n\n"
                               "Make sure:\n"
                               "1. AFG1062 is connected via USB\n"
                               "2. VISA drivers are installed\n"
                               "3. Device is powered on")
            print(f"AFG1062 connection error: {e}")
    
    def afg_configure(self):
        """Configure AFG1062 pulse settings"""
        if not self.afg_available:
            self.afg_status.set("AFG not available - PyVISA not installed")
            return
        
        if not self.afg_controller or not self.afg_controller.is_connected:
            self.afg_status.set("AFG not connected - connect first")
            messagebox.showwarning("Not Connected", "Please connect to AFG1062 first")
            return
        
        try:
            duration = float(self.afg_pulse_duration.get())
            if duration <= 0:
                raise ValueError("Duration must be positive")
        except ValueError:
            self.afg_status.set("Invalid pulse duration")
            messagebox.showerror("Input Error", "Please enter a valid pulse duration in seconds (e.g., 0.001 for 1ms)")
            return
        
        try:
            # Get selected channel (CH1 or CH2 -> 1 or 2)
            channel_str = self.afg_channel.get()
            channel_num = 1 if channel_str == "CH1" else 2
            
            # Configure pulse (default: 5V amplitude, 1000Hz frequency)
            self.afg_controller.configure_pulse(duration_seconds=duration, amplitude_volts=5.0, frequency_hz=1000, channel=channel_num)
            
            # Enable output
            self.afg_controller.enable_output(channel=channel_num)
            
            self.afg_status.set(f"AFG {channel_str}: Configured ({duration*1000:.3f}ms pulse)")
            print(f"AFG1062 {channel_str} configured: {duration*1000:.3f}ms pulse")
        except Exception as e:
            error_msg = f"Failed to configure AFG1062: {str(e)}"
            self.afg_status.set(error_msg)
            messagebox.showerror("Configuration Error", error_msg)
            print(f"AFG1062 configuration error: {e}")
    
    def afg_test(self):
        """Test trigger a pulse from AFG1062"""
        if not self.afg_available:
            self.afg_status.set("AFG not available - PyVISA not installed")
            messagebox.showwarning("Not Available", "PyVISA is not installed")
            return
        
        if not self.afg_controller or not self.afg_controller.is_connected:
            self.afg_status.set("AFG not connected - connect first")
            messagebox.showwarning("Not Connected", "Please connect to AFG1062 first")
            return
        
        try:
            # Get selected channel
            channel_str = self.afg_channel.get()
            channel_num = 1 if channel_str == "CH1" else 2
            
            # Check if configured - try to trigger, will fail if not configured
            self.afg_controller.trigger(channel=channel_num)
            self.afg_status.set(f"AFG {channel_str}: Test pulse sent ")
            print(f"AFG1062 {channel_str} test pulse triggered successfully")
        except RuntimeError as e:
            error_msg = str(e)
            if "not connected" in error_msg.lower():
                self.afg_status.set("AFG not connected")
                messagebox.showwarning("Not Connected", "Please connect to AFG1062 first")
            else:
                self.afg_status.set("AFG: Configure first")
                messagebox.showwarning("Not Configured", 
                                     "Please configure the AFG first using 'Apply Config'.\n\n"
                                     "The AFG needs to be configured with pulse settings before it can be triggered.")
            print(f"AFG1062 test error: {e}")
        except Exception as e:
            error_msg = f"Failed to trigger test pulse: {str(e)}"
            self.afg_status.set("AFG: Test failed")
            messagebox.showerror("Test Error", error_msg)
            print(f"AFG1062 test error: {e}")
    
    def afg_disconnect(self):
        """Disconnect from AFG1062"""
        if not self.afg_controller:
            return
        
        try:
            self.afg_controller.disconnect()
            self.afg_status.set("AFG: Not connected")
            print("AFG1062 disconnected")
        except Exception as e:
            print(f"Error disconnecting AFG1062: {e}")
            self.afg_status.set("AFG: Disconnect error")

    def disconnect_from_arduino(self):
        """Close persistent connection to Arduino"""
        try:
            # Stop the serial reader thread
            self.serial_reading_active = False
            print("Stopping serial reader thread...")
            
            # Wait for thread to finish
            if self.serial_reader_thread and self.serial_reader_thread.is_alive():
                print("Waiting for serial reader thread to finish...")
                self.serial_reader_thread.join(timeout=2.0)
            
            # Disconnect Arduino
            if self.arduino:
                if hasattr(self.arduino, 'ser') and self.arduino.ser and self.arduino.ser.is_open:
                    self.arduino.disconnect()
                self.arduino = None
            
            print("Disconnected from Arduino")
        except Exception as e:
            print(f"Error disconnecting: {e}")
            # Force cleanup even on error
            self.arduino = None
            self.serial_reading_active = False

if __name__ == "__main__":
    root = ctk.CTk()
    app = ModernExperimentControlApp(root)
    
    def on_closing():
        try:
            # Stop any active experiments
            if hasattr(app, 'serial_reading_active'):
                app.serial_reading_active = False
        except Exception:
            pass
        
        try:
            app.save_camera_settings()
        except Exception:
            pass
        
        print("Closing GUI - disconnecting from Arduino...")
        app.disconnect_from_arduino()
        
        # Disconnect camera
        if hasattr(app, 'phantom_camera') and app.phantom_camera:
            try:
                app.phantom_camera.disconnect()
                print("Camera disconnected")
            except Exception as e:
                print(f"Error disconnecting camera: {e}")
        
        # Disconnect AFG1062
        if hasattr(app, 'afg_controller') and app.afg_controller:
            try:
                app.afg_controller.disconnect()
                print("AFG1062 disconnected")
            except Exception as e:
                print(f"Error disconnecting AFG1062: {e}")
        
        # Clean up temporary ICO file
        if hasattr(app, 'temp_ico_path') and app.temp_ico_path and os.path.exists(app.temp_ico_path):
            try:
                os.remove(app.temp_ico_path)
                print("Cleaned up temporary icon file")
            except Exception as e:
                print(f"Could not clean up icon file: {e}")
        
        # Destroy the window
        try:
            root.quit()  # Stop the mainloop
        except:
            pass
        root.destroy()
        print("GUI closed successfully")
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
