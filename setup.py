import sys
from pathlib import Path
from cx_Freeze import setup, Executable

# 포함할 패키지 목록
packages = [
    "tkinter",
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.common",
    "selenium.webdriver.support",
    "webdriver_manager",
    "dotenv",
    "googletrans",
    "httpx",
    "httpcore",
]

# 포함할 추가 파일/폴더
include_files = [
    ("src", "src"),
    (".env", ".env"),
]

build_options = {
    "packages": packages,
    "include_files": include_files,
    "excludes": [],
    "build_exe": "dist",
}

setup(
    name="reservation-auto",
    version="1.0.0",
    description="PMS 예약 자동화",
    options={"build_exe": build_options},
    executables=[
        Executable(
            "gui.py",
            base="Win32GUI",  # 콘솔창 없이 실행
            target_name="예약자동화.exe",
        )
    ],
)
