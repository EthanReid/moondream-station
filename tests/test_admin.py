#!/usr/bin/env python3
import pexpect
import re
import json
import time
import logging
import argparse
from pathlib import Path

# Configuration
PROMPT = 'moondream>'
TIMEOUTS = {'quick': 15, 'standard': 60, 'startup': 100, 'update': 300}
MANIFEST_DIR = Path('./test_manifests')

UPDATE_PATTERNS = {
    'bootstrap': r'(Restart.*for update|Starting update process)',
    'hypervisor': r'Hypervisor.*update.*completed',
    'model': r'All component updates have been processed',
    'cli': r'CLI update complete\. Please restart the CLI'
}

# Core Functions
def start_server(executable='./moondream_station', args=None):
    """Start server and wait for prompt."""
    cmd = [executable] + (args or [])
    logging.debug(f"Starting: {' '.join(cmd)}")
    
    process = pexpect.spawn(' '.join(cmd))
    process.expect(PROMPT, timeout=TIMEOUTS['startup'])
    return process

def run_command(process, cmd, timeout=None):
    """Execute command and return output."""
    timeout = timeout or TIMEOUTS['standard']
    logging.debug(f"Running: {cmd}")
    
    process.sendline(cmd)
    process.expect(PROMPT, timeout=timeout)
    return process.before.decode().strip()

def restart_server(process, executable='./moondream_station', args=None):
    """Force restart server."""
    if process.isalive():
        process.close(force=True)
    time.sleep(2)
    return start_server(executable, args)

def update_manifest(version):
    """Copy manifest version file to current."""
    src = MANIFEST_DIR / f'manifest_v{version:03d}.json'
    dst = MANIFEST_DIR / 'manifest.json'
    
    if not src.exists():
        raise FileNotFoundError(f"Manifest {src} not found")
    
    import shutil
    shutil.copy2(src, dst)
    logging.debug(f"Updated manifest to v{version:03d}")

def parse_update_status(output):
    """Parse check-updates output to component status dict."""
    status = {}
    for line in output.split('\n'):
        if 'Up to date' in line:
            comp = line.split(':')[0].strip()
            status[comp] = 'up_to_date'
        elif 'Update available' in line:
            comp = line.split(':')[0].strip()
            status[comp] = 'update_available'
    return status

def check_update_status(process, expected):
    """Verify update status matches expected."""
    output = run_command(process, 'admin check-updates')
    actual = parse_update_status(output)
    
    for comp, status in expected.items():
        if actual.get(comp) != status:
            logging.error(f"{comp}: expected {status}, got {actual.get(comp)}")
            return False
    return True

def get_versions(process):
    """Extract component versions from check-updates and config."""
    updates = run_command(process, 'admin check-updates')
    config = run_command(process, 'admin get-config')
    
    versions = {}
    
    # Parse from check-updates
    for match in re.finditer(r'(\w+):\s+(v[\d.]+)', updates):
        versions[match.group(1).lower()] = match.group(2)
    
    # Parse from config (for inference_client)
    if match := re.search(r'active_inference_client:\s+(v[\d.]+)', config):
        versions['inference_client'] = match.group(1)
    
    return versions

def validate_versions(process, manifest_version, components=None):
    """Check versions match manifest expectations."""
    manifest_file = MANIFEST_DIR / f'manifest_v{manifest_version:03d}.json'
    
    with open(manifest_file) as f:
        expected = json.load(f)
    
    actual = get_versions(process)
    components = components or ['bootstrap', 'hypervisor', 'cli', 'inference_client']
    
    for comp in components:
        exp_key = f'{comp}_version'
        if exp_key in expected and expected[exp_key] != actual.get(comp):
            logging.error(f"{comp}: expected {expected[exp_key]}, got {actual.get(comp)}")
            return False
    
    return True

def do_update(process, update_type, command, executable, args):
    """Execute update command and restart."""
    logging.debug(f"Starting {update_type} update")
    
    if update_type == 'bootstrap':
        # Bootstrap exits immediately
        process.sendline(command)
        try:
            process.expect(UPDATE_PATTERNS['bootstrap'], timeout=TIMEOUTS['update'])
        except pexpect.EOF:
            pass
    else:
        # Other updates return to prompt or exit
        process.sendline(command)
        try:
            idx = process.expect([UPDATE_PATTERNS.get(update_type, pexpect.TIMEOUT), PROMPT], 
                                timeout=TIMEOUTS['update'])
            if idx == 0:  # Found completion pattern
                try:
                    process.sendline('exit')
                    process.expect(pexpect.EOF, timeout=TIMEOUTS['quick'])
                except:
                    pass
        except pexpect.TIMEOUT:
            logging.warning(f"{update_type} update timeout")
    
    return restart_server(process, executable, args)

def test_model_switch(process, model_name, expected_client=None):
    """Test switching to a model."""
    output = run_command(process, f'admin model-use "{model_name}" --confirm', 
                        timeout=TIMEOUTS['update'])
    
    if 'Model initialization completed successfully' not in output:
        logging.error(f"Model switch to {model_name} failed")
        return False
    
    config = run_command(process, 'admin get-config')
    
    # Verify model
    if match := re.search(r'active_model:\s+(.+)', config):
        if match.group(1).strip() != model_name:
            logging.error(f"Model mismatch: expected {model_name}, got {match.group(1)}")
            return False
    
    # Verify client if specified
    if expected_client:
        if match := re.search(r'active_inference_client:\s+(v[\d.]+)', config):
            if match.group(1) != expected_client:
                logging.error(f"Client mismatch: expected {expected_client}, got {match.group(1)}")
                return False
    
    return True

def test_inference_clients(process, version):
    """Test model switches update inference client correctly."""
    manifest_file = MANIFEST_DIR / f'manifest_v{version:03d}.json'
    
    with open(manifest_file) as f:
        models = json.load(f).get('models', {})
    
    for model, data in models.items():
        if 'inference_client_version' in data:
            if not test_model_switch(process, model, data['inference_client_version']):
                return False
    
    return True

# Main Test Sequence
def main():
    parser = argparse.ArgumentParser(description='Test Moondream Station updates')
    parser.add_argument('--executable', default='./moondream_station')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--no-cleanup', action='store_true')
    parser.add_argument('--manifest-url', help='URL to manifest.json for testing')
    args, server_args = parser.parse_known_args()
    
    # Add manifest URL to server args if provided
    if args.manifest_url:
        server_args = ['--manifest-url', args.manifest_url] + server_args
    
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s: %(message)s',
        handlers=[
            logging.FileHandler('test_updates.log', mode='w'),
            logging.StreamHandler() if args.verbose else logging.NullHandler()
        ]
    )
    
    # Initialize
    update_manifest(1)
    process = start_server(args.executable, server_args)
    
    try:
        # Refresh manifest
        run_command(process, 'admin update-manifest')
        
        # Test v001 - Baseline
        if not check_update_status(process, {
            'Bootstrap': 'up_to_date',
            'Hypervisor': 'up_to_date', 
            'CLI': 'up_to_date',
            'Model': 'up_to_date'
        }):
            return False
        
        if not validate_versions(process, 1):
            return False
        
        # Test updates v002-v006
        tests = [
            (2, 'bootstrap', 'admin update-bootstrap --confirm'),
            (3, 'hypervisor', 'admin update-hypervisor --confirm'),
            (4, 'model', 'admin update --confirm'),
            (5, 'cli', 'admin update --confirm'),
            (6, 'inference_client', None)  # Special case
        ]
        
        for version, component, command in tests:
            # Update manifest
            update_manifest(version)
            run_command(process, 'admin update-manifest')
            
            # Special handling for inference_client
            if component == 'inference_client':
                if not test_inference_clients(process, version):
                    return False
                if not validate_versions(process, version, ['inference_client']):
                    return False
            else:
                # Check update available
                expected = {
                    'Bootstrap': 'up_to_date',
                    'Hypervisor': 'up_to_date',
                    'CLI': 'up_to_date',
                    'Model': 'up_to_date'
                }
                # Map component names
                comp_map = {'bootstrap': 'Bootstrap', 'hypervisor': 'Hypervisor',
                           'cli': 'CLI', 'model': 'Model'}
                expected[comp_map[component]] = 'update_available'
                
                if not check_update_status(process, expected):
                    return False
                
                # Do update
                process = do_update(process, component, command, args.executable, server_args)
                
                # Verify update complete
                if not check_update_status(process, {
                    'Bootstrap': 'up_to_date',
                    'Hypervisor': 'up_to_date',
                    'CLI': 'up_to_date',
                    'Model': 'up_to_date'
                }):
                    return False
                
                # Validate version
                validate_comp = [component] if component != 'model' else None
                if not validate_versions(process, version, validate_comp):
                    return False
        
        logging.info("All tests passed!")
        return True
        
    except Exception as e:
        logging.error(f"Test failed: {e}")
        return False
        
    finally:
        if process and process.isalive():
            process.close(force=True)
        
        if not args.no_cleanup:
            update_manifest(1)

if __name__ == "__main__":
    exit(0 if main() else 1)