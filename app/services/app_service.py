import os
import subprocess
import logging
import psutil

try:
    from AppOpener import open as open_app
except ImportError:
    open_app = None

logger = logging.getLogger("J.A.R.V.I.S")

class AppService:
    """Service to open and close installed system applications natively."""
    
    def open_application(self, app_name: str) -> str:
        app_name = app_name.strip()
        if not app_name:
            return "Please provide an application name."
            
        logger.info(f"[APP_SERVICE] Attempting to open application: {app_name}")
        
        if app_name.lower() in ["settings", "windows settings"]:
            try:
                os.startfile("ms-settings:")
                return "I have opened Settings."
            except Exception as e:
                logger.error(f"[APP_SERVICE] Failed to open settings: {e}")
                return "Failed to open Settings."

        # Performance Optimization: Direct command triggers for common Windows apps
        if os.name == "nt":
            fast_apps = {
                "calculator": "calc",
                "notepad": "notepad",
                "paint": "mspaint",
                "cmd": "cmd",
                "powershell": "powershell",
                "explorer": "explorer",
                "taskmgr": "taskmgr",
            }
            if app_name.lower() in fast_apps:
                try:
                    subprocess.Popen(fast_apps[app_name.lower()], shell=True)
                    return f"I have opened {app_name}."
                except Exception:
                    pass

        if open_app:
            try:
                # Disable match_closest for common apps to speed up
                open_app(app_name, match_closest=(app_name.lower() not in ["calculator", "notepad", "chrome", "edge"]))
                return f"I have opened {app_name}."
            except Exception as e:
                logger.warning(f"[APP_SERVICE] AppOpener failed for {app_name}: {e}")
        
        if os.name == "nt":
            try:
                subprocess.Popen(f'start "" "{app_name}"', shell=True)
                return f"I have started {app_name}."
            except Exception as e:
                logger.error(f"[APP_SERVICE] Subprocess fallback failed: {e}")
                err_msg = f"Failed to find or open {app_name}."
                return err_msg
        
        try:
            cmd = ["open", "-a", app_name] if os.uname().sysname == "Darwin" else [app_name]
            subprocess.Popen(cmd)
            return f"I have started {app_name}."
        except Exception as e:
            logger.error(f"[APP_SERVICE] Linux/Mac fallback failed: {e}")
            return f"Failed to find or open the app {app_name}."

    def close_application(self, app_name: str) -> str:
        app_name = app_name.strip().lower()
        if not app_name:
            return "Please provide an application name to close."
            
        logger.info(f"[APP_SERVICE] Attempting to close application: {app_name}")
        closed_count = 0
        
        try:
            for proc in psutil.process_iter(['name']):
                name = proc.info.get('name', '').lower()
                if name and (app_name in name or app_name + ".exe" in name):
                    proc.kill()
                    closed_count += 1
                    
            if closed_count > 0:
                return f"I have closed {app_name}."
            else:
                return f"I couldn't find any running process named {app_name}."
        except Exception as e:
            logger.error(f"[APP_SERVICE] Failed to close {app_name}: {e}")
            return f"Failed to close the app {app_name}."
