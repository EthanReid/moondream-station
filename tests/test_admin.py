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
TIMEOUTS = {'quick': 15, 'standard': 60, 'startup': 100, 'update': 30}
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
    # Convert all \r to \n to handle spinner/progress artifacts
    lines = [line.strip() for line in output.replace('\r', '\n').split('\n') 
             if line.strip() and not line.strip().startswith('Checking for') and not line.strip().startswith('admin')]
    
    for line in lines:
        if ':' in line and (' - Up to date' in line or ' - Update available' in line):
            comp = line.split(':')[0].strip()
            if ' - Up to date' in line:
                status[comp] = 'up_to_date'
            elif ' - Update available' in line:
                status[comp] = 'update_available'
    return status

def check_update_status(process, expected):
    """Verify update status matches expected."""
    # Send a dummy command first to clear any spinners
    run_command(process, 'admin health')
    
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
    
    # Parse from check-updates - more specific regex
    if match := re.search(r'Bootstrap:\s+(v[\d.]+)', updates):
        versions['bootstrap'] = match.group(1)
    if match := re.search(r'Hypervisor:\s+(v[\d.]+)', updates):
        versions['hypervisor'] = match.group(1)
    if match := re.search(r'CLI:\s+(v[\d.]+)', updates):
        versions['cli'] = match.group(1)
    
    # Parse from config (for inference_client and active versions)
    if match := re.search(r'active_bootstrap:\s+(v[\d.]+)', config):
        versions['active_bootstrap'] = match.group(1)
        logging.debug(f"Active bootstrap version: {match.group(1)}")
    if match := re.search(r'active_inference_client:\s+(v[\d.]+)', config):
        versions['inference_client'] = match.group(1)
    
    logging.debug(f"Extracted versions: {versions}")
    return versions

def validate_versions(process, manifest_version, components=None):
    """Check versions match manifest expectations."""
    manifest_file = MANIFEST_DIR / f'manifest_v{manifest_version:03d}.json'
    
    with open(manifest_file) as f:
        manifest = json.load(f)
    
    # Extract expected versions from manifest structure
    expected = {}
    if 'current_bootstrap' in manifest:
        expected['bootstrap'] = manifest['current_bootstrap']['version']
    if 'current_hypervisor' in manifest:
        expected['hypervisor'] = manifest['current_hypervisor']['version']
    if 'current_cli' in manifest:
        expected['cli'] = manifest['current_cli']['version']
    
    # For inference_client, we'd need to check the models
    # but for now, let's just use the first one found
    for category in manifest.get('models', {}).values():
        for model_data in category.values():
            if 'inference_client' in model_data:
                expected['inference_client'] = model_data['inference_client']
                break
    
    actual = get_versions(process)
    components = components or ['bootstrap', 'hypervisor', 'cli', 'inference_client']
    
    for comp in components:
        if comp in expected and expected[comp] != actual.get(comp):
            logging.error(f"{comp}: expected {expected[comp]}, got {actual.get(comp)}")
            return False
    
    return True

def do_update(process, update_type, command, executable, args):
    """Execute update command and restart."""
    logging.debug(f"Starting {update_type} update with command: {command}")
    
    if update_type == 'bootstrap':
        # Bootstrap exits immediately
        process.sendline(command)
        try:
            process.expect(UPDATE_PATTERNS['bootstrap'], timeout=TIMEOUTS['update'])
            logging.debug(f"Bootstrap update pattern found")
            time.sleep(5)  # Give it time to actually update
        except pexpect.EOF:
            logging.debug(f"Bootstrap update ended with EOF (expected)")
        except pexpect.TIMEOUT:
            logging.warning(f"Bootstrap update timeout - may have completed anyway")
    else:
        # Other updates return to prompt or exit
        process.sendline(command)
        try:
            idx = process.expect([UPDATE_PATTERNS.get(update_type, pexpect.TIMEOUT), PROMPT], 
                                timeout=TIMEOUTS['update'])
            if idx == 0:  # Found completion pattern
                logging.debug(f"{update_type} update pattern found")
                try:
                    process.sendline('exit')
                    process.expect(pexpect.EOF, timeout=TIMEOUTS['quick'])
                except:
                    pass
            else:
                logging.debug(f"{update_type} update returned to prompt")
        except pexpect.TIMEOUT:
            logging.warning(f"{update_type} update timeout")
    
    time.sleep(5)  # Give system time to settle
    return restart_server(process, executable, args)

def test_model_switch(process, model_name):
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
    else:
        logging.error("Could not find active_model in config")
        return False
    
    return True

def test_inference_clients(process, version):
    """Test model switches to trigger inference client updates."""
    manifest_file = MANIFEST_DIR / f'manifest_v{version:03d}.json'
    
    with open(manifest_file) as f:
        manifest = json.load(f)
    
    # Get all models from the manifest
    all_models = []
    for category in manifest.get('models', {}).values():
        all_models.extend(list(category.keys()))
    
    if len(all_models) < 2:
        logging.warning("Need at least 2 models to test inference client switching")
        return True
    
    # Switch from first model to second model
    logging.debug(f"Switching from {all_models[0]} to {all_models[1]}")
    if not test_model_switch(process, all_models[1]):
        return False
    
    # Switch back to first model
    logging.debug(f"Switching back to {all_models[0]}")
    if not test_model_switch(process, all_models[0]):
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
                
                # Log versions after update
                versions_after = get_versions(process)
                logging.debug(f"Versions after {component} update: {versions_after}")
                
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