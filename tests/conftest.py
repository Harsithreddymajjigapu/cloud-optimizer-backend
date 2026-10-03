import os
import pathlib

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "HjjFcNC_OtSMMTiAgFUonXp-HxXgNecLF7B5xyM-_gE=")

# test.db survives between runs, so rows from a previous run leak into the next
# and the duplicate-email check fires. Start clean every time.
pathlib.Path("test.db").unlink(missing_ok=True)
