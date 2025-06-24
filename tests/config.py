import os
class Config:
    PROMPT = 'moondream>'
    EXIT_MESSAGE = r'Exiting Moondream CLI'
    
    UPDATE_COMPLETION = {
        'model': r'All component updates have been processed',
        'cli': r'CLI update complete\. Please restart the CLI',
        'bootstrap': r'(Restart.*for update|Starting update process)',
        'hypervisor_complete': r'Hypervisor.*update.*completed',
        'hypervisor_off': r'Server status: Hypervisor: off, Inference: off'
    }
    
    STATUS_INDICATORS = {
        'up_to_date': 'Up to date',
        'update_available': 'Update available'
    }
    
    COMPONENT_NAMES = ['Bootstrap', 'Hypervisor', 'CLI', 'Model']
    VALIDAITON_COMPONENTS = ['bootstrap', 'hypervisor', 'cli', 'inference_client']
    
    MODEL_FIELDS = {
        'name': 'Model: ',
        'release_date': 'Release Date: ',
        'size': 'Size: ',
        'notes': 'Notes: '
    }
    
    MODEL_CHANGE = {
        'success': r'Model initialization completed successfully'
    }

    MANIFEST_VERSIONS = [1, 2, 3, 4, 5]
    
    VERSION_Config = {
        'check_updates': {
            'bootstrap': r'Bootstrap:\s+(v\d+\.\d+\.\d+)\s+-\s+(.+)',
            'hypervisor': r'Hypervisor:\s+(v\d+\.\d+\.\d+)\s+-\s+(.+)',
            'cli': r'CLI:\s+(v\d+\.\d+\.\d+)\s+-\s+(.+)',
            'model': r'Model:\s+([^-]+)\s+-\s+(.+)'
        },
        'get_config': {
            'bootstrap': r'active_bootstrap:\s+(v\d+\.\d+\.\d+)',
            'hypervisor': r'active_hypervisor:\s+(v\d+\.\d+\.\d+)',
            'cli': r'active_cli:\s+(v\d+\.\d+\.\d+)',
            'inference_client': r'active_inference_client:\s+(v\d+\.\d+\.\d+)',
            'model': r'active_model:\s+(.+)'
        }
    }

    MANIFEST_PATH = os.path.expanduser("~/.local/share/MoondreamStation/manifest.py")
    MANIFEST_URL_PATTERN = r'MANIFEST_URL\s*=\s*["\']([^"\']+)["\']'
    MODEL_CATEGORY = '2b'

class Timeouts:
    QUICK = 15
    STANDARD = 60
    STARTUP = 60
    UPDATE = 300
    RECOVERY = 30