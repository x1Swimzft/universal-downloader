import os
import sys
import multiprocessing
import uvicorn
from app.main import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    port = 8000
    if "--port" in sys.argv:
        try:
            idx = sys.argv.index("--port")
            port = int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            pass

    os.environ["BACKEND_PORT"] = str(port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
