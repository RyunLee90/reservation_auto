"""
테스트 전용: 아고다 계정만 자동 처리 (히카리/야놀자/여기어때 제외).

실행 (reservation_auto 폴더에서):
    python run_agoda_test.py

또는 .env 에 AGODA_TEST_ONLY=1 을 넣고 기존처럼 python src/main.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

os.environ["AGODA_TEST_ONLY"] = "1"

if __name__ == "__main__":
    import main as main_module

    main_module.run()
