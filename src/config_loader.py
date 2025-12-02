"""
Configuration loader for HPATR.
Loads paths from config/paths.yaml (or paths_example.yaml as fallback).
"""
import os
import yaml
from pathlib import Path

# Get the project root (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

def load_config():
    """Load configuration from paths.yaml or paths_example.yaml"""
    config_file = CONFIG_DIR / "paths.yaml"
    example_file = CONFIG_DIR / "paths_example.yaml"
    
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        print(f"✓ Loaded config from: {config_file}")
    elif example_file.exists():
        with open(example_file, 'r') as f:
            config = yaml.safe_load(f)
        print(f"⚠ Using example config (create config/paths.yaml to customize): {example_file}")
    else:
        # Fallback to hardcoded defaults
        print("⚠ No config file found, using hardcoded defaults")
        config = {
            'imaging': {
                'default_input_dir': '/Volumes/LaCie/Phantom/Flashed_Output',
                'default_input_file': 'flashed_output.tiff',
                'output_root': '/Volumes/LaCie/Shadowgraph'
            },
            'gui': {
                'experiment_log_dir': '/Volumes/LaCie/Experiments/Logs',
                'serial_log_file': 'serial_log.txt',
                'camera_settings_file': str(PROJECT_ROOT / 'src' / 'gui' / 'camera_settings.json')
            },
            'mp4_to_tiff': {
                'default_video_path': '/Volumes/LaCie/Phantom/Video/5fps_First_Cine_Trial.mp4',
                'default_tiff_folder': '/Volumes/LaCie/Phantom/TIFF_Output',
                'default_flashed_output': '/Volumes/LaCie/Phantom/Flashed_Output'
            }
        }
    
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

