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
        self.pre_startup_ports = {}
    
    @DebugTracer.log_operation
    def validate_startup_environment(self, backend_path="~/.local/share/MoondreamStation", checksum_path="expected_checksum.json"):
        """Validate startup environment - file checksums and port states (v001 only)."""
        DebugTracer.log("Starting startup environment validation", "STARTUP")
        logging.debug("=== Startup Environment Validation ===")
        
        try:
            # Check port occupancy before server start
            pre_hypervisor = is_port_occupied(2020)
            pre_inference = is_port_occupied(20200)
            self.pre_startup_ports = {
                'hypervisor': pre_hypervisor,
                'inference': pre_inference
            }
            
            DebugTracer.log(f"Pre-startup port check - Hypervisor: {'occupied' if pre_hypervisor else 'free'}, Inference: {'occupied' if pre_inference else 'free'}", "STARTUP")
            logging.debug(f"Hypervisor Port (2020) was {'occupied' if pre_hypervisor else 'not occupied'} before server startup")
            logging.debug(f"Inference Server Port (20200) was {'occupied' if pre_inference else 'not occupied'} before server startup")
            
            # Validate backend files
            DebugTracer.log(f"Validating backend files in {backend_path}", "STARTUP")
            logging.debug(f"Validating backend files in {backend_path}")
            validate_files(os.path.expanduser(backend_path), checksum_path)
            DebugTracer.log("Backend file validation completed", "STARTUP")
            logging.debug("Backend file validation completed successfully")
            
            return True
            
        except Exception as e:
            DebugTracer.log(f"Startup environment validation failed: {str(e)}", "STARTUP")
            logging.error(f"Startup environment validation failed: {e}")
            return False
    
    @DebugTracer.log_operation
    def validate_post_startup_state(self):
        """Validate server state after startup (v001 only)."""
        
        DebugTracer.log("Validating post-startup server state", "STARTUP")
        logging.debug("=== Post-Startup State Validation ===")
        
        try:
            # Check current port occupancy
            current_hypervisor = is_port_occupied(2020)
            current_inference = is_port_occupied(20200)
            
            DebugTracer.log(f"Post-startup port check - Hypervisor: {'occupied' if current_hypervisor else 'free'}, Inference: {'occupied' if current_inference else 'free'}", "STARTUP")
            logging.debug(f"Hypervisor Port (2020) is currently {'occupied' if current_hypervisor else 'not occupied'}")
            logging.debug(f"Inference Server Port (20200) is currently {'occupied' if current_inference else 'not occupied'}")
            
            # Server should be running, so ports should be occupied
            if not current_hypervisor:
                DebugTracer.log("Warning: Hypervisor port not occupied after startup", "STARTUP")
                logging.warning("Hypervisor port (2020) not occupied - server may not be running properly")
            
            if not current_inference:
                DebugTracer.log("Warning: Inference port not occupied after startup", "STARTUP") 
                logging.warning("Inference port (20200) not occupied - inference server may not be running")
            
            return True
            
        except Exception as e:
            DebugTracer.log(f"Post-startup state validation failed: {str(e)}", "STARTUP")
            logging.error(f"Post-startup state validation failed: {e}")
            return False
    
    @DebugTracer.log_operation
    def run_capability_tests(self):
        
        DebugTracer.log("Starting capability testing", "CAPABILITY")
        logging.debug("=== Running Capability Tests ===")
        
        try:
            cmd = Commands(self.server.process)
            
            # Save current model state before testing
            config_output = cmd.get_config()
            current_config = Parser.parse_config(config_output)
            original_model = current_config.get('active_model', None)
            
            DebugTracer.log(f"Original active model: {original_model}", "CAPABILITY")
            logging.debug(f"Saving original active model: {original_model}")
            
            # Get model list and test each one
            output = cmd.model_list()
            models = parse_model_list_output(output)
            
            DebugTracer.log(f"Testing capabilities for {len(models)} models", "CAPABILITY")
            logging.debug(f"Found {len(models)} models for capability testing: {models}")
            
            for model_name in models:
                DebugTracer.log(f"Testing capabilities for model: {model_name}", "CAPABILITY")
                logging.debug(f"--- Testing capabilities for model: {model_name} ---")
                
                cmd.model_use(f'"{model_name}"')
                test_model_capabilities(self.server.process, model_name)
            
            # Restore original model if we had one
            if original_model and original_model in models:
                DebugTracer.log(f"Restoring original model: {original_model}", "CAPABILITY")
                logging.debug(f"Restoring original active model: {original_model}")
                cmd.model_use(f'"{original_model}"')
            elif original_model:
                DebugTracer.log(f"Warning: Original model '{original_model}' not found in current model list", "CAPABILITY")
                logging.warning(f"Could not restore original model '{original_model}' - not in current model list")
            
            DebugTracer.log("Capability testing completed", "CAPABILITY")
            logging.debug("Capability testing completed successfully")
            return True
            
        except Exception as e:
            DebugTracer.log(f"Capability testing failed: {str(e)}", "CAPABILITY")
            logging.error(f"Capability testing failed: {e}")
            return False
    
    def run(self):
        logging.debug("Starting incremental updates test suite")
        try:
            Manifest.verify_environment()
        except Exception as e:
            logging.error(f"Test environment verification failed: {e}")
            return False
        
        # Validate startup environment before server start
        if not self.validate_startup_environment():
            logging.error("Startup environment validation failed")
            return False
        
        Manifest.update_version(1)
        self.server.start()
        self.updater = Updater(self.server)
        
        # Validate post-startup state
        if not self.validate_post_startup_state():
            logging.warning("Post-startup state validation failed - continuing with tests")
        
        try:
            success = self._execute_test_sequence()
            logging.debug(f"Test suite completed: {'PASS' if success else 'FAIL'}")
            return success
        finally:
            if self.cleanup:
                try:
                    Manifest.update_version(1)
                    logging.debug("Manifest restored to v001")
                except Exception as e:
                    logging.warning(f"Failed to restore manifest: {e}")
            self.server.stop()
    
    def _execute_test_sequence(self):
        all_passed = True
        
        cmd = Commands(self.server.process)
        cmd.update_manifest()
        
        success = Validator.check_updates(self.server.process, "All Up to Date (v001)", {
            'Bootstrap': Config.STATUS_INDICATORS['up_to_date'],
            'Hypervisor': Config.STATUS_INDICATORS['up_to_date'], 
            'CLI': Config.STATUS_INDICATORS['up_to_date']
        })
        all_passed = all_passed and success
        
        # Validate versions for v001 baseline
        success = Validator.validate_versions(self.server.process, 1)
        if not success:
            logging.error("Version validation failed for v001 baseline")
            all_passed = False
        
        # Capability test after v001 baseline
        if self.test_capabilities:
            logging.debug("Running capability tests after v001 baseline")
            success = self.run_capability_tests()
            if not success:
                logging.error("Capability tests failed after v001 baseline")
                all_passed = False
        
        Manifest.update_version(2)
        cmd.update_manifest()
        success = Validator.check_updates(self.server.process, "Bootstrap Update Available (v002)", {
            'Bootstrap': Config.STATUS_INDICATORS['update_available'],
            'Hypervisor': Config.STATUS_INDICATORS['up_to_date'],
            'CLI': Config.STATUS_INDICATORS['up_to_date']
        })
        all_passed = all_passed and success
        
        success = self.updater.bootstrap()
        if not success:
            logging.error("Bootstrap update failed")
            all_passed = False
        
        # Validate bootstrap version after update
        success = Validator.validate_versions(self.server.process, 2, ['bootstrap'])
        if not success:
            logging.error("Bootstrap version validation failed after update")
            all_passed = False
        
        # Capability test after v002 bootstrap update
        if self.test_capabilities:
            logging.debug("Running capability tests after bootstrap update")
            success = self.run_capability_tests()
            if not success:
                logging.error("Capability tests failed after bootstrap update")
                all_passed = False
        
        Manifest.update_version(3)
        cmd = Commands(self.server.process)
        cmd.update_manifest()
        success = Validator.check_updates(self.server.process, "Hypervisor + Model Updates Available (v003)", {
            'Bootstrap': Config.STATUS_INDICATORS['up_to_date'],
            'Hypervisor': Config.STATUS_INDICATORS['update_available'],
            'CLI': Config.STATUS_INDICATORS['up_to_date'],
            'Model': Config.STATUS_INDICATORS['update_available']
        })
        all_passed = all_passed and success
        
        success = self.updater.hypervisor()
        if not success:
            logging.error("Hypervisor update failed")
            all_passed = False
        
        # Validate hypervisor version after update
        success = Validator.validate_versions(self.server.process, 3, ['hypervisor'])
        if not success:
            logging.error("Hypervisor version validation failed after update")
            all_passed = False
        
        # Capability test after hypervisor update
        if self.test_capabilities:
            logging.debug("Running capability tests after hypervisor update")
            success = self.run_capability_tests()
            if not success:
                logging.error("Capability tests failed after hypervisor update")
                all_passed = False
        
        cmd = Commands(self.server.process)
        success = Validator.check_updates(self.server.process, "After Hypervisor Update in v003", {
            'Bootstrap': Config.STATUS_INDICATORS['up_to_date'],
            'Hypervisor': Config.STATUS_INDICATORS['up_to_date'],
            'CLI': Config.STATUS_INDICATORS['up_to_date'],
            'Model': Config.STATUS_INDICATORS['update_available']
        })
        all_passed = all_passed and success
        
        success = self.updater.full('admin update --confirm', "model")
        if not success:
            logging.error("Model update failed")
            all_passed = False
        
        cmd = Commands(self.server.process)
        success = Validator.check_updates(self.server.process, "After Model Update in v003", {
            'Bootstrap': Config.STATUS_INDICATORS['up_to_date'],
            'Hypervisor': Config.STATUS_INDICATORS['up_to_date'],
            'CLI': Config.STATUS_INDICATORS['up_to_date'],
            'Model': Config.STATUS_INDICATORS['up_to_date']
        })
        all_passed = all_passed and success
        
        success = Validator.model_list(self.server.process)
        all_passed = all_passed and success
        
        # Validate all versions after model update (v003 should have new models)
        success = Validator.validate_versions(self.server.process, 3)
        if not success:
            logging.error("Version validation failed after model update")
            all_passed = False
        
        # Capability test after model update
        if self.test_capabilities:
            logging.debug("Running capability tests after model update")
            success = self.run_capability_tests()
            if not success:
                logging.error("Capability tests failed after model update")
                all_passed = False
        
        Manifest.update_version(4)
        cmd = Commands(self.server.process)
        cmd.update_manifest()
        success = Validator.check_updates(self.server.process, "CLI Update Available (v004)", {
            'Bootstrap': Config.STATUS_INDICATORS['up_to_date'],
            'Hypervisor': Config.STATUS_INDICATORS['up_to_date'],
            'CLI': Config.STATUS_INDICATORS['update_available'],
            'Model': Config.STATUS_INDICATORS['up_to_date']
        })
        all_passed = all_passed and success
        
        success = self.updater.full('admin update --confirm', "cli")
        if not success:
            logging.error("CLI update failed")
            all_passed = False
        
        cmd = Commands(self.server.process)
        success = Validator.check_updates(self.server.process, "After CLI Update (v004)", {
            'Bootstrap': Config.STATUS_INDICATORS['up_to_date'],
            'Hypervisor': Config.STATUS_INDICATORS['up_to_date'],
            'CLI': Config.STATUS_INDICATORS['up_to_date'],
            'Model': Config.STATUS_INDICATORS['up_to_date']
        })
        all_passed = all_passed and success
        
        # Validate CLI version after update
        success = Validator.validate_versions(self.server.process, 4, ['cli'])
        if not success:
            logging.error("CLI version validation failed after update")
            all_passed = False
        
        # Capability test after CLI update
        if self.test_capabilities:
            logging.debug("Running capability tests after CLI update")
            success = self.run_capability_tests()
            if not success:
                logging.error("Capability tests failed after CLI update")
                all_passed = False
        
        cmd = Commands(self.server.process)
        success = Validator.check_updates(self.server.process, "After CLI Update (v004)", {
            'Bootstrap': Config.STATUS_INDICATORS['up_to_date'],
            'Hypervisor': Config.STATUS_INDICATORS['up_to_date'],
            'CLI': Config.STATUS_INDICATORS['up_to_date'],
            'Model': Config.STATUS_INDICATORS['up_to_date']
        })
        all_passed = all_passed and success
        
        # Step 5: Inference Client Update Test (v005)
        Manifest.update_version(5)
        cmd = Commands(self.server.process)
        cmd.update_manifest()
        
        logging.debug("=== Testing Inference Client Updates (v005) ===")
        
        # Test inference client switches based on manifest configuration
        success = Validator.test_inference_client_switches(self.server.process, 5)
        if not success:
            logging.error("Inference client switches failed")
            all_passed = False
        
        logging.debug("Inference client update tests completed")
        
        # Validate inference client versions after all switches
        success = Validator.validate_versions(self.server.process, 5, ['inference_client'])
        if not success:
            logging.error("Inference client version validation failed")
            all_passed = False
        
        # Capability test after inference client updates
        if self.test_capabilities:
            logging.debug("Running capability tests after inference client updates")
            success = self.run_capability_tests()
            if not success:
                logging.error("Capability tests failed after inference client updates")
                all_passed = False
        
        return all_passed

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