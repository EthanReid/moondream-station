import pexpect
import os
import logging
import time
import requests
import re
from utils import DebugTracer
from config import Config, Timeouts
from server import Server
from manifest import Manifest
from commands import Commands
from parser import Parser
from test_capability import test_model_capabilities, parse_model_list_output
from utils import is_port_occupied, validate_files, setup_trace_logging

def setup_logging(verbose=False, debug_trace=False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    file_handler = logging.FileHandler('test_updates.log', mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    setup_trace_logging(debug_trace)
    
    if verbose:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.addHandler(console_handler)

class Validator:
    @staticmethod
    @DebugTracer.log_operation
    def check_updates(process, scenario, expected):
        log = lambda msg, level="debug": (
            DebugTracer.log(msg, "VALIDATOR"),
            getattr(logging, level)(msg)
        )
        
        log(f"Validating scenario: {scenario}")
        actual = Parser.parse_updates(Commands(process).check_updates())
        log(f"Expected: {expected}\nActual: {actual}")
        
        failed = []
        for k, v in expected.items():
            if actual.get(k) != v:
                log(f"{k}: got '{actual.get(k)}', expected '{v}'", "error")
                failed.append(k)
        
        success = not failed
        log(f"Validation result: {'PASS' if success else 'FAIL'}")
        return success
    
    @staticmethod
    @DebugTracer.log_operation
    def model_list(process):
        log = lambda msg, level="debug": (
            DebugTracer.log(msg, "VALIDATOR"),
            getattr(logging, level)(msg)
        )
        
        log("Starting model list validation")
        models = Parser.parse_models(Commands(process).model_list())
        
        # Load manifest
        if not os.path.exists(Config.MANIFEST_PATH):
            log("Manifest file not found - skipping validation", "warning")
            return True
        
        with open(Config.MANIFEST_PATH) as f:
            url_match = re.search(Config.MANIFEST_URL_PATTERN, f.read())
        
        if not url_match:
            log("MANIFEST_URL not found - skipping validation", "warning")
            return True
        
        # Fetch manifest data
        try:
            manifest_data = requests.get(url_match.group(1), timeout=10).json()
            manifest_models = manifest_data.get('models', {}).get(Config.MODEL_CATEGORY, {})
        except Exception as e:
            log(f"Failed to fetch manifest: {e}", "warning")
            return True
        
        log(f"Found {len(manifest_models)} models in manifest, {len(models)} in CLI")
        
        # Validate models
        fields = ['release_date', 'model_size', 'notes']
        failures = []
        
        for name, cli_data in models.items():
            if name not in manifest_models:
                failures.append(f"Model '{name}' found in CLI but not in manifest")
                continue
            
            for field in fields:
                if cli_data.get(field) != manifest_models[name].get(field):
                    failures.append(f"{name}.{field}: expected '{manifest_models[name].get(field)}', got '{cli_data.get(field)}'")
        
        for name in set(manifest_models) - set(models):
            failures.append(f"Model '{name}' in manifest but not in CLI")
        
        for f in failures:
            log(f, "warning" if "but not in" in f else "debug")
        
        success = not failures
        log(f"Model list validation: {'PASS' if success else 'FAIL'}")
        return success

    @staticmethod
    @DebugTracer.log_operation
    def test_inference_client_switches(process, manifest_version):
        """Test inference client switches based on manifest expectations."""
        log = lambda msg, lvl="debug": (
            DebugTracer.log(msg, "VALIDATOR"),
            getattr(logging, lvl)(msg)
        )
        
        log(f"Testing inference client switches for v{manifest_version:03d}")
        
        models = {
            k: v['inference_client_version']
            for k, v in Manifest.get_expected_versions(manifest_version).get('models', {}).items()
            if isinstance(v, dict) and 'inference_client_version' in v
        }
        
        if not models:
            log("No models with inference client versions found", "warning")
            return True
        
        log(f"Testing {len(models)} models: {models}")
        
        failed = [
            model for model, client in models.items()
            if not Validator.model_switch(process, model, expected_inference_client=client)
        ]
        
        if failed:
            log(f"Failed models: {failed}", "error")
        
        success = not failed
        log(f"Result: {'PASS' if success else 'FAIL'}")
        return success

    @staticmethod
    @DebugTracer.log_operation
    def validate_versions(process, manifest_version, components_to_check=None):
        """Validate component versions against expected versions from manifest."""
        log = lambda msg, lvl="debug": (
            DebugTracer.log(msg, "VALIDATOR"),
            getattr(logging, lvl)(msg)
        )
        
        log(f"Validating versions for manifest v{manifest_version:03d}")
        
        expected = Manifest.get_expected_versions(manifest_version)
        if not expected:
            log("No expected versions found - skipping validation", "warning")
            return True
        
        cmd = Commands(process)
        actual = {
            **Parser.parse_versions_from_check_updates(cmd.check_updates()),
            **Parser.parse_versions_from_config(cmd.get_config())
        }
        
        log(f"Expected: {expected}\nActual: {actual}")
        
        components = components_to_check or Config.VALIDAITON_COMPONENTS
        failures = []
        
        for comp in components:
            exp, act = expected.get(comp), actual.get(comp)
            if exp is None:
                continue
            if act is None:
                log(f"{comp}: version not found", "warning")
                failures.append(comp)
            elif act != exp:
                log(f"{comp}: got '{act}', expected '{exp}'", "error")
                failures.append(comp)
        
        success = not failures
        log(f"Result: {'PASS' if success else 'FAIL'}")
        return success

    @staticmethod
    def model_switch(process, model_name, expected_inference_client=None):
        log = lambda msg, lvl="debug": (
            DebugTracer.log(msg, "VALIDATOR"),
            getattr(logging, lvl)(msg)
        )
        
        log(f"Testing model switch to: {model_name}")
        cmd = Commands(process)
        
        # Get before state
        before = Parser.parse_config(cmd.get_config())
        log(f"Before - Model: {before.get('active_model')}, Client: {before.get('active_inference_client')}")
        
        # Execute switch
        if Config.MODEL_CHANGE['success'] not in cmd.model_use(model_name):
            log(f"Model switch to {model_name} failed - success pattern not found", "error")
            return False
        
        # Verify after state
        after = Parser.parse_config(cmd.get_config())
        new_model = after.get('active_model')
        new_client = after.get('active_inference_client')
        log(f"After - Model: {new_model}, Client: {new_client}")
        
        # Check model
        if new_model != model_name:
            log(f"Model verification failed - expected {model_name}, got {new_model}", "error")
            return False
        
        # Check inference client if specified
        if expected_inference_client and new_client != expected_inference_client:
            log(f"Client verification failed - expected {expected_inference_client}, got {new_client}", "error")
            return False
        
        log("Model switch validation: PASS")
        return True

class Updater:
    def __init__(self, server):
        self.server = server
        self.log = lambda msg, lvl="debug": (
            DebugTracer.log(msg, "UPDATER"),
            getattr(logging, lvl)(msg)
        )
    
    def _update(self, command, update_type, patterns, expect_exit=False):
        """Core update logic shared by all update methods."""
        self.log(f"Starting {update_type} update: {command}")
        
        try:
            cmd = Commands(self.server.process)
            
            if expect_exit:
                cmd.run(command, expect_pattern=patterns[0], 
                       timeout=Timeouts.UPDATE, expect_exit=True)
            else:
                self.server.process.sendline(command)
                try:
                    idx = self.server.process.expect(patterns, timeout=Timeouts.UPDATE)
                    if idx < len(patterns) - 1:  # Not the prompt pattern
                        self.log(f"{update_type} completed, exiting")
                        self._safe_exit()
                    else:
                        self.log(f"{update_type} returned to prompt unexpectedly", "warning")
                except pexpect.TIMEOUT:
                    self.log(f"Timeout during {update_type}, forcing exit", "warning")
                    self._safe_exit()
            
            self._restart()
            return True
            
        except Exception as e:
            self.log(f"{update_type} failed: {e}", "error")
            self._recover()
            return False
    
    def _safe_exit(self):
        """Safely exit CLI."""
        try:
            self.server.process.sendline('exit')
            self.server.process.expect(Config.EXIT_MESSAGE, timeout=Timeouts.QUICK)
        except (pexpect.TIMEOUT, pexpect.EOF):
            pass
    
    def _restart(self):
        """Force close and restart server."""
        if self.server.process.isalive():
            self.server.process.close(force=True)
        self.server.restart()
        self.log("Server restarted")
    
    def _recover(self):
        """Attempt recovery after failure."""
        try:
            if self.server.process.isalive():
                self.server.process.close(force=True)
            time.sleep(3)
            self.server.restart()
        except Exception as e:
            self.log(f"Recovery failed: {e}", "error")
    
    @DebugTracer.log_operation
    def bootstrap(self, command='admin update-bootstrap --confirm'):
        return self._update(command, "bootstrap", 
                          [Config.UPDATE_COMPLETION['bootstrap']], 
                          expect_exit=True)
    
    @DebugTracer.log_operation
    def hypervisor(self, command='admin update-hypervisor --confirm'):
        return self._update(command, "hypervisor", [
            Config.UPDATE_COMPLETION['hypervisor_complete'],
            Config.UPDATE_COMPLETION['hypervisor_off'],
            Config.PROMPT
        ])
    
    @DebugTracer.log_operation
    def full(self, command='admin update --confirm', update_type="general"):
        patterns = {
            "model": Config.UPDATE_COMPLETION['model'],
            "cli": Config.UPDATE_COMPLETION['cli'],
            "general": f"({Config.UPDATE_COMPLETION['model']}|{Config.UPDATE_COMPLETION['cli']})"
        }
        return self._update(command, update_type, 
                          [patterns.get(update_type, patterns["general"]), Config.PROMPT])

class TestSuite:
   def __init__(self, executable='./moondream_station', args=None, cleanup=True, test_capabilities=False):
       self.server = Server(executable, args)
       self.cleanup = cleanup
       self.test_capabilities = test_capabilities
       self.updater = None
   
   def validate_environment(self):
       """Check files and ports."""
       try:
           ports = {'hypervisor': is_port_occupied(2020), 'inference': is_port_occupied(20200)}
           DebugTracer.log(f"Pre-startup ports: {ports}", "STARTUP")
           logging.debug(f"Pre-startup ports: {ports}")
           validate_files(os.path.expanduser("~/.local/share/MoondreamStation"), "expected_checksum.json")
           return True
       except Exception as e:
           logging.error(f"Environment validation failed: {e}")
           return False
   
   def validate_post_startup(self):
       """Check ports after startup."""
       ports = {'hypervisor': is_port_occupied(2020), 'inference': is_port_occupied(20200)}
       if not all(ports.values()):
           logging.warning(f"Some ports not occupied: {ports}")
       return True
   
   def run_capability_tests(self):
       """Test all model capabilities."""
       if not self.test_capabilities:
           return True
       try:
           cmd = Commands(self.server.process)
           original = Parser.parse_config(cmd.get_config()).get('active_model')
           models = parse_model_list_output(cmd.model_list())
           
           for model in models:
               cmd.model_use(f'"{model}"')
               test_model_capabilities(self.server.process, model)
           
           if original in models:
               cmd.model_use(f'"{original}"')
           return True
       except Exception as e:
           logging.error(f"Capability test failed: {e}")
           return False
   
   def run(self):
       try:
           Manifest.verify_environment()
       except Exception as e:
           logging.error(f"Environment verification failed: {e}")
           return False
       
       if not self.validate_environment():
           return False
       
       Manifest.update_version(1)
       self.server.start()
       self.updater = Updater(self.server)
       self.validate_post_startup()
       
       try:
           return self._test_sequence()
       finally:
           if self.cleanup:
               Manifest.update_version(1)
           self.server.stop()
   
   def _test_sequence(self):
       """Execute test updates v001-v006."""
       cmd = Commands(self.server.process)
       cmd.update_manifest()
       
       # Use lambdas for lazy evaluation
       return all(test() for test in [
           # v001: Baseline
           lambda: self._check_state("v001", {'Bootstrap': 'up_to_date', 'Hypervisor': 'up_to_date', 'CLI': 'up_to_date'}),
           lambda: Validator.validate_versions(self.server.process, 1),
           lambda: self.run_capability_tests(),
           
           # v002-v006: Component updates (one per version)
           lambda: self._do_update(2, 'bootstrap'),
           lambda: self._do_update(3, 'hypervisor'),
           lambda: self._do_update(4, 'model'),
           lambda: self._do_update(5, 'cli'),
           lambda: self._do_update(6, 'inference_client')
       ])
   
   def _check_state(self, label, expected):
       """Check update status."""
       return Validator.check_updates(self.server.process, label,
           {k: Config.STATUS_INDICATORS[v] for k, v in expected.items()})
   
   def _do_update(self, version, component):
    """Update a component and validate."""
    Manifest.update_version(version)
    Commands(self.server.process).update_manifest()
    
    # Special handling for inference_client
    if component == 'inference_client':
        return all([
            Validator.test_inference_client_switches(self.server.process, version),
            Validator.validate_versions(self.server.process, version, [component]),
            self.run_capability_tests()
        ])
    
    # Check update available - only the current component should need update
    expected = {k: 'up_to_date' for k in Config.COMPONENT_NAMES}  # Use Config.COMPONENT_NAMES
    
    # Map component names to match Config.COMPONENT_NAMES
    component_map = {
        'bootstrap': 'Bootstrap',
        'hypervisor': 'Hypervisor', 
        'cli': 'CLI',
        'model': 'Model'
    }
    
    expected[component_map[component]] = 'update_available'
    
    if not self._check_state(f"v{version:03d}", expected):
        logging.error(f"Pre-update check failed for {component} at v{version}")
        return False
    
    # Perform update
    if component == 'bootstrap':
        success = self.updater.bootstrap()
    elif component == 'hypervisor':
        success = self.updater.hypervisor()
    elif component == 'model':
        success = self.updater.full('admin update --confirm', 'model')
    elif component == 'cli':
        success = self.updater.full('admin update --confirm', 'cli')
    else:
        logging.error(f"Unknown component: {component}")
        return False
    
    if not success:
        logging.error(f"{component} update failed")
        return False
    
    # Verify update completed - everything should be up to date now
    expected_after = {k: 'up_to_date' for k in Config.COMPONENT_NAMES}
    if not self._check_state(f"After {component} update", expected_after):
        return False
    
    # Additional checks for model update
    if component == 'model' and not Validator.model_list(self.server.process):
        return False
    
    # Validate versions and run capability tests
    validate_components = [component] if component != 'model' else None
    return all([
        Validator.validate_versions(self.server.process, version, validate_components),
        self.run_capability_tests()
    ])

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test Moondream Station complete update suite')
    parser.add_argument('--executable', default='./moondream_station', help='Path to executable')
    parser.add_argument('--verbose', action='store_true', help='Print logs to console')
    parser.add_argument('--debug-trace', action='store_true', help='Enable comprehensive debug tracing')
    parser.add_argument('--test-capabilities', action='store_true', help='Run capability tests after updates')
    parser.add_argument('--no-cleanup', action='store_true', help='Skip manifest cleanup')
    args, server_args = parser.parse_known_args()
    
    setup_logging(verbose=args.verbose, debug_trace=args.debug_trace)
    
    if args.debug_trace:
        DebugTracer.log("=== COMPREHENSIVE DEBUG TRACING ENABLED ===", "SYSTEM")
        DebugTracer.log(f"Command line args: {vars(args)}", "SYSTEM")
        DebugTracer.log(f"Server args: {server_args}", "SYSTEM")

    suite = TestSuite(args.executable, server_args, 
                     cleanup=not args.no_cleanup, 
                     test_capabilities=args.test_capabilities)
    success = suite.run()
    
    if args.debug_trace:
        DebugTracer.log(f"=== TEST SUITE COMPLETED: {'SUCCESS' if success else 'FAILURE'} ===", "SYSTEM")
    
    exit(0 if success else 1)

if __name__ == "__main__":
    main()