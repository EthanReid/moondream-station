import pexpect
import time
import re
import json

class MoondreamServer:
    """Manages server lifecycle and commands."""
    def __init__(self, executable_path, base_manifest_url, update_manifest_url):
        self.executable_path = executable_path
        self.base_manifest_url = base_manifest_url
        self.update_manifest_url = update_manifest_url
        self.current_manifest_url = base_manifest_url
        self.process = None

        self.prompt = 'moondream>'
        self.update_patterns = {
        'bootstrap': r'(Restart.*for update|Terminated)',
        'hypervisor': r'Server status: Hypervisor: off, Inference: off',
        'model': r'All component updates have been processed',
        'cli': r'CLI update complete\. Please restart the CLI'
        }
        self.timeout = 100
    
    def start(self, use_update_manifest: bool = False):
        """Start server with specified manifest."""
    
        if use_update_manifest:
            self.current_manifest_url = self.update_manifest_url
        print(self.current_manifest_url)
        
        cmd = [self.executable_path, '--manifest-url', self.current_manifest_url]
        print(f"Starting server with: {' '.join(cmd)}")
        
        try:
            self.process = pexpect.spawn(' '.join(cmd))
            self.process.expect(self.prompt, timeout=self.timeout)
            print("Server started successfully")
        except pexpect.TIMEOUT:
            raise RuntimeError(f"Server failed to start within {self.timeout} seconds")
        except pexpect.EOF:
            raise RuntimeError("Server process terminated unexpectedly")
        except Exception as e:
            raise RuntimeError(f"Failed to start server: {e}")

    def stop(self):
        """Stop server cleanly."""
        if self.process and self.process.isalive():
            try:
                self.run_command("exit", timeout=5)
            except:
                pass # Force close if exit command fails to exit fast enough
            finally:
                self.process.close(force=True)
            print("Server stopped.")
        else:
            print("Server was not running to begin with.")

    def restart(self, use_update_manifest: bool = True):
        """Restart server, optionally with update manifest."""
        self.stop()
        time.sleep(2)
        self.start(use_update_manifest)

    def run_command(self, cmd: str, expect:str , timeout: int = None) -> str:
        """Execute command with error handling."""
        if not self.process or not self.process.isalive():
            raise RuntimeError("Server not running")
        
        try:
            self.process.sendline(cmd)
            self.process.expect(expect, timeout=timeout)
            return self.process.before.decode().strip()
        except pexpect.TIMEOUT:
            raise TimeoutError(f"Command '{cmd}' timed out after {timeout}s")
        except Exception as e:
            raise RuntimeError(f"Command '{cmd}' failed: {e}")
    
    def get_versions(self) -> dict[str, str]:
        """Get current component versions from both check-updates and config."""
        versions = {}
        
        # Get inference client version from config
        config_output = self.run_command("admin get-config", expect=self.prompt)
        if match := re.search(r'active_bootstrap:\s+(v[\d.]+)', config_output):
            versions['bootstrap'] = match.group(1)
        if match := re.search(r'active_hypervisor:\s+(v[\d.]+)', config_output):
            versions['hypervisor'] = match.group(1)
        if match := re.search(r'active_cli:\s+(v[\d.]+)', config_output):
            versions['cli'] = match.group(1)
        if match := re.search(r'active_inference_client:\s+(v[\d.]+)', config_output):
            versions['inference'] = match.group(1)
        
        return versions
    
    def pull_manifest(self, expected_note: list[str]):
        """Update manifest from server."""
        try:
            output = self.run_command("admin update-manifest", expect=self.prompt)
            for note in expected_note:
                if note in output:
                    print(f"Manifest verified: Found note '{note}'")
                    break
                else:
                    raise ValueError(f"Manifest update verification failed - expected notes not found")
        except Exception as e:
            raise RuntimeError(f"Failed to pull manifest: {e}")
        
    def check_updates(self, component: str = None) -> bool:
        """
        Check if a component has updates available.
        
        Args:
            component: Component name to check
        
        Returns:
            True if update available, False otherwise
        """
        output = self.run_command("admin check-updates", expect=self.prompt, timeout=self.timeout)
        
        # Clean up spinner/progress artifacts
        clean_output = output.replace('\r', '\n')
        lines = [line.strip() for line in clean_output.split('\n') 
                if line.strip() and 
                not line.strip().startswith('Checking for') and
                not line.strip().startswith('admin')]
        
        status = {}
        for line in lines:
            if ':' in line and (' - Up to date' in line or ' - Update available' in line):
                comp = line.split(':')[0].strip().lower()
                if ' - Up to date' in line:
                    status[comp] = 'up_to_date'
                elif ' - Update available' in line:
                    status[comp] = 'update_available'
        
        # Return boolean for the component
        if component:
            return status.get(component.lower()) == 'update_available'
        
        # If no component specified, could return False or raise error
        return False

    def update_component(self, component: str) -> bool:
        """Update component with component-specific behavior.
        Only works if the components are one of Bootstrap, CLI, Hypervisor or Model
        """
        pattern = self.update_patterns[component]
        
        if component == 'cli' or 'model':
            cmd = "admin update --confirm"
        else:
            cmd = f"admin update-{component} --confirm"
        
        print(f"Updating {component} with: {cmd}")
        self.process.sendline(cmd)
        
        try:
            # All components: wait for their specific pattern
            self.process.expect(pattern, timeout=self.timeout)
            print(f"{component} update pattern found: {pattern}")
            
            # After pattern, process is either hung or in restart sequence
            # Just kill it regardless
            if component != 'bootstrap':
                self.stop()
                
        except pexpect.TIMEOUT:
            raise RuntimeError(f"{component} update failed - pattern not found")
        
        return True
    
    def get_model_list(self) -> list[str]:
        """Get list of available models."""
        output = self.run_command("admin model-list", expect=self.prompt)
        
        # Extract model names - they appear after "Model: "
        models = []
        for line in output.split('\n'):
            if line.strip().startswith('Model: '):
                model_name = line.split('Model: ', 1)[1].strip()
                models.append(model_name)
        
        return models
    
    def get_current_model(self) -> str:
        """Get currently active model from config."""
        config_output = self.run_command("admin get-config", expect=self.prompt)
        
        # Look for active_model in config
        if match := re.search(r'active_model:\s+(.+)', config_output):
            return match.group(1).strip()
        
        return None
    
    def use_model(self, model_name: str, timeout:int = 300) -> bool:
        """Switch to a specific model."""
        try:
            output = self.run_command(
                f'admin model-use "{model_name}" --confirm',
                expect=self.prompt,
                timeout=timeout  # model switching can take time
            )
            
            # Check for success indicators
            if 'Model initialization completed successfully' in output:
                print(f"Successfully switched to model: {model_name}")
                return True
            else:
                print(f"Model switch may have failed. Output: {output[:200]}...")
                return False
                
        except Exception as e:
            print(f"Failed to switch to model {model_name}: {e}")
            return False

    def test_model_capabilities(self, model_name: str, image_url: str, expected_json: str = "expected_responses.json") -> dict[str, bool]:
        """Test all capabilities for a model. Returns pass/fail for each."""
        try:
            with open(expected_json, 'r') as f:
                expected = json.load(f)
        except:
            return {"error": False}
            
        if model_name not in expected:
            return {"error": False}
        
        model_exp = expected[model_name]
        tests = [
            ('caption', f'caption {image_url}', model_exp.get('caption_normal', model_exp.get('caption', {}))),
            ('query', f'query "What is in this image?" {image_url}', model_exp.get('query', {})),
            ('detect', f'detect face {image_url}', model_exp.get('detect', '')),
            ('point', f'point face {image_url}', model_exp.get('point', ''))
        ]
        
        results = {}
        for test_name, cmd, exp in tests:
            try:
                output = self.run_command(cmd, expect=self.prompt, timeout=60)
                
                # Clean output
                lines = output.split('\n')
                cleaned = ' '.join(line.strip() for line in lines 
                                if line.strip() and not line.startswith(cmd.split()[0]))
                
                # Check expected
                if isinstance(exp, dict) and 'keywords' in exp:
                    results[test_name] = any(kw.lower() in cleaned.lower() for kw in exp['keywords'])
                else:
                    results[test_name] = str(exp) in cleaned
                    
            except Exception:
                results[test_name] = False
        
        return results