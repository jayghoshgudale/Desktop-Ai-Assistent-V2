import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.services.app_service import AppService
    from app.services.system_service import SystemService

    print("Testing AppService...")
    app_service = AppService()
    res = app_service.open_application("calculator")
    print("AppService output:", res)

    print("Testing SystemService...")
    sys_service = SystemService()
    print("System service methods exist: ", hasattr(sys_service, "sleep"))
    
    print("ALL TESTS PASSED / INITIALIZED")
except Exception as e:
    print(f"Test failed: {e}")
