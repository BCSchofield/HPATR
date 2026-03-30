# Merge term 1
"""
Configuration loader for HPATR.
Loads paths from config/paths.yaml (or paths_example.yaml as fallback).
Automatically detects OS and LaCie drive location.
"""
import os
import platform
from pathlib import Path

# Make yaml import optional - drive detection doesn't need it
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    print("[WARNING] PyYAML not installed - config file loading will be disabled")

# Get the project root (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

def detect_os():
    """Detect the operating system"""
    return platform.system()

def find_lacie_drive():
    """
    Automatically find the LaCie drive on the system.
    Returns the base path to the LaCie drive, or None if not found.
    """
    system = detect_os()
    
    if system == "Darwin":  # macOS
        # On Mac, LaCie drives are typically mounted at /Volumes/LaCie
        lacie_path = Path("/Volumes/LaCie")
        if lacie_path.exists():
            return str(lacie_path)
        # Also check for other common LaCie volume names
        volumes = Path("/Volumes")
        if volumes.exists():
            for vol in volumes.iterdir():
                if "lacie" in vol.name.lower():
                    return str(vol)
        # Fallback: Backup_PhD is a secondary drive that also holds the data
        backup_path = Path("/Volumes/Backup_PhD")
        if backup_path.exists():
            return str(backup_path)
    
    elif system == "Windows":
        # On Windows, check common drive letters (D:, E:, F:, etc.)
        import string
        for drive_letter in string.ascii_uppercase[3:]:  # Start from D: (skip A:, B:, C:)
            drive_path = Path(f"{drive_letter}:\\")
            if drive_path.exists():
                # Check if it's a LaCie drive by looking for common LaCie folder names
                try:
                    # Check for LaCie-specific folders or volume label
                    has_lacie = (drive_path / "LaCie").exists()
                    has_phantom = (drive_path / "Phantom").exists()
                    has_shadowgraph = (drive_path / "Shadowgraph").exists()
                    
                    print(f"[DEBUG] Checking drive {drive_letter}:\\ - LaCie: {has_lacie}, Phantom: {has_phantom}, Shadowgraph: {has_shadowgraph}")
                    
                    if has_lacie or has_phantom or has_shadowgraph:
                        print(f"[DEBUG] LaCie drive detected at {drive_letter}:\\")
                        return f"{drive_letter}:\\"
                    # Also check volume label (Windows-specific)
                    try:
                        import win32api
                        volume_label = win32api.GetVolumeInformation(f"{drive_letter}:\\")[0]
                        print(f"[DEBUG] Drive {drive_letter}:\\ volume label: '{volume_label}'")
                        if "lacie" in volume_label.lower():
                            print(f"[DEBUG] LaCie drive detected by volume label at {drive_letter}:\\")
                            return f"{drive_letter}:\\"
                    except (ImportError, Exception) as e:
                        print(f"[DEBUG] Could not check volume label for {drive_letter}:\\ - {e}")
                        pass  # win32api not available, skip volume label check
                except (PermissionError, OSError) as e:
                    print(f"[DEBUG] Permission/OS error checking drive {drive_letter}:\\ - {e}")
                    continue  # Can't access this drive, try next
    
    # Linux/other - check /media and /mnt
    elif system == "Linux":
        for mount_point in ["/media", "/mnt"]:
            mount_path = Path(mount_point)
            if mount_path.exists():
                for vol in mount_path.iterdir():
                    if "lacie" in vol.name.lower():
                        return str(vol)
    
    return None

def resolve_path(path_str, lacie_base=None):
    """
    Resolve a path string, replacing placeholders and handling OS-specific paths.
    
    Args:
        path_str: Path string that may contain {lacie_drive} placeholder
        lacie_base: Base path to LaCie drive (auto-detected if None)
    
    Returns:
        Resolved path string with OS-appropriate separators
    """
    if not path_str:
        return path_str
    
    system = detect_os()
    
    # Replace {lacie_drive} placeholder if present
    if "{lacie_drive}" in path_str or "{LACIE_DRIVE}" in path_str:
        if lacie_base is None:
            lacie_base = find_lacie_drive()
        
        if lacie_base:
            # Replace placeholder with actual LaCie drive path
            path_str = path_str.replace("{lacie_drive}", lacie_base)
            path_str = path_str.replace("{LACIE_DRIVE}", lacie_base)
        else:
            # LaCie drive not found - use OS-specific default
            if system == "Darwin":
                default_lacie = "/Volumes/LaCie"
            elif system == "Windows":
                default_lacie = "D:\\"  # Common default for external drives
            else:
                default_lacie = "/media/lacie"  # Linux default
            
            path_str = path_str.replace("{lacie_drive}", default_lacie)
            path_str = path_str.replace("{LACIE_DRIVE}", default_lacie)
    
    # Normalize path separators for current OS using Path
    # Path automatically handles OS-specific separators
    path_obj = Path(path_str)
    
    # Convert to string with OS-appropriate separators
    # On Windows, Path will use backslashes; on Unix, forward slashes
    return str(path_obj)

def get_os_default_paths(lacie_base=None):
    """
    Get OS-specific default paths.
    
    Args:
        lacie_base: Base path to LaCie drive (auto-detected if None)
    
    Returns:
        Dictionary of default paths for the current OS
    """
    system = detect_os()
    
    if lacie_base is None:
        lacie_base = find_lacie_drive()
    
    if lacie_base:
        # LaCie drive found - use it
        base = lacie_base
    else:
        # LaCie drive not found - use OS-specific defaults
        if system == "Darwin":
            base = "/Volumes/LaCie"
        elif system == "Windows":
            base = "D:\\"
        else:
            base = "/media/lacie"
    
    # Normalize path separators
    if system == "Windows":
        # Ensure Windows-style paths
        base = base.replace("/", "\\")
        if not base.endswith("\\"):
            base += "\\"
        sep = "\\"
    else:
        # Unix-style paths
        base = base.replace("\\", "/")
        if not base.endswith("/"):
            base += "/"
        sep = "/"
    
    defaults = {
        'imaging': {
            'default_input_dir': f"{base}Phantom{sep}Flashed_Output",
            'default_input_file': 'flashed_output.tiff',
            'output_root': f"{base}Shadowgraph"
        },
        'gui': {
            'experiment_log_dir': f"{base}Experiments{sep}Logs",
            'serial_log_file': 'serial_log.txt',
            'camera_settings_file': str(PROJECT_ROOT / 'src' / 'gui' / 'camera_settings.json')
        },
        'mp4_to_tiff': {
            'default_video_path': f"{base}Phantom{sep}Video{sep}Shadowgraph_Video.mp4",
            'default_tiff_folder': f"{base}Phantom{sep}TIFF_Output",
            'default_flashed_output': f"{base}Phantom{sep}Flashed_Output"
        }
    }
    
    return defaults

def load_config():
    """Load configuration from paths.yaml or paths_example.yaml, with OS-aware path resolution"""
    config_file = CONFIG_DIR / "paths.yaml"
    example_file = CONFIG_DIR / "paths_example.yaml"
    
    # Find LaCie drive once for all path resolution
    lacie_base = find_lacie_drive()
    if lacie_base:
        print(f"Detected LaCie drive at: {lacie_base}")
    else:
        system = detect_os()
        print(f"[WARNING] LaCie drive not found (OS: {system}). Using OS-specific defaults.")
    
    if not YAML_AVAILABLE:
        # If yaml is not available, use OS-aware defaults
        print("[WARNING] PyYAML not available - using OS-aware defaults")
        return get_os_default_paths(lacie_base)
    
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        print(f"Loaded config from: {config_file}")
    elif example_file.exists():
        with open(example_file, 'r') as f:
            config = yaml.safe_load(f)
        print(f"[WARNING] Using example config (create config/paths.yaml to customize): {example_file}")
    else:
        # Fallback to OS-aware defaults
        print("[WARNING] No config file found, using OS-aware defaults")
        config = get_os_default_paths(lacie_base)
    
    # Resolve all paths in the config (handle placeholders and normalize)
    # Known path keys that should always be resolved
    path_keys = {
        'imaging': ['default_input_dir', 'output_root'],
        'gui': ['experiment_log_dir', 'camera_settings_file', 'phantom_sdk_path'],
        'mp4_to_tiff': ['default_video_path', 'default_tiff_folder', 'default_flashed_output']
    }
    
    if config:
        for section_name, section_data in config.items():
            if isinstance(section_data, dict):
                for key, value in section_data.items():
                    # Resolve if it's a known path key or if it looks like a path
                    if isinstance(value, str) and value:
                        should_resolve = (
                            key in path_keys.get(section_name, []) or
                            '{lacie_drive}' in value or
                            '{LACIE_DRIVE}' in value or
                            (value.startswith('/') and len(value) > 1) or
                            (len(value) > 2 and value[1] == ':' and value[2] in ['/', '\\'])  # Windows drive letter
                        )
                        if should_resolve:
                            config[section_name][key] = resolve_path(value, lacie_base)
    
    return config

# Global config instance
_config = None

def get_config():
    """Get the global config instance (lazy-loaded)"""
    global _config
    if _config is None:
        _config = load_config()
    return _config

def get_imaging_config():
    """Get imaging-specific config"""
    return get_config().get('imaging', {})

def get_gui_config():
    """Get GUI-specific config"""
    return get_config().get('gui', {})

def get_mp4_config():
    """Get mp4_to_tiff-specific config"""
    return get_config().get('mp4_to_tiff', {})

