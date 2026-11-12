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

Chọn một file (nút **File…**) hoặc cả folder (nút **Folder…**) → bấm **Tải model** để lấy danh sách model từ Ollama → chọn kiểu ghi → **Bắt đầu dịch**. Có thanh tiến độ và nút **Dừng** (phần đã dịch vẫn được lưu).

### Dòng lệnh

```bash
python app.py input.xlsx
python app.py input.xlsx -o output.xlsx -m qwen2.5:3b --mode bilingual --no-md
python app.py input.xlsx -c my-config.toml
```

### Dịch cả folder

```bash
python app.py ./data               # tạo ./data_en và ./data_en_md cạnh folder gốc
python app.py ./data --dry-run     # chỉ in kế hoạch, không dịch
python app.py ./data -o D:\out --md-out D:\out_md --no-recursive
```

Với folder `data`, app tạo cạnh nó:

```
data/                      data_en/                    data_en_md/
  a.xlsx                     a.xlsx                      a.md
  sub/                       sub/                        sub/
    b.xlsx                     b.xlsx                      b.md
    deep/c.xlsm                deep/c.xlsm                 deep/c.md
```

- Cấu trúc thư mục con và tên file được giữ nguyên; folder gốc không bị sửa. Hậu tố lấy từ `output.suffix` (`_en`) và `output.markdown_suffix` (`_md`).
- Nếu cùng thư mục có `x.xlsx` và `x.xlsm`, file Markdown thành `x.xlsx.md` và `x.xlsm.md` để không ghi đè nhau.
- Chỉ xử lý `.xlsx`/`.xlsm`. `.xls`/`.xlsb` được báo là bỏ qua (hãy Save As `.xlsx`); file ẩn, file khóa `~$...` và file khác không bị đụng tới (không copy sang folder output).
- Cache bản dịch dùng chung cho cả folder, lưu ở `data_en.cache.json`: chuỗi lặp lại giữa các file chỉ dịch một lần, và chạy lại sau khi dừng/lỗi sẽ tiếp tục từ chỗ đã dịch.
- Một file lỗi (hỏng, đang bị khóa…) được ghi lại rồi dịch tiếp các file còn lại; đặt `batch.continue_on_error = false` để dừng ngay. Mã thoát là 1 nếu có file lỗi.

Tham số dòng lệnh **ghi đè** giá trị trong file cấu hình. Không truyền tham số nào thì giá trị lấy từ `config.toml`.

| Tham số | Ý nghĩa | Lấy từ config nếu bỏ trống |
|---|---|---|
| `input` | File `.xlsx`/`.xlsm` hoặc **folder** cần dịch (bỏ trống: mở giao diện) | — |
| `-c`, `--config` | File cấu hình `.toml` | `config.toml` cạnh `app.py` |
| `-o`, `--output` | File kết quả (hoặc folder kết quả nếu input là folder) | `<tên><output.suffix>.xlsx` / `<folder><output.suffix>` |
| `--md-out` | File (hoặc folder) Markdown | cạnh file kết quả / `<folder><suffix><markdown_suffix>` |
| `--no-recursive` | Folder: chỉ xử lý file ở cấp trên cùng | `batch.recursive` |
| `--dry-run` | Chỉ in kế hoạch, không dịch/ghi gì | — |
| `-m`, `--model` | Tên model Ollama | `ollama.model` |
| `--backend` | `ollama` hoặc `llama_cpp` | `backend.type` |
| `--model-path` | File model `.gguf` (tự chuyển sang `llama_cpp`) | `llama_cpp.model_path` |
| `--host` | Địa chỉ Ollama | `ollama.host` |
| `--mode` | `replace` (thay bằng bản dịch) hoặc `bilingual` (JP + EN) | `translate.mode` |
| `--no-md` | Không xuất file Markdown | `output.markdown` |

File gốc **không bị sửa**. File output luôn phải khác file input.

### Dùng file model .gguf (không cần Ollama)

Có thể nhúng thẳng file model GGUF vào app bằng `llama-cpp-python`: model chạy ngay trong tiến trình Python, không có cổng HTTP nào.

```bash
pip install llama-cpp-python        # Windows không có compiler: thêm  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
# tải file .gguf (vd. Qwen2.5-7B-Instruct Q4_K_M) từ Hugging Face vào thư mục models/
python app.py data --model-path models/qwen2.5-7b-instruct-q4_k_m.gguf
```

- Hoặc đặt cố định trong `config.toml`: `[backend] type = "llama_cpp"` và `[llama_cpp] model_path = "models/....gguf"` (xem thêm `n_threads`, `n_ctx`, `n_gpu_layers`).
- GUI có ô chọn backend và nút chọn file `.gguf`.
- **Không commit file model lên git** (vài GB); `models/` và `*.gguf` đã nằm trong `.gitignore`.
- Model được nạp một lần cho cả lượt dịch (kể cả cả folder). Tốc độ xấp xỉ Ollama vì cùng dùng llama.cpp.
- Thiếu file `.gguf` hoặc thiếu thư viện thì app báo lỗi ngay từ đầu, không báo từng đoạn.
- Cache bản dịch tách riêng theo backend và tên file model.

### Chạy bằng Docker (terminal)

Container chỉ có giao diện dòng lệnh (không có GUI). Dữ liệu để trong `./work`, model `.gguf` trong `./models`:

```bash
mkdir -p work models          # copy folder Excel vào ./work/data, file .gguf vào ./models
export UID GID                # để file kết quả không thuộc root (bash); có thể bỏ qua nếu UID đã là 1000
docker compose build          # có llama-cpp-python; bản nhẹ: docker compose build --build-arg WITH_LLAMA=0

# (A) Model .gguf nhúng sẵn. Container chạy với network_mode: none (không có mạng)
docker compose run --rm gguf /work/data --model-path /models/ten-model.gguf

# (B) Ollama chạy trong compose
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b      # lần đầu cần mạng để tải model
docker compose run --rm ollama-cli /work/data -m qwen2.5:7b
docker compose --profile ollama down
```

- Kết quả nằm cạnh folder đầu vào: `./work/data_en`, `./work/data_en_md`. Mọi tham số của `python app.py` dùng được (`--dry-run`, `--mode bilingual`, `--no-md`...).
- Cấu hình dùng trong container là `config.docker.toml` (host Ollama `http://ollama:11434`, `model_path = /models/model.gguf`). `./prompts` được mount vào, nên sửa prompt trên máy là có hiệu lực ngay, không cần build lại.
- Dùng Ollama đã cài sẵn trên máy host thay vì trong compose: thêm `--host http://host.docker.internal:11434` (Linux cần `extra_hosts: ["host.docker.internal:host-gateway"]`).
- Cổng Ollama không được publish ra ngoài. Chỉ bước `ollama pull` cần mạng; nếu cần tuyệt đối không có mạng, dùng cách (A).
- Chưa build thử trên Docker thật trong môi trường của tôi (không có Docker daemon); `docker compose config` hợp lệ và phần cấu hình trong container đã chạy thử ngoài Docker. Nếu build `llama-cpp-python` lỗi, dùng `--build-arg WITH_LLAMA=0` với Ollama.

## Cấu hình

Mọi giá trị trước đây nằm cứng trong code giờ nằm trong `config.toml` (có chú thích từng mục):

| Mục | Điều chỉnh được |
|---|---|
| `[backend]` | `type`: `ollama` hoặc `llama_cpp` |
| `[llama_cpp]` | `model_path`, `n_ctx`, `n_threads`, `n_gpu_layers`, `[llama_cpp.options]` |
| `[ollama]` | `host`, `model`, `keep_alive`, `timeout`, `retries` |
| `[ollama.options]` | Tham số sinh văn bản truyền thẳng cho Ollama: `temperature`, `num_ctx`, `num_predict`, `top_p`... (thêm tùy ý) |
| `[prompt]` | Đường dẫn file system prompt và user prompt |
| `[translate]` | `source_pattern` (regex chọn đoạn cần dịch), `mode`, ký tự nối khi song ngữ |
| `[targets]` | Bật/tắt từng phần được dịch: `cells`, `shapes`, `charts`, `diagrams`, `comments` (`table_headers` luôn theo `cells`) |
| `[dictionary]` | `enabled`, `files` (file từ điển giữ nguyên tiếng Nhật), `suggest`, `suggest_max`, `ignore_file`, `placeholder_note` |
| `[batch]` | `recursive` (vào thư mục con), `continue_on_error` (file lỗi thì dịch tiếp file khác) |
| `[output]` | `suffix`, `markdown_suffix` (đuôi tên file/folder kết quả), xuất Markdown, giới hạn dòng/cột Markdown, bật/tắt cache |

Cách nạp cấu hình:

1. `config.toml` cạnh `app.py` được nạp tự động; chỉ định file khác bằng `-c`.
2. Nếu có `config.local.toml` cạnh nó, các giá trị trong đó **ghi đè** `config.toml`. File này đã nằm trong `.gitignore`, hợp để đặt model hoặc đường dẫn riêng cho từng máy.
3. Mục nào không khai báo thì dùng giá trị mặc định trong `xlsx_trans/config.py`; `[ollama.options]` được **gộp** với mặc định (chỉ cần ghi tham số muốn đổi).
4. Tham số dòng lệnh và giá trị chọn trên giao diện ghi đè tất cả.

Cấu hình sai (regex lỗi, `mode` không hợp lệ, TOML sai cú pháp) sẽ báo lỗi rõ ràng khi khởi động. Nếu file prompt bị thiếu, app dùng prompt mặc định trong code và in cảnh báo.

### Từ điển giữ nguyên tiếng Nhật

Tên màn hình, tên item, tên người, message... cần để nguyên tiếng Nhật thì thêm vào `resources/dictionary.txt` (mỗi dòng một từ, chia nhóm bằng `[tên nhóm]`, dòng `#` là ghi chú):

```
[screen]
ログイン画面
[person]
山田太郎
[message]
保存しました。
```

```bash
python app.py --dict-add person 山田太郎     # thêm nhanh vào file từ điển đầu tiên
python app.py --dict-list                    # xem danh sách
python app.py data --dict khac.txt           # thêm file từ điển (dùng được nhiều lần); --no-dict để tắt
```

Giao diện có nút **Từ điển…** để sửa trực tiếp file.

**Gợi ý tự động.** Mỗi lần dịch một file hoặc cả folder, app quét trước (không gọi model) và hỏi bạn về những từ *có vẻ là danh từ riêng* mà chưa có trong từ điển; bạn chọn từ nào thì thêm từ đó rồi mới dịch:

| Loại | Nhận diện bằng |
|---|---|
| `person` | chữ đứng trước さん / 様 / 氏 / 殿 / 君 (loại お客様, ご担当者様...) |
| `screen` | ô ngắn có đuôi 画面 / 一覧 / 登録 / 詳細 / 管理 / 入力 / 確認 / 検索... |
| `label` | chữ nằm trong 「」 『』 【】 |
| `message` | ô ngắn kiểu 保存しました。 / エラー... |
| `item` | ô chỉ gồm katakana (ưu tiên thấp nhất) |

- Terminal: nhập số cần thêm (`1,3-5`, `a` = tất cả, Enter = bỏ qua lần này); sau đó có thể chọn "không hỏi lại" các từ còn lại. Giao diện: hộp thoại có danh sách để chọn. Khi dịch cả folder chỉ hỏi **một lần**, số lần xuất hiện được cộng gộp qua mọi file.
- Từ được thêm có hiệu lực ngay trong lần dịch đó. Từ bị "không hỏi lại" lưu ở `resources/dictionary.ignore.txt` (xóa dòng để được gợi ý lại).
- Đây chỉ là heuristic nên có gợi ý sai và có từ bị sót; bạn quyết định từng từ. Không có terminal tương tác (chạy tự động, cron) thì gợi ý bị bỏ qua. Tắt hẳn bằng `--no-suggest` hoặc `dictionary.suggest = false`.
- Docker: `docker compose run` có terminal nên hỏi được; thư mục `resources/` được mount vào container để lưu từ điển.

Cách từ điển áp dụng khi dịch:

- Ô chỉ gồm từ trong danh sách (cả khi kèm số, dấu câu) → giữ nguyên, **không gọi model**. Áp dụng cả cho tiêu đề Table (ô và tên cột vẫn khớp nhau) và tên sheet trong Markdown.
- Từ nằm trong câu dài hơn → được thay bằng ký hiệu `[[1]]`, `[[2]]`… trước khi gửi cho model rồi khôi phục đúng chữ gốc sau khi dịch. Nếu model làm mất ký hiệu, app thử lại một lần; vẫn mất thì đoạn đó giữ nguyên bản gốc và tính là một lỗi trong log. Model nhỏ đôi khi làm mất ký hiệu, nên hãy kiểm tra log.
- Từ dài được khớp trước (「ログイン画面」 trước 「ログイン」); phân biệt hoa thường; khớp theo chuỗi con, nên từ ngắn như 「会」 sẽ khớp cả trong 「会社」.
- Sửa từ điển thì cache bản dịch cũ tự không dùng lại. Trong Docker, thư mục `resources/` được mount vào container.
- Thay đổi chỉ dẫn gửi cho model về ký hiệu bằng `[dictionary] placeholder_note` trong `config.toml`.

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

- **Excel Table:** tên cột được dịch cùng ô tiêu đề; nếu hai tiêu đề dịch ra giống nhau thì thêm số 2, 3… vào cả ô lẫn tên cột, và công thức dạng `Table1[[#This Row],[名前]]`, `[@名前]`, defined name được đổi theo. Pivot table, slicer, query table tham chiếu tên cột cũ **không** được đổi (làm mới pivot trong Excel nếu cần).
- Công thức/điều kiện có chuỗi tiếng Nhật viết cứng (vd. `=A1="完了"`, danh sách dropdown `"はい,いいえ"`) không được dịch, nên có thể không còn khớp với cell đã dịch.

- **Không dịch**: công thức, tên sheet, pivot cache, threaded comments (comment kiểu mới).
- Tên sheet giữ nguyên để không làm hỏng công thức tham chiếu; bản dịch tên sheet chỉ xuất hiện trong file Markdown.
- Ô công thức đang hiện kết quả tiếng Nhật: kết quả cũ vẫn hiện cho đến khi Excel tính lại. Mở file output, nhấn **F9** và lưu. Markdown lấy kết quả đã tính sẵn của Excel, nên nếu cần hãy làm bước này trước rồi chạy lại.
- Tên cột của Table sau khi dịch có thể trùng nhau; app tự thêm số (2, 3…) để tránh lỗi, nhưng khi đó tên cột có thể lệch với header cell.
- Chỉ hỗ trợ `.xlsx` / `.xlsm`. File `.xls` cũ hãy **Save As** sang `.xlsx` trước.
- Ô gộp (merge) trong Markdown chỉ hiện giá trị ở ô góc trái trên.
- Chất lượng dịch phụ thuộc model; nên kiểm tra các thuật ngữ chuyên ngành.

## Trạng thái kiểm thử

Đã kiểm tra với bản dịch giả lập trên file mẫu (cell, shape, biểu đồ, comment, table, nhiều sheet) và mở được bằng LibreOffice. Phần cấu hình đã kiểm tra: nạp `config.toml` / `config.local.toml` / file chỉ định bằng `-c`, prompt và options được gửi đúng cho Ollama (kiểm tra trên payload, không gọi model thật), bật/tắt `[targets]`, đổi `suffix`, cache vô hiệu khi đổi prompt, báo lỗi khi cấu hình sai. **Chưa kiểm tra trên Excel thật và với model Ollama thật** — hãy thử trên một bản sao trước khi dùng cho file quan trọng.

## Cấu trúc mã nguồn

```
app.py                 điểm vào (gọi xlsx_trans.cli)
Dockerfile, docker-compose.yml, config.docker.toml   chạy trong container
xlsx_trans/
  config.py            nạp config.toml/prompt, giá trị mặc định
  backend.py           chọn backend model (ollama | llama_cpp)
  suggest.py           gợi ý danh từ riêng chưa có trong từ điển
  dictionary.py        từ điển giữ nguyên tiếng Nhật (bảo vệ/khôi phục từ khóa)
  tables.py            giữ Excel Table nhất quán sau khi dịch
  ollama.py            gọi API Ollama (nơi duy nhất có code mạng)
  llama_local.py       chạy file .gguf trong tiến trình (llama-cpp-python)
  cache.py             cache bản dịch theo chữ ký (model + prompt + options)
  xlsx_xml.py          gom/áp bản dịch trên XML trong file xlsx
  markdown.py          xuất Markdown
  pipeline.py          dịch MỘT file (XML + cache + markdown)
  batch.py             dịch CẢ folder: lập kế hoạch, dựng cấu trúc output
  cli.py               tham số dòng lệnh
  gui.py               giao diện tkinter
tests/                 unittest
```

## Chạy test

Bộ unittest dùng thư viện chuẩn của Python, chạy từ thư mục gốc của repo:

```bash
python -m unittest discover -v
```

- **Không cần Ollama hay mạng**: lời gọi tới Ollama được giả lập; file xlsx mẫu được dựng ngay trong test (`tests/fixtures.py`) với shared strings có furigana, inline string, công thức, comment, table, shape trong `mc:AlternateContent`, biểu đồ và SmartArt.
- Cần `lxml` và `openpyxl` (đã có trong `requirements.txt`); các test Markdown tự bỏ qua nếu thiếu `openpyxl`.
- Phạm vi: nạp và kiểm tra cấu hình/prompt (`test_config.py`), payload và retry gửi Ollama (`test_ollama.py`), gom/áp bản dịch trên XML (`test_xlsx_xml.py`), toàn bộ luồng dịch gồm giữ nguyên các part không đổi, bật/tắt `[targets]`, cache, dừng/tiếp tục, lỗi (`test_process.py`), xuất Markdown (`test_markdown.py`), tham số dòng lệnh (`test_cli.py`).

## Giấy phép

Apache License 2.0, xem file [LICENSE](LICENSE).
