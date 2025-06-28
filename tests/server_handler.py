import pexpect
import time
import re

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
        'hypervisor': r'Hypervisor.*update.*completed',
        'model': r'All component updates have been processed',
        'cli': r'CLI update complete\. Please restart the CLI'
        }
        self.timeout = 300
    
    def start(self, use_update_manifest: bool = False):
        """Start server with specified manifest."""
    
        if use_update_manifest:
            self.current_manifest_url = self.update_manifest_url
        
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
        if match := re.search(r'active_inference_client:\s+(v[\d.]+)', config_output):
            versions['bootstrap'] = match.group(1)
        if match := re.search(r'active_inference_client:\s+(v[\d.]+)', config_output):
            versions['hypervisor'] = match.group(1)
        if match := re.search(r'active_inference_client:\s+(v[\d.]+)', config_output):
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

    def update_component(self, component: str) -> bool:
        """Update component with component-specific behavior."""
        cmd = f"admin update-{component} --confirm"
        pattern = self.update_patterns[component]
        
        self.process.sendline(cmd)
        
        try:
            # Others: pattern → hang
            self.process.expect(pattern, timeout=self.timeout)
            print(f"{component} update pattern found")
            # Kill the hung process
            if self.process.isalive():
                self.stop()
        except pexpect.TIMEOUT or TimeoutError:
            raise RuntimeError(f"Update timeout - no pattern '{pattern}' found in {self.timeout}s")


        return True
           