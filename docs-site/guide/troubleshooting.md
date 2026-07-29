# Sửa lỗi

Các lệnh dưới đây dùng `$PluginRoot` đã được tìm theo
[Cài đặt nhanh](/guide/getting-started).

## Bắt đầu bằng hai kiểm tra

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

Sau đó gọi MCP `knowledge_status` với cùng đường dẫn tuyệt đối. Không sửa file
manifest hoặc database trước khi đọc cảnh báo.

## Không thấy skill hoặc MCP

- Xác nhận plugin xuất hiện trong Codex.
- Khởi động lại Codex.
- Mở task mới sau cài đặt/nâng cấp.
- Với vendored mode, trust project rồi chạy `-Action Verify`.
- Kiểm tra `.codex/config.toml` còn block được vendor script quản lý.
- Nếu lỗi xuất hiện sau update, làm lại đúng quy trình
  [update/rollback theo tag](/guide/install-modes); không trộn file từ hai tag.

## “Company is not registered”

Project `combined` hoặc `company-only` đang trỏ đến một company ID chưa được ánh
xạ trên máy này:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "register", "--root", $CompanyRoot, "--admin", "admin"
  )
```

Không sửa registry hoặc `company_id` bằng tay.

Nếu một root cũ đang được map sai, dùng
`company unregister --root ABSOLUTE_COMPANY_ROOT` theo
[hướng dẫn gỡ đăng ký](/guide/uninstall), rồi register root đúng. Không xóa
mapping trực tiếp trong file registry.

## Migration required

Xem trước:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("migrate", "--root", $ProjectRoot, "--dry-run")
```

Nếu nội dung đúng, apply:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("migrate", "--root", $ProjectRoot, "--apply")
```

Migration schema 1/0.2 sang schema 2 tạo backup trước khi ghi. Không thay
`schema_version` thủ công.

## Memory còn event chờ

Dùng `$memorizer` để chạy status, distill, rồi validate. Chỉ báo capture thành
công khi pending bằng 0. Nếu index hỏng nhưng Markdown nguồn còn tốt, chạy
`rebuild`; không chỉnh SQLite.

## Company search không trả sự thật

Kết quả có thể nằm trong `attested_results` vì source chưa được xác minh trên
máy mới. Khôi phục file vào `.local-sources\` hoặc crawl lại website, rồi ingest.
Git chỉ giữ lịch sử canonical, không xác minh source hiện tại.

## PDF scan không có chữ

Chạy company `health`. Cài Tesseract và language pack `eng`, `vie` nếu tài liệu
song ngữ. PDF có text dùng pypdfium2; trang ít text mới chuyển sang OCR. File
lỗi phải được báo lỗi, không được publish nội dung rỗng.

## LM Studio không hoạt động

Kiểm tra LM Studio đang chạy, local server có endpoint OpenAI-compatible và tên
chat/embedding model khớp `.ckb/config.json`. Chat model lỗi chặn ingestion;
embedding lỗi chỉ làm search quay về lexical.

Endpoint phải dùng `http://127.0.0.1:PORT/...`,
`http://localhost:PORT/...` hoặc địa chỉ IPv6 loopback dạng số. V1 từ chối host
LAN/Internet, credential nằm trong URL, query string và fragment; runtime cũng
bỏ qua proxy môi trường. Nếu config cũ dùng URL từ xa, hãy thay bằng URL LM
Studio cục bộ thay vì làm yếu ranh giới này.

## Cần mở issue

Đọc [hướng dẫn hỗ trợ](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/SUPPORT.md).
Luôn xóa tên công ty, đường dẫn thật, source excerpt và secret trước khi đăng.
