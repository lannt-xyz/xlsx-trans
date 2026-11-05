#!/usr/bin/env python3
"""Điểm vào: python app.py [file-hoặc-folder] [tùy chọn]. Mã nguồn nằm trong package xlsx_trans/."""
import sys

from xlsx_trans.cli import main

if __name__ == "__main__":
    sys.exit(main())
