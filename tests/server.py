import time
import logging
import pexpect
from config import Config, Timeouts
from utils import DebugTracer, TracedProcess
class Server:
    def __init__(self, executable='./moondream_station', args=None):
        self.executable = executable
        self.args = args or []
        self.process = None
    
    def _get_process_output(self):
        """Extract output from process safely."""
        return self.process.before.decode() if self.process else 'None'
    
    def _log_and_raise(self, error_type, operation, output=None):
        """Centralized error logging and raising."""
        if output is None:
            output = self._get_process_output()
        
        DebugTracer.log(f"Server {operation} failed ({error_type}): {output}", "SERVER")
        logging.error(f"Server {operation} failed ({error_type}). Output: {output}")
        raise
    
    def _force_cleanup(self, reason="error"):
        """Force close process with consistent logging."""
        if self.process and self.process.isalive():
            DebugTracer.log(f"Force closing process after {reason}", "SERVER")
            self.process.close(force=True)
            DebugTracer.log("Server force stopped", "SERVER")
            logging.debug(f"Server force stopped after {reason}")
    
    @DebugTracer.log_operation
    def start(self):
        cmd = [self.executable] + self.args
        DebugTracer.log(f"Starting server command: {' '.join(cmd)}", "SERVER")
        logging.debug(f"Starting server: {' '.join(cmd)}")
        time.sleep(2)
        
        try:
            raw_process = pexpect.spawn(' '.join(cmd))
            self.process = TracedProcess(raw_process)
            DebugTracer.log("Waiting for startup prompt", "SERVER")
            self.process.expect(Config.PROMPT, timeout=Timeouts.STARTUP)
            DebugTracer.log("Server started successfully", "SERVER")
            logging.debug("Server started successfully")
            return self.process
            
        except pexpect.EOF:
            self._log_and_raise("EOF", "startup")
        except pexpect.TIMEOUT:
            self._log_and_raise("TIMEOUT", "startup")

    @DebugTracer.log_operation
    def stop(self):
        if not self.process:
            DebugTracer.log("No process to stop", "SERVER")
            return
        
        try:
            DebugTracer.log("Sending exit command", "SERVER")
            self.process.sendline('exit')
            self.process.expect(Config.EXIT_MESSAGE, timeout=Timeouts.QUICK)
            
            if self.process.isalive():
                self._force_cleanup("normal_exit")
            else:
                DebugTracer.log("Server stopped successfully", "SERVER")
                logging.debug("Server stopped successfully")
                
        except Exception:
            self._force_cleanup("exception")
    
    @DebugTracer.log_operation
    def restart(self):
        DebugTracer.log("Restarting server", "SERVER")
        logging.debug("Restarting server")
        self.stop()
        time.sleep(2)
        return self.start()