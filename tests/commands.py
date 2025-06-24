import logging
import pexpect
import time
from config import Config, Timeouts
from utils import DebugTracer

import logging
import pexpect
import time
from config import Config, Timeouts
from utils import DebugTracer

class Commands:
    def __init__(self, process):
        self.process = process
        # Command definitions with their specific requirements
        self.command_specs = {
            'update_manifest': {'cmd': 'admin update-manifest', 'timeout': Timeouts.STANDARD},
            'check_updates': {'cmd': 'admin check-updates', 'timeout': Timeouts.STANDARD},
            'model_list': {'cmd': 'admin model-list', 'timeout': Timeouts.STANDARD},
            'status': {'cmd': 'admin status', 'timeout': Timeouts.STANDARD},
            'get_config': {'cmd': 'admin get-config', 'timeout': Timeouts.STANDARD},
        }
    
    @DebugTracer.log_command
    def execute(self, command_key, **kwargs):
        """Execute a predefined command by key."""
        if command_key not in self.command_specs:
            raise ValueError(f"Unknown command: {command_key}")
        
        spec = self.command_specs[command_key]
        cmd_string = spec['cmd']
        timeout = kwargs.get('timeout', spec['timeout'])
        
        return self._run_command(cmd_string, timeout=timeout, **kwargs)
    
    @DebugTracer.log_command
    def execute_custom(self, command_string, **kwargs):
        """Execute a custom command string."""
        timeout = kwargs.get('timeout', Timeouts.STANDARD)
        return self._run_command(command_string, timeout=timeout, **kwargs)
    
    @DebugTracer.log_command
    def model_use(self, model_name):
        """Special case for model switching with longer timeout."""
        cmd = f'admin model-use {model_name} --confirm'
        return self._run_command(cmd, timeout=Timeouts.UPDATE)
    
    @DebugTracer.log_command
    def run(self, command, **kwargs):
        """Run method that Updater expects - delegates to _run_command."""
        return self._run_command(command, **kwargs)
    
    def _run_command(self, command, timeout=Timeouts.STANDARD, expect_pattern=None, expect_exit=False):
        """Core command execution logic."""
        DebugTracer.log(f"Executing: {command}", "COMMAND")
        logging.debug(f"Running: {command}")
        
        self.process.sendline(command)
        
        if expect_exit:
            return self._handle_exit_command(expect_pattern, timeout)
        else:
            return self._handle_normal_command(expect_pattern, timeout)
    
    def _handle_exit_command(self, expect_pattern, timeout):
        """Handle commands that should exit the process."""
        try:
            if expect_pattern:
                self.process.expect(expect_pattern, timeout=timeout)
                logging.debug(f"Found expected pattern: {expect_pattern}")
            time.sleep(3)
            return self._get_output()
        except pexpect.EOF:
            logging.debug("Server exited (EOF)")
            return self._get_output()
        except pexpect.TIMEOUT:
            logging.warning(f"Timeout waiting for pattern: {expect_pattern}")
            return self._get_output()
    
    def _handle_normal_command(self, expect_pattern, timeout):
        """Handle normal commands that return to prompt."""
        try:
            if expect_pattern:
                self.process.expect(expect_pattern, timeout=timeout)
            self.process.expect(Config.PROMPT, timeout=timeout)
            return self._get_output()
        except pexpect.TIMEOUT:
            logging.warning(f"Command timeout after {timeout}s")
            return self._get_output()
    
    def _get_output(self):
        """Extract and clean command output."""
        if not hasattr(self.process, 'before'):
            DebugTracer.log("Process has no 'before' attribute - may be in unexpected state", "COMMAND")
            logging.warning("Process missing 'before' attribute - command may have failed")
            return None
        
        try:
            output = self.process.before.decode().strip()
            DebugTracer.log(f"Command output length: {len(output)}", "COMMAND")
            logging.debug(f"Command completed, output: {output[:100]}...")
            return output
        except Exception as e:
            DebugTracer.log(f"Failed to decode process output: {str(e)}", "COMMAND")
            logging.error(f"Failed to decode command output: {e}")
            return None
    
    # Convenience methods that use the new system
    def update_manifest(self):
        return self.execute('update_manifest')
    
    def check_updates(self):
        return self.execute('check_updates')
    
    def model_list(self):
        return self.execute('model_list')
    
    def status(self):
        return self.execute('status')
    
    def get_config(self):
        return self.execute('get_config')