# Dùng project nhận từ GitHub mà không cần terminal

Trang này dành cho người được gửi một project qua GitHub và muốn tiếp tục làm
việc với Local Knowledge Suite nhưng không biết PowerShell, Git command hoặc
đường dẫn kỹ thuật của plugin.

Bạn chỉ cần:

1. bấm nút để tải project bằng GitHub Desktop;
2. mở đúng thư mục trong Codex;
3. dán các câu yêu cầu mẫu trong hướng dẫn này; và
4. bấm **Allow** khi Codex hỏi quyền cho thao tác bạn vừa yêu cầu.

Không dán mật khẩu, token GitHub, private key hoặc mã đăng nhập vào chat Codex.

## Trước khi bắt đầu

### Phần mềm cần có

Trên máy Windows, hãy cài:

- **GitHub Desktop** để tải và cập nhật project bằng giao diện;
- **Codex Desktop** để mở project và làm việc với plugin;
- **Python 3.12** và **uv** để Local Knowledge Suite chạy lần đầu.

Bạn không cần Node.js, npm hoặc pnpm khi chỉ sử dụng project. Các công cụ đó chỉ
dành cho người phát triển chính Local Knowledge Suite.

Nếu không chắc máy đã có đủ phần mềm, hãy mở một task Codex không chứa dữ liệu
bí mật và dán:

```text
Kiểm tra máy Windows này đã có GitHub Desktop, Python 3.12 và uv để chạy
Local Knowledge Suite hay chưa. Chưa cài gì. Với phần còn thiếu, hãy chỉ dùng
nguồn chính thức, giải thích nút tôi cần bấm và xin quyền trước khi cài.
Tôi không muốn tự gõ lệnh terminal.
```

Nếu project sử dụng kiến thức công ty, bạn có thể cần thêm:

- **LM Studio**;
- một model chat và một model embedding đã được tải trong LM Studio;
- quyền truy cập repository kiến thức công ty; và
- bản sao hợp lệ của các file nguồn công ty do quản trị viên cung cấp.

### Ba thứ không giống nhau

Hãy hình dung:

- **Project GitHub** là project bạn đang làm, ví dụ website bán xe đạp.
- **Memory** là ghi nhớ riêng của project đó, ví dụ “mọi nút chính dùng màu
  xanh”.
- **Company Knowledge** là kho kiến thức dùng chung, ví dụ chính sách bảo hành
  của công ty và trích dẫn nguồn.

Một project có thể chỉ dùng Memory. Không phải project nào cũng cần Company
Knowledge.

## Phần 1 — Nhận project bằng GitHub Desktop

### Bước 1: mở trang GitHub của project

Người gửi sẽ đưa cho bạn một đường link tương tự:

`https://github.com/ten-cong-ty/ten-project`

Mở đường link đó trong trình duyệt.

Nếu GitHub báo không có quyền truy cập:

1. kiểm tra bạn đã đăng nhập đúng tài khoản GitHub;
2. mở email mời cộng tác;
3. bấm **Accept invitation**; và
4. tải lại trang project.

### Bước 2: bấm nút Code

Trên trang repository:

1. bấm nút màu xanh **Code**;
2. chọn tab **Local** nếu GitHub đang hiển thị tab khác;
3. bấm **Open with GitHub Desktop**; và
4. cho phép trình duyệt mở GitHub Desktop.

### Bước 3: chọn nơi lưu

Trong cửa sổ **Clone a repository**:

1. xem ô **Local path**;
2. chọn một thư mục dễ tìm, ví dụ `Documents\Projects`;
3. không đặt project bên trong một project Git khác;
4. bấm **Clone**; và
5. chờ GitHub Desktop hiện trạng thái **No local changes**.

Ghi nhớ thư mục vừa chọn. Đây là **thư mục gốc của project**.

### Bước 4: không copy project bằng File Explorer

Không kéo một bản project cũ sang chỗ mới để thay cho thao tác clone. Mỗi bản
clone có danh tính đường dẫn khác nhau, nên Local Knowledge phải được khôi phục
rõ ràng trên máy mới.

## Phần 2 — Mở đúng project trong Codex

1. mở **Codex Desktop**;
2. chọn **Open folder** hoặc thao tác tương đương;
3. chọn đúng thư mục vừa clone;
4. kiểm tra tên project đang hiện trong Codex; và
5. tạo một task mới.

Không mở thư mục cha chứa nhiều project. Ví dụ, hãy mở
`Documents\Projects\website-ban-hang`, không mở toàn bộ
`Documents\Projects`.

## Phần 3 — Kiểm tra trước, chưa sửa gì

Dán nguyên câu này vào Codex:

```text
Kiểm tra trạng thái Local Knowledge của project đang mở. Chưa sửa, chưa migrate,
chưa restore và chưa tạo dữ liệu. Hãy nói cho tôi project đang dùng Memory-only,
combined hay company-only, plugin có được cài chưa, và bước tiếp theo an toàn là gì.
```

Kết quả thường rơi vào một trong bốn trường hợp:

| Codex báo | Ý nghĩa đơn giản | Làm tiếp |
| --- | --- | --- |
| Plugin chưa được cài | Máy này chưa có Local Knowledge Suite | Sang Phần 4 |
| Project chưa được khởi tạo | Repository chưa có danh tính Local Knowledge | Sang Phần 5 |
| Cần restore | Project đã có danh tính nhưng đây là máy hoặc đường dẫn mới | Sang Phần 6 |
| Cần migration | Project dùng schema cũ | Sang Phần 7 |
| Trạng thái khỏe | Project sẵn sàng | Sang Phần 8 |

Không tự mở và sửa số `schema_version`, `project_id` hoặc `company_id`.

## Phần 4 — Nhờ Codex cài plugin

Nếu Codex báo plugin chưa có, dán:

```text
Hãy cài Local Knowledge Suite từ GitHub repository
luutru433-coder/local-knowledge-suite, khóa đúng release v1.0.0.
Trước khi thay đổi, hãy kiểm tra có bản cũ hay marketplace trùng tên không.
Chỉ cài plugin local-knowledge-suite@john-idk và xác minh MCP có đúng 4 tools.
```

Codex có thể mở hộp thoại xin quyền:

1. đọc kỹ đường dẫn repository;
2. kiểm tra đúng tài khoản `luutru433-coder`;
3. kiểm tra đúng tag `v1.0.0`;
4. bấm **Allow**;
5. chờ Codex báo plugin `1.0.0` đã được cài; và
6. đóng task hiện tại, rồi mở một task Codex mới.

Plugin và MCP chỉ được nạp đầy đủ khi mở task mới.

Trong task mới, dán:

```text
Xác minh Local Knowledge Suite đang dùng version 1.0.0 và MCP đang có đúng
4 tools: bootstrap_workspace, knowledge_status, recall_context và capture_memory.
Chưa thay đổi dữ liệu project.
```

## Phần 5 — Project GitHub chưa có Local Knowledge

Chỉ làm phần này khi Codex xác nhận repository chưa có manifest Local Knowledge.

### Lựa chọn dễ nhất: Memory-only

Memory-only phù hợp khi project chỉ cần nhớ:

- quy ước code;
- sở thích trình bày;
- quyết định kiến trúc;
- tên component;
- việc đã cam kết; hoặc
- kiến thức riêng của đúng project.

Dán:

```text
Dùng manage-local-knowledge để khởi tạo project đang mở ở chế độ memory-only,
cài đặt global. Sau đó kiểm tra lại trạng thái và nói rõ những file nào cần
được commit lên repository.
```

Sau khi Codex hoàn thành:

1. mở GitHub Desktop;
2. xem tab **Changes**;
3. chỉ mong đợi manifest project và các dòng `.gitignore` được quản lý;
4. đọc phần thay đổi;
5. nhập nội dung commit, ví dụ
   `Initialize Local Knowledge for this project`;
6. bấm **Commit to current branch**; và
7. bấm **Push origin**.

Không commit thư mục `.memorizer`, database, cache hoặc file khóa.

### Không chọn combined chỉ để “dùng thử”

Chỉ chọn `combined` khi quản trị viên đã cung cấp đúng company repository và
company ID. Binding company của project không được đổi bằng cách sửa file thủ
công sau khi project đã khởi tạo.

## Phần 6 — Khôi phục project đã có Local Knowledge

### Trường hợp Memory-only

Dán:

```text
Project này vừa được clone trên máy mới. Hãy dùng manage-local-knowledge để
restore đúng danh tính project hiện có, giữ nguyên profile và company binding,
sau đó chạy project doctor. Không tạo project ID mới.
```

Nếu project có Memory snapshot đã được review trong Git, dán tiếp:

```text
Kiểm tra project có Memory snapshot hợp lệ hay không. Nếu có, hãy giải thích
nội dung và độ nhạy cảm trước. Chỉ import sau khi tôi xác nhận, và không merge
với một vault đã có dữ liệu.
```

### Trường hợp combined hoặc company-only

Không restore project ngay. Trước tiên phải chuẩn bị company repository ở
Phần 9. Manifest project chỉ nói project thuộc company nào; nó không tự cấp
quyền company trên máy mới.

## Phần 7 — Khi Codex báo cần migration

Đầu tiên dán:

```text
Hãy preview migration Local Knowledge của project này. Chỉ đọc và liệt kê:
schema hiện tại, schema đích, những store sẽ thay đổi, nơi tạo backup và
repository nào sẽ bị ảnh hưởng. Chưa apply.
```

Kiểm tra câu trả lời. Với project có Company Knowledge, migration có thể thay
đổi cả manifest project và manifest company.

Khi bạn đồng ý, dán:

```text
Tôi đã xem migration preview. Hãy apply migration được hỗ trợ, giữ backup,
không sửa schema thủ công. Sau đó restore project nếu cần và chạy project doctor.
Nếu bất kỳ bước nào fail, dừng lại và báo đường dẫn backup.
```

Sau đó mở GitHub Desktop cho từng repository bị thay đổi:

1. đọc tab **Changes**;
2. không commit file database, source riêng hoặc credential;
3. commit manifest hợp lệ vào đúng repository;
4. push từng repository riêng; và
5. mở task Codex mới.

## Phần 8 — Cách dùng Memory hằng ngày

### Tìm lại bối cảnh trước khi làm

Ví dụ bạn sắp sửa API:

```text
Trước khi sửa API, hãy tìm Memory và skill liên quan của project này. Tách rõ
điều đã được ghi nhớ, hướng dẫn của skill và suy luận mới của bạn.
```

### Lưu một quyết định lâu dài

Ví dụ thực tế:

```text
Hãy nhớ cho project này: mọi API public phải có ví dụ request và response
trong tài liệu. Đây là quy ước lâu dài của project.
```

Codex phải:

1. tìm ghi nhớ trùng hoặc mâu thuẫn;
2. lưu một thông tin nhỏ, rõ nghĩa;
3. loại dữ liệu bí mật;
4. xử lý ghi nhớ ngay; và
5. xác nhận không còn event chờ.

### Không nên yêu cầu Memory ghi nhớ

Không lưu:

- “tôi đang mở file A”;
- log lỗi chỉ xuất hiện một lần;
- suy đoán chưa được xác nhận;
- nội dung có thể đọc lại từ tài liệu chính thức;
- mật khẩu, token, cookie hoặc private key; hoặc
- sự thật của công ty lấy từ PDF.

### Sửa một ghi nhớ cũ

```text
Quy ước cũ về tên API không còn đúng. Hãy tìm đúng Memory đang hoạt động,
cho tôi xem trước, rồi thay bằng quy ước mới: endpoint public dùng kebab-case.
Giữ lịch sử bằng supersede, không xóa dấu vết.
```

## Phần 9 — Project dùng Company Knowledge

Phần này dành cho profile `combined` hoặc `company-only`.

### Bước 1: nhận đúng company repository

Quản trị viên phải gửi một GitHub repository riêng, thường là private. Repository
này không phải repository code của project.

Clone repository đó bằng GitHub Desktop giống Phần 1, nhưng lưu ở thư mục riêng,
ví dụ:

- project: `Documents\Projects\northstar-support`;
- company: `Documents\CompanyKnowledge\northstar`.

Không đặt company repository bên trong project.

### Bước 2: đăng ký company trên máy mới

Mở project trong Codex và dán:

```text
Project này dùng Company Knowledge. Company repository đã được clone tại
[DÁN ĐƯỜNG DẪN COMPANY REPOSITORY].
Hãy kiểm tra manifest và Git trước. Nếu danh tính hợp lệ, đăng ký company trên
máy Windows này và cho tôi biết có cần tạo administrator hay không.
Không ingest nguồn và chưa restore project.
```

Thay phần trong ngoặc vuông bằng đường dẫn bạn đã chọn trong GitHub Desktop.

Nếu cần mật khẩu administrator, không dán mật khẩu vào chat. Hãy nhập vào hộp
thoại tương tác hoặc giao diện portal do plugin mở.

### Bước 3: restore project

Sau khi company được đăng ký thành công, dán:

```text
Company đã được đăng ký. Bây giờ hãy restore project đang mở với đúng project ID
và company ID có sẵn, sau đó chạy project doctor. Không đổi profile hoặc binding.
```

### Bước 4: chuẩn bị LM Studio

Trong LM Studio:

1. mở mục tải model;
2. tải một model chat phù hợp;
3. tải một model embedding;
4. mở mục model đang chạy;
5. nạp cả hai model;
6. mở local server;
7. xác nhận server đang chạy trên máy local.

Sau đó nói với Codex:

```text
Hãy kiểm tra LM Studio local cho company này. Liệt kê chính xác model chat và
embedding đang được nạp. Chưa thay đổi config cho tới khi tôi xác nhận tên model.
```

Sau khi xem đúng tên model:

```text
Hãy cập nhật cấu hình không bí mật của company bằng đúng hai model vừa xác nhận,
giữ nguyên các khóa cấu hình khác, rồi chạy company health.
```

Nếu LM Studio có bearer token, nhập token trong
**Company Portal → Settings → Credentials**. Không gửi token qua chat.

### Bước 5: khôi phục nguồn công ty

Git company không chứa file nguồn riêng như PDF nội bộ. Quản trị viên phải cung
cấp lại nguồn được phép đọc và một danh sách nguồn.

Đặt các file được phép vào thư mục `.local-sources` của company repository.
Sau đó dán:

```text
Hãy đối chiếu các file trong .local-sources với source inventory do quản trị
viên cung cấp. Chỉ đăng ký nguồn nằm đúng trong thư mục được phép. Cho tôi xem
danh sách file, website, allowed domain và branch trước khi ingest.
```

Sau khi kiểm tra:

```text
Tôi đã duyệt danh sách nguồn. Hãy đăng ký từng nguồn, tạo job ingest mới,
chạy job và giữ lại lịch sử nếu có job fail. Không sử dụng nguồn ngoài danh sách.
```

### Bước 6: kiểm tra một câu trả lời có bằng chứng

Ví dụ:

```text
Dùng Company Knowledge để trả lời: thời hạn bảo hành của sản phẩm là bao lâu?
Chỉ trả lời nếu evidence_sufficient là true. Với mỗi ý được dùng, hãy chỉ ra
source, vị trí và excerpt đã xác minh. Nếu thiếu bằng chứng, hãy nói rõ là chưa đủ.
```

Một câu trả lời hợp lệ phải có:

- nguồn;
- vị trí trong nguồn;
- đoạn trích hỗ trợ trực tiếp;
- trạng thái đã xác minh; và
- không dùng Memory để thay bằng chứng công ty.

## Phần 10 — Ví dụ hoàn chỉnh

Bạn nhận project `northstar-support` từ GitHub. Project này nhớ quy ước UI riêng
và dùng chính sách bảo hành chung của Northstar.

### Việc bạn làm bằng giao diện

1. clone `northstar-support` bằng GitHub Desktop;
2. clone repository company Northstar vào thư mục riêng;
3. mở `northstar-support` trong Codex;
4. yêu cầu Codex kiểm tra nhưng chưa sửa;
5. cài plugin nếu thiếu;
6. mở task mới;
7. đăng ký company repository;
8. restore project;
9. kiểm tra LM Studio;
10. khôi phục và ingest nguồn được quản trị viên duyệt;
11. chạy doctor; và
12. thử một câu hỏi có citation.

### Câu yêu cầu hằng ngày

Trước khi sửa giao diện:

```text
Tìm các Memory liên quan đến quy ước nút và màu sắc của project này.
```

Khi cần chính sách công ty:

```text
Tìm chính sách đổi trả trong Company Knowledge và chỉ dùng nội dung có citation
đã xác minh.
```

Sau khi người phụ trách quyết định một quy ước mới:

```text
Hãy nhớ cho riêng project này: nút hoàn tiền phải yêu cầu xác nhận lần hai.
```

## Phần 11 — Dấu hiệu project đã sẵn sàng

Yêu cầu Codex:

```text
Chạy kiểm tra cuối cho Local Knowledge của project này. Hãy trình bày bằng bảng:
plugin version, project schema, profile, project ID, company registration,
Memory health, pending events, migration, vendor verification và cảnh báo.
Không sửa gì.
```

Project sẵn sàng khi:

- plugin đúng version;
- MCP có đúng bốn tools;
- project schema hiện hành;
- không yêu cầu migration;
- Memory không có event chờ;
- vendored snapshot hợp lệ nếu project dùng vendored mode;
- company được đăng ký đúng nếu profile cần company;
- `project doctor` thành công; và
- một câu hỏi company thử nghiệm có citation hợp lệ.

## Phần 12 — Khi có lỗi

### Codex không thấy skill

1. kiểm tra plugin đã được cài;
2. đóng task hiện tại;
3. mở task mới;
4. mở lại đúng thư mục project; và
5. yêu cầu Codex xác minh plugin version.

### Codex báo project chưa được authorize

Project đang ở máy hoặc đường dẫn mới. Với Memory-only, yêu cầu Codex restore.
Với combined/company-only, đăng ký company trước rồi mới restore project.

### Codex báo migration required

Yêu cầu preview trước. Không sửa số schema bằng Notepad. Chỉ apply migration
được plugin hỗ trợ sau khi đã xem repository bị ảnh hưởng.

### MCP không khởi động

Dán:

```text
Hãy chẩn đoán Local Knowledge MCP nhưng chưa xóa dữ liệu. Kiểm tra plugin version,
Python 3.12, uv, runtime environment và đường dẫn cache. Phân biệt lỗi runtime
với lỗi project manifest, rồi đề xuất bước sửa ít phá hủy nhất.
```

### Company search không có kết quả

Kiểm tra theo thứ tự:

1. company đã đăng ký;
2. project đã restore;
3. LM Studio health;
4. file nguồn hiện vẫn tồn tại và không bị đổi;
5. ingest job thành công;
6. claim đã được review/publish;
7. citation vẫn khớp nguồn hiện tại; và
8. user có quyền trên đúng branch.

Không yêu cầu Codex “tự đoán câu trả lời” khi evidence chưa đủ.

## Checklist ngắn cho người nhận project

- [ ] Tôi clone project bằng GitHub Desktop.
- [ ] Tôi mở đúng thư mục project trong Codex.
- [ ] Tôi kiểm tra status trước khi sửa.
- [ ] Plugin là version được project yêu cầu.
- [ ] Tôi mở task mới sau khi cài hoặc nâng cấp plugin.
- [ ] Tôi không sửa project ID, company ID hoặc schema bằng tay.
- [ ] Nếu project dùng company, tôi clone và đăng ký company trước khi restore.
- [ ] Tôi không đưa mật khẩu hoặc token vào chat.
- [ ] Tôi chạy project doctor.
- [ ] Tôi thử recall Memory.
- [ ] Nếu dùng company, tôi thử một câu trả lời có citation.
