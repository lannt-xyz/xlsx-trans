# xlsx-trans

Dịch Excel từ **tiếng Nhật sang tiếng Anh** bằng **model chạy local qua [Ollama](https://ollama.com)**. Dữ liệu không rời khỏi máy bạn.

Khác với cách đọc bằng `openpyxl` rồi ghi lại (hay làm mất shape, hình, biểu đồ), app này **sửa trực tiếp XML bên trong file `.xlsx`**, nên mọi thứ không phải chữ tiếng Nhật được giữ nguyên: định dạng, công thức, hình, biểu đồ, macro.

## Tính năng

- Dịch từng đoạn chữ có tiếng Nhật, bỏ qua số, mã sản phẩm, URL và chữ đã là tiếng Anh.
- Dịch được:
  - chữ trong cell (shared strings và inline strings)
  - text trong shape / text box / WordArt
  - tiêu đề, nhãn trong biểu đồ và SmartArt
  - comment (note) kiểu cũ
  - tên cột của Table (để khớp với header đã dịch)
- Hai kiểu ghi: **thay bằng bản dịch** hoặc **song ngữ** (cell: `JP` xuống dòng `EN`; shape: `JP / EN`).
- Xuất thêm **một file Markdown chung** để đọc/đối chiếu (có thể tắt).
- Cache bản dịch ra đĩa: bấm Dừng hoặc chạy lại thì không phải dịch lại phần đã xong.
- Có giao diện (tkinter) và chạy dòng lệnh.

## Cài đặt

1. Cài Ollama từ https://ollama.com và tải một model:

   ```bash
   ollama pull qwen2.5:7b
   ```

2. Cài Python 3.8+ và các thư viện:

   ```bash
   pip install -r requirements.txt
   ```

   (`lxml` để sửa XML, `openpyxl` chỉ dùng để đọc dữ liệu khi xuất Markdown. Trên Linux có thể cần thêm `python3-tk` cho giao diện.)

3. Đảm bảo Ollama đang chạy (`ollama serve`, hoặc app Ollama đang mở). Mặc định app kết nối tới `http://localhost:11434`.

## Cách dùng

### Giao diện

```bash
python app.py
```

Chọn file `.xlsx`/`.xlsm` → bấm **Tải model** để lấy danh sách model từ Ollama → chọn kiểu ghi → **Bắt đầu dịch**. Có thanh tiến độ và nút **Dừng** (phần đã dịch vẫn được lưu).

### Dòng lệnh

```bash
python app.py input.xlsx
python app.py input.xlsx -o output.xlsx -m qwen2.5:3b --mode bilingual --no-md
```

| Tham số | Ý nghĩa | Mặc định |
|---|---|---|
| `input` | File `.xlsx` hoặc `.xlsm` cần dịch | bắt buộc |
| `-o`, `--output` | File kết quả | `<tên>_en.xlsx` cạnh file gốc |
| `-m`, `--model` | Tên model Ollama | `qwen2.5:7b` |
| `--host` | Địa chỉ Ollama | `http://localhost:11434` |
| `--mode` | `replace` (thay bằng bản dịch) hoặc `bilingual` (JP + EN) | `replace` |
| `--no-md` | Không xuất file Markdown | xuất |

File gốc **không bị sửa**. File output luôn phải khác file input.

## Kết quả

Với `report.xlsx`, app tạo:

- `report_en.xlsx`: bản đã dịch.
- `report_en.md`: bản Markdown (nếu không tắt).
- `report_en.xlsx.cache.json`: cache bản dịch, dùng lại khi chạy lại cùng model. Đổi model thì dịch lại từ đầu. Xóa file này nếu muốn dịch lại hoàn toàn.

### File Markdown

Một file chung, mỗi sheet là một mục, để đối chiếu với Excel:

- Đầu file có danh sách tất cả sheet và vùng dữ liệu (ví dụ `A1:E4`).
- Mỗi mục ghi **tên sheet gốc** đúng như trong Excel (kèm bản dịch tiếng Anh chỉ để tham khảo).
- Cột `#` là **số dòng Excel**, tiêu đề cột là **chữ cột Excel** (A, B, C…). Dòng trống được bỏ qua nhưng số dòng giữ nguyên, nên "dòng 4, cột C" trong Markdown chính là ô `C4`.
- Comment được liệt kê kèm địa chỉ ô; text box kèm vị trí "gần ô" nào.
- Giới hạn 20.000 dòng và 200 cột mỗi sheet (sheet dài hơn bị cắt và có ghi chú).

## Chọn model cho máy yếu

Chạy CPU (ví dụ i5-8500, RAM 32GB, không GPU) thì tốc độ là điểm yếu. Các con số dưới đây chỉ là ước lượng, hãy chạy thử 20–30 cell để đo thực tế:

| Model | Tốc độ ước tính (cell ngắn) | Ghi chú |
|---|---|---|
| `qwen2.5:3b` | ~2–3 giây/cell | Nhanh nhất, chất lượng tạm được, hợp văn bản đơn giản |
| `qwen2.5:7b` | ~5–8 giây/cell | Cân bằng nhất, dịch tốt hơn rõ |
| ≥ 9B | rất chậm | Không nên dùng trên CPU yếu |

Mẹo: đóng các app nặng khi chạy; app giữ model trong RAM 30 phút giữa các lần gọi; các cell trùng nội dung chỉ dịch một lần.

## Giới hạn

- **Không dịch**: công thức, tên sheet, pivot cache, threaded comments (comment kiểu mới).
- Tên sheet giữ nguyên để không làm hỏng công thức tham chiếu; bản dịch tên sheet chỉ xuất hiện trong file Markdown.
- Ô công thức đang hiện kết quả tiếng Nhật: kết quả cũ vẫn hiện cho đến khi Excel tính lại. Mở file output, nhấn **F9** và lưu. Markdown lấy kết quả đã tính sẵn của Excel, nên nếu cần hãy làm bước này trước rồi chạy lại.
- Tên cột của Table sau khi dịch có thể trùng nhau; app tự thêm số (2, 3…) để tránh lỗi, nhưng khi đó tên cột có thể lệch với header cell.
- Chỉ hỗ trợ `.xlsx` / `.xlsm`. File `.xls` cũ hãy **Save As** sang `.xlsx` trước.
- Ô gộp (merge) trong Markdown chỉ hiện giá trị ở ô góc trái trên.
- Chất lượng dịch phụ thuộc model; nên kiểm tra các thuật ngữ chuyên ngành.

## Trạng thái kiểm thử

Đã kiểm tra với bản dịch giả lập trên file mẫu (cell, shape, biểu đồ, comment, table, nhiều sheet) và mở được bằng LibreOffice. **Chưa kiểm tra trên Excel thật và với model Ollama thật** — hãy thử trên một bản sao trước khi dùng cho file quan trọng.

## Giấy phép

Apache License 2.0, xem file [LICENSE](LICENSE).
