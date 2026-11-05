"""xlsx-trans: dịch Excel JP -> EN bằng model local qua Ollama, sửa trực tiếp XML trong file .xlsx.

Các module:
  config    nạp config.toml / config.local.toml và prompt
  ollama    gọi Ollama (chat, danh sách model, dựng messages)
  cache     cache bản dịch (dùng chung được giữa nhiều file)
  xlsx_xml  đọc/ghi XML trong file xlsx: gom các đoạn cần dịch, ghi lại package
  markdown  xuất workbook đã dịch ra Markdown
  pipeline  dịch MỘT file xlsx
  batch     dịch CẢ FOLDER (giữ nguyên cấu trúc thư mục con)
  gui       giao diện tkinter
  cli       dòng lệnh
"""

__version__ = "0.2.0"
