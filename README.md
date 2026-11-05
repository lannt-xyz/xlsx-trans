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
- **Cấu hình và prompt nằm ngoài code**: `config.toml` (model, tham số Ollama, phần nào được dịch, tên file output...) và `prompts/` (system prompt, user prompt) — sửa file là đổi hành vi, không phải sửa code. Xem mục [Cấu hình](#cấu-hình).

## Cài đặt

1. Cài Ollama từ https://ollama.com và tải một model:

   ```bash
   ollama pull qwen2.5:7b
   ```

2. Cài Python 3.8+ và các thư viện:

   ```bash
   pip install -r requirements.txt
   ```

   (`lxml` để sửa XML, `openpyxl` chỉ dùng để đọc dữ liệu khi xuất Markdown, `tomli` chỉ cần với Python < 3.11 để đọc `config.toml`. Trên Linux có thể cần thêm `python3-tk` cho giao diện.)

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
python app.py input.xlsx -c my-config.toml
```

Tham số dòng lệnh **ghi đè** giá trị trong file cấu hình. Không truyền tham số nào thì giá trị lấy từ `config.toml`.

| Tham số | Ý nghĩa | Lấy từ config nếu bỏ trống |
|---|---|---|
| `input` | File `.xlsx` hoặc `.xlsm` cần dịch (bỏ trống: mở giao diện) | — |
| `-c`, `--config` | File cấu hình `.toml` | `config.toml` cạnh `app.py` |
| `-o`, `--output` | File kết quả | `<tên><output.suffix>.xlsx` cạnh file gốc |
| `-m`, `--model` | Tên model Ollama | `ollama.model` |
| `--host` | Địa chỉ Ollama | `ollama.host` |
| `--mode` | `replace` (thay bằng bản dịch) hoặc `bilingual` (JP + EN) | `translate.mode` |
| `--no-md` | Không xuất file Markdown | `output.markdown` |

File gốc **không bị sửa**. File output luôn phải khác file input.

## Cấu hình

Mọi giá trị trước đây nằm cứng trong code giờ nằm trong `config.toml` (có chú thích từng mục):

| Mục | Điều chỉnh được |
|---|---|
| `[ollama]` | `host`, `model`, `keep_alive`, `timeout`, `retries` |
| `[ollama.options]` | Tham số sinh văn bản truyền thẳng cho Ollama: `temperature`, `num_ctx`, `num_predict`, `top_p`... (thêm tùy ý) |
| `[prompt]` | Đường dẫn file system prompt và user prompt |
| `[translate]` | `source_pattern` (regex chọn đoạn cần dịch), `mode`, ký tự nối khi song ngữ |
| `[targets]` | Bật/tắt từng phần được dịch: `cells`, `shapes`, `charts`, `diagrams`, `comments`, `table_headers` |
| `[output]` | `suffix` tên file kết quả, xuất Markdown, giới hạn dòng/cột Markdown, bật/tắt cache |

Cách nạp cấu hình:

1. `config.toml` cạnh `app.py` được nạp tự động; chỉ định file khác bằng `-c`.
2. Nếu có `config.local.toml` cạnh nó, các giá trị trong đó **ghi đè** `config.toml`. File này đã nằm trong `.gitignore`, hợp để đặt model hoặc đường dẫn riêng cho từng máy.
3. Mục nào không khai báo thì dùng giá trị mặc định trong `app.py`; `[ollama.options]` được **gộp** với mặc định (chỉ cần ghi tham số muốn đổi).
4. Tham số dòng lệnh và giá trị chọn trên giao diện ghi đè tất cả.

Cấu hình sai (regex lỗi, `mode` không hợp lệ, TOML sai cú pháp) sẽ báo lỗi rõ ràng khi khởi động. Nếu file prompt bị thiếu, app dùng prompt mặc định trong code và in cảnh báo.

### Tùy chỉnh prompt

- `prompts/system.txt`: system prompt. Sửa để đổi văn phong, thêm quy tắc, thêm bảng thuật ngữ cố định (ví dụ "Translate 売上 as 'Revenue'")...
- `prompts/user.txt`: mẫu user prompt, `{text}` được thay bằng đoạn cần dịch. Mặc định chỉ có `{text}`; có thể thêm hướng dẫn quanh nó, ví dụ `Translate to English:\n{text}`. Nếu file không chứa `{text}`, nội dung file được đặt trước đoạn cần dịch.
- **Đổi ngôn ngữ**: sửa `translate.source_pattern` (regex nhận diện ngôn ngữ nguồn) và `prompts/system.txt` (hướng dịch). Phần còn lại của app không phụ thuộc ngôn ngữ cụ thể (nhãn trên giao diện và trong file Markdown vẫn bằng tiếng Việt).
- Chỉ cần sửa file `.txt`, không cần sửa code. Có thể trỏ `[prompt]` sang file prompt khác, kể cả đường dẫn tuyệt đối.

## Kết quả

Với `report.xlsx`, app tạo:

- `report_en.xlsx`: bản đã dịch.
- `report_en.md`: bản Markdown (nếu không tắt).
- `report_en.xlsx.cache.json`: cache bản dịch, dùng lại khi chạy lại. Cache **tự vô hiệu khi đổi model, prompt hoặc `ollama.options`**, nên sửa prompt xong chạy lại sẽ dịch lại từ đầu. Xóa file này nếu muốn dịch lại hoàn toàn, hoặc tắt bằng `output.cache = false`.

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

Đã kiểm tra với bản dịch giả lập trên file mẫu (cell, shape, biểu đồ, comment, table, nhiều sheet) và mở được bằng LibreOffice. Phần cấu hình đã kiểm tra: nạp `config.toml` / `config.local.toml` / file chỉ định bằng `-c`, prompt và options được gửi đúng cho Ollama (kiểm tra trên payload, không gọi model thật), bật/tắt `[targets]`, đổi `suffix`, cache vô hiệu khi đổi prompt, báo lỗi khi cấu hình sai. **Chưa kiểm tra trên Excel thật và với model Ollama thật** — hãy thử trên một bản sao trước khi dùng cho file quan trọng.

## Chạy test

Bộ unittest dùng thư viện chuẩn của Python, chạy từ thư mục gốc của repo:

```bash
python -m unittest discover -v
```

- **Không cần Ollama hay mạng**: lời gọi tới Ollama được giả lập; file xlsx mẫu được dựng ngay trong test (`tests/fixtures.py`) với shared strings có furigana, inline string, công thức, comment, table, shape trong `mc:AlternateContent`, biểu đồ và SmartArt.
- Cần `lxml` và `openpyxl` (đã có trong `requirements.txt`); các test Markdown tự bỏ qua nếu thiếu `openpyxl`.
- Phạm vi: nạp và kiểm tra cấu hình/prompt (`test_config.py`), payload và retry gửi Ollama (`test_ollama.py`), gom/áp bản dịch trên XML (`test_collectors.py`), toàn bộ luồng dịch gồm giữ nguyên các part không đổi, bật/tắt `[targets]`, cache, dừng/tiếp tục, lỗi (`test_process.py`), xuất Markdown (`test_markdown.py`), tham số dòng lệnh (`test_cli.py`).

## Giấy phép

Apache License 2.0, xem file [LICENSE](LICENSE).
