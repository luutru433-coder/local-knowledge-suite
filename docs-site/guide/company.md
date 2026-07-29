# Kiến thức công ty

Company Knowledge Base dùng cho thông tin phải có nguồn: chính sách, sản phẩm,
quy trình, hợp đồng mẫu hoặc tài liệu nội bộ. Ví dụ này chỉ dùng công ty giả
`Northstar Bicycle Labs`.

Các lệnh dưới đây giả định bạn đã đặt `$PluginRoot` theo
[Cài đặt nhanh](/guide/getting-started). Người dùng bình thường có thể yêu cầu
Codex dùng `$company-knowledge-base` mà không tự tìm đường dẫn.

## 1. Tạo repository riêng

Không tạo company repository bên trong project ứng dụng.

```powershell
$CompanyRoot = "D:\Knowledge\Northstar-Bicycle-Labs"
$AdminUser = "admin"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "init",
    "--root", $CompanyRoot,
    "--name", "Northstar Bicycle Labs",
    "--admin", $AdminUser
  )
```

Chỉ nhập mật khẩu tại dấu nhắc ẩn (`getpass`) do terminal hiển thị. Không đưa
**mật khẩu** vào `ToolArguments`, biến môi trường, prompt chat, file, log hoặc
Git. Ghi lại `company_id` được trả về.

Company repository có:

```text
.local-knowledge\company.toml   commit
knowledge\                      commit
.local-sources\                 không commit
.ckb\                           không commit
```

Nếu dùng GitHub, tạo remote **private** cho company repository.

## 2. Cấu hình model và credential

`company init` tạo `.ckb\config.json` với tên model mẫu
`local-chat-model` và `local-embedding-model`. Đây chỉ là placeholder, không
phải model dùng được.

```powershell
$CompanyId = "northstar-bicycle-labs" # company_id do lệnh init trả về
```

Mở Local Server trong LM Studio, load một chat model và một embedding model.
Khi server không yêu cầu bearer token, lệnh sau liệt kê ID chính xác:

```powershell
$LmStudioUrl = "http://127.0.0.1:1234/v1"
(Invoke-RestMethod -Method Get -Uri "$LmStudioUrl/models").data |
  Select-Object -ExpandProperty id
```

Nếu server yêu cầu bearer token, đọc ID model trong giao diện LM Studio. Sau đó
ghi đúng URL và hai ID vừa thấy vào config không chứa secret:

```powershell
$ChatModel = Read-Host "Exact chat model ID"
$EmbeddingModel = Read-Host "Exact embedding model ID"
$ConfigPath = Join-Path $CompanyRoot ".ckb\config.json"
$Config = if (Test-Path -LiteralPath $ConfigPath) {
  Get-Content -Raw -Encoding utf8 $ConfigPath | ConvertFrom-Json
} else {
  [pscustomobject]@{}
}
$Config | Add-Member NoteProperty lm_studio_url $LmStudioUrl -Force
$Config | Add-Member NoteProperty chat_model $ChatModel -Force
$Config | Add-Member NoteProperty embedding_model $EmbeddingModel -Force
$ConfigJson = $Config | ConvertTo-Json -Depth 20
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
  $ConfigPath,
  $ConfigJson + [Environment]::NewLine,
  $Utf8NoBom
)
```

Ba giá trị bắt buộc trong file sẽ giống cấu trúc này:

```json
{
  "lm_studio_url": "http://127.0.0.1:1234/v1",
  "chat_model": "ID_CHAT_MODEL_CHÍNH_XÁC",
  "embedding_model": "ID_EMBEDDING_MODEL_CHÍNH_XÁC"
}
```

Không đặt token hoặc mật khẩu Git trong file. Chạy portal, đăng nhập admin, mở
**Settings → Credentials**, rồi lưu LM Studio bearer token nếu server yêu cầu.
Chỉ cấu hình Git username/PAT ở đây khi company dùng private remote để
sync/push:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "serve", "--company", $CompanyId,
    "--host", "127.0.0.1", "--port", "8000"
  )
```

Portal mã hóa credential; khóa chính nằm trong Windows Credential Manager.
Trước khi thêm nguồn, chạy health:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "health", "--company", $CompanyId)
```

Đọc JSON trả về, không chỉ exit code: `status` phải là `ok`, `database` là
`true`, chat endpoint sẵn sàng, secret backend không lỗi và `okf` không có lỗi.
Embedding model phải sẵn sàng để có semantic search; nếu không, search chỉ còn
lexical. OCR chỉ bắt buộc khi ingest PDF scan.

## 3. Gắn project

```powershell
$ProjectRoot = "D:\Projects\northstar-support"
$CompanyId = "northstar-bicycle-labs"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init",
    "--root", $ProjectRoot,
    "--company", $CompanyId,
    "--profile", "combined",
    "--install-mode", "global"
  )
```

`combined` dùng Memory riêng và company chung. `company-only` bỏ Memory nhưng
vẫn bắt buộc company đã đăng ký.

## 4. Thêm nguồn

Copy tài liệu đã được phép đọc vào `.local-sources\`. Ví dụ:

```powershell
$SourcePath = Join-Path $CompanyRoot ".local-sources\support-policy.md"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "source-add", "--company", $CompanyId,
    "file", $SourcePath, "--title", "Support policy"
  )
```

Lệnh trả về source ID. Queue và chạy job:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "ingest", "--company", $CompanyId, "1")

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "run-job", "--company", $CompanyId, "1")
```

Thay `1` bằng ID thực tế. Với website, dùng URL HTTP(S) công khai và truyền
`--allow-domain` cho từng domain được phép. Plugin từ chối localhost, mạng riêng
và domain ngoài allowlist.

## 5. Review và trả lời

Chạy portal:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "serve", "--company", $CompanyId,
    "--host", "127.0.0.1", "--port", "8000"
  )
```

Mở `http://127.0.0.1:8000`. Review claim, excerpt, locator và confidence.
Chỉ câu có `evidence_sufficient: true`, citation `verified: true`,
`source_uri`, `locator` và excerpt hỗ trợ chính xác mới được dùng.

Nếu bằng chứng thiếu, Codex phải nói kho công ty chưa đủ bằng chứng. Không lấy
Memory hoặc nội dung skill để lấp chỗ trống.
