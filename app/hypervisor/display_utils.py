import sys
import time
import itertools
import threading

MOONDREAM_STATION_BANNER = r"""
.-----------------------------------------------------------.
|  __  __                       _                           |
| |  \/  | ___   ___  _ __   __| |_ __ ___  __ _ _ __ ___   |
| | |\/| |/ _ \ / _ \| '_ \ / _` | '__/ _ \/ _` | '_ ` _ \  |
| | |  | | (_) | (_) | | | | (_| | | |  __/ (_| | | | | | | |
| |_|  |_|\___/ \___/|_| |_|\__,_|_|  \___|\__,_|_| |_| |_| |
| / ___|| |_ __ _| |_(_) ___  _ __                          |
| \___ \| __/ _` | __| |/ _ \| '_ \                         |
|  ___) | || (_| | |_| | (_) | | | |                        |
| |____/ \__\__,_|\__|_|\___/|_| |_|                        |
'-----------------------------------------------------------'           
"""

RUNNING = r"""
 ____                    _                         
|  _ \ _   _ _ __  _ __ (_)_ __   __ _             
| |_) | | | | '_ \| '_ \| | '_ \ / _` |            
|  _ <| |_| | | | | | | | | | | | (_| |  _   _   _ 
|_| \_\\__,_|_| |_|_| |_|_|_| |_|\__, | (_) (_) (_)
                                 |___/                                 
"""


class Spinner:
    """Shows an animated spinner with a message while a long-running task is executing"""

    def __init__(self, message="Loading"):
        """Initialize the spinner with a message"""
        self.message = message
        self.spinner = itertools.cycle(["|", "/", "-", "\\"])
        self.running = False
        self.spinner_thread = None

    def start(self):
        """Start the spinner animation"""
        self.running = True
        self.spinner_thread = threading.Thread(target=self._spin)
        self.spinner_thread.daemon = True
        self.spinner_thread.start()

    def stop(self):
        """Stop the spinner animation"""
        self.running = False
        if self.spinner_thread:
            self.spinner_thread.join()
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def _spin(self):
        """Animate the spinner"""
        while self.running:
            sys.stdout.write(f"\r{self.message} {next(self.spinner)} ")
            sys.stdout.flush()
            time.sleep(0.1)

    def __enter__(self):
        """Start spinner when used in a context manager"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop spinner when exiting context manager"""
        self.stop()


def print_banner():
    """Print the Moondream Station ASCII art banner"""
    print(MOONDREAM_STATION_BANNER)
