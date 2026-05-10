import logging
from typing import Optional

logger = logging.getLogger("J.A.R.V.I.S")

class SandboxService:
    def __init__(self):
        self.client = None
        try:
            import docker
            self.client = docker.from_env()
            logger.info("[SANDBOX] Docker client initialized successfully. Safe-execution enabled.")
        except ImportError:
            logger.warning("[SANDBOX] 'docker' python library not found. Code sandbox disabled.")
        except Exception as e:
            logger.warning("[SANDBOX] Docker daemon not found or unavailable. Code sandbox disabled: %s", e)

    def run_python_code(self, code: str, timeout: int = 15) -> dict:
        if not self.client:
            return {"error": "Docker daemon is not running or Sandbox is disabled.", "stdout": "", "stderr": "", "exit_code": -1}
            
        try:
            import docker
            logger.info("[SANDBOX] Executing Python code in isolated container...")
            
            image_name = "python:3.10-alpine"
            command = ["python", "-c", code]
            
            # Using low-level containers.run to get more control if needed, but for now:
            result = self.client.containers.run(
                image_name,
                command=command,
                remove=True,
                mem_limit="128m",
                network_disabled=False,
                stdout=True,
                stderr=True,
                pids_limit=50
            )
            
            output = result.decode('utf-8', errors='replace').strip()
            return {
                "stdout": output,
                "stderr": "",
                "exit_code": 0
            }
            
        except docker.errors.ContainerError as e:
            stderr_out = e.stderr.decode('utf-8', errors='replace').strip() if e.stderr else str(e)
            stdout_out = e.stdout.decode('utf-8', errors='replace').strip() if e.stdout else ""
            return {
                "stdout": stdout_out,
                "stderr": stderr_out,
                "exit_code": e.exit_status
            }
        except docker.errors.ImageNotFound:
            return {"error": "python:3.10-alpine image not found.", "stdout": "", "stderr": "", "exit_code": -1}
        except Exception as e:
            logger.error("[SANDBOX] Docker execution failed: %s", e)
            return {"error": str(e), "stdout": "", "stderr": str(e), "exit_code": -1}
