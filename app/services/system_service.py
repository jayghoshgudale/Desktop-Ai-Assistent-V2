import os
import subprocess
import logging

logger = logging.getLogger("J.A.R.V.I.S")

class SystemService:
    """Service to execute system-level commands like shutdown, restart, sleep."""
    
    def shutdown(self) -> str:
        logger.info("[SYSTEM_SERVICE] Shutting down computer...")
        if os.name == 'nt':
            subprocess.Popen(["shutdown", "/s", "/t", "0"])
        else:
            subprocess.Popen(["sudo", "shutdown", "-h", "now"])
        return "Shutting down the computer."
        
    def restart(self) -> str:
        logger.info("[SYSTEM_SERVICE] Restarting computer...")
        if os.name == 'nt':
            subprocess.Popen(["shutdown", "/r", "/t", "0"])
        else:
            subprocess.Popen(["sudo", "shutdown", "-r", "now"])
        return "Restarting the computer."
        
    def sleep(self) -> str:
        logger.info("[SYSTEM_SERVICE] Putting computer to sleep...")
        if os.name == 'nt':
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif os.uname().sysname == 'Darwin':
            subprocess.Popen(["pmset", "sleepnow"])
        else:
            subprocess.Popen(["systemctl", "suspend"])
        return "Putting the computer to sleep."
