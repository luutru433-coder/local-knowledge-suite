# Chuyển sang máy Windows mới

Hãy chuyển từng loại dữ liệu đúng cách:

1. repo project giữ code và `.local-knowledge\project.toml`;
2. Memory chỉ chuyển bằng snapshot đã review;
3. company repository giữ manifest và `knowledge\` trên remote private;
4. source gốc được backup riêng, không nằm trong Git; và
5. model, credential, user và quyền được cấu hình lại trên máy mới.

Các lệnh dùng `$PluginRoot` đã được tìm theo
[Cài đặt nhanh](/guide/getting-started).

## Trên máy cũ

### Mọi project

Commit và push project, gồm `.local-knowledge\project.toml` và các dòng
`.gitignore` do runtime quản lý. Nếu cần chuyển Memory, tạo và review
[snapshot](/guide/memory-snapshots).

Ghi lại profile của từng project. Project `memory-only` **bỏ qua toàn bộ bước
company** ở cả máy cũ và máy mới.

### Chỉ khi project dùng company

Push `.local-knowledge\company.toml` và `knowledge\` lên remote private. Không
commit `.ckb\` hoặc `.local-sources\`.

Backup source gốc vào thiết bị được phép và tạo inventory riêng tư, không chứa
credential. Với file/folder, `path` là đường dẫn tương đối bên dưới
`.local-sources\`; với website, `path` là seed URL. Ghi đủ năm trường
`kind`, `path`, `title`, `allow-domain`, `branch`:

```json
[
  {
    "kind": "file",
    "path": "policies\\support-policy.md",
    "title": "Support policy",
    "allow-domain": [],
    "branch": "main"
  },
  {
    "kind": "website",
    "path": "https://docs.example.invalid/start",
    "title": "Public product documentation",
    "allow-domain": ["docs.example.invalid"],
    "branch": "main"
  }
]
```

Ví dụ đặt file trên ổ backup mã hóa:

```powershell
$MigrationRoot = "E:\LocalKnowledgeMigration\northstar"
$SourceInventoryPath = Join-Path $MigrationRoot "source-inventory.json"
$AccessInventoryPath = Join-Path $MigrationRoot "access-inventory.json"
```

Trong portal cũ, ghi thêm inventory quyền gồm username, global role và từng
cặp branch/branch role. Không ghi password, token hoặc master key. Không copy
Windows Credential Manager hay
`%LOCALAPPDATA%\LocalKnowledgeSuite\registry.json`.

## Trên máy mới

### 1. Cài đúng release

Cài Git, Codex, `uv` và Python 3.12, rồi cài tag đã ghi:

```powershell
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.0
codex plugin add local-knowledge-suite@john-idk
```

Restart Codex, mở task mới và tìm lại `$PluginRoot`.

Gắn ổ backup đã được phép và gán lại đường dẫn inventory trên máy mới:

```powershell
$MigrationRoot = "E:\LocalKnowledgeMigration\northstar"
$SourceInventoryPath = Join-Path $MigrationRoot "source-inventory.json"
$AccessInventoryPath = Join-Path $MigrationRoot "access-inventory.json"
```

### 2. Clone project và chọn đúng nhánh khôi phục

Gán đường dẫn trước khi dùng:

```powershell
$ProjectRepositoryUrl = "https://github.com/your-org/northstar-support.git"
$ProjectRoot = "D:\Projects\northstar-support"
git clone $ProjectRepositoryUrl $ProjectRoot
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
```

Đọc profile đã ghi trong project. Thứ tự tiếp theo phụ thuộc vào profile:

- Với `memory-only`, khôi phục project ngay:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "restore", "--root", $ProjectRoot)
```

  Sau đó import snapshot đã review nếu có, chạy `-Action Verify` nếu dùng
  vendored mode, chạy `project doctor`, trust project và dừng ở đây. Không
  clone/register company, không cấu hình model, không phục hồi source và không
  tạo user company.
- Với `combined` hoặc `company-only`, **chưa chạy `project restore`**. Project
  restore cần tìm được company trong registry của máy mới, vì vậy hãy hoàn tất
  bước 3 trước.

### 3. Đăng ký company cho `combined` hoặc `company-only`

```powershell
$CompanyRoot = "D:\Knowledge\Northstar-Bicycle-Labs"
$CompanyId = "northstar-bicycle-labs"
$AdminUser = "admin"
$CompanyRepositoryUrl = "https://github.com/your-org/northstar-company-knowledge.git"

git clone $CompanyRepositoryUrl $CompanyRoot
$CompanyRoot = (Resolve-Path $CompanyRoot).Path

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "register",
    "--root", $CompanyRoot,
    "--admin", $AdminUser
  )
```

Nhập password local mới ở dấu nhắc ẩn. Đừng copy credential từ máy cũ.

Sau khi `company register` thành công, mới khôi phục project:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "restore", "--root", $ProjectRoot)
```

Import snapshot đã review nếu có. Với vendored mode, chạy `-Action Verify`.

### 4. Cấu hình lại model và credential

Load chat/embedding model trong LM Studio, lấy ID chính xác, rồi tạo hoặc cập
nhật config không chứa secret:

```powershell
$LmStudioUrl = "http://127.0.0.1:1234/v1"
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

Không để lại placeholder `local-chat-model` hoặc `local-embedding-model`.

Chạy portal và nhập lại LM Studio bearer token nếu cần. Nếu dùng private remote,
nhập lại Git username/PAT tại **Settings → Credentials**. Không đưa secret vào
config, chat, Git hoặc inventory.

Trước khi source-add hoặc ingest:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "health", "--company", $CompanyId)
```

Chỉ tiếp tục khi JSON có `status: "ok"` và database/chat/secret/OKF đều sẵn
sàng. Sửa embedding nếu cần semantic search; sửa OCR trước khi ingest PDF scan.

### 5. Phục hồi và ingest lại source

Copy source backup vào cùng đường dẫn tương đối dưới
`$CompanyRoot\.local-sources\`. Sau đó dùng inventory để đăng ký và chạy từng
job mới:

```powershell
$SourceRoot = Join-Path $CompanyRoot ".local-sources"
$Inventory = Get-Content -Raw -Encoding utf8 $SourceInventoryPath |
  ConvertFrom-Json

foreach ($Source in $Inventory) {
  $Uri = if ($Source.kind -eq "website") {
    [string]$Source.path
  } else {
    Join-Path $SourceRoot ([string]$Source.path)
  }

  $SourceArgs = @(
    "company", "source-add", "--company", $CompanyId,
    [string]$Source.kind, $Uri,
    "--title", [string]$Source.title,
    "--branch", [string]$Source.branch
  )
  foreach ($Domain in @($Source.'allow-domain')) {
    $SourceArgs += @("--allow-domain", [string]$Domain)
  }

  $Added = (
    & "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
      -Tool local-knowledge -ToolArguments $SourceArgs |
      Out-String
  ) | ConvertFrom-Json
  $Queued = (
    & "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
      -Tool local-knowledge `
      -ToolArguments @(
        "company", "ingest", "--company", $CompanyId, [string]$Added.id
      ) |
      Out-String
  ) | ConvertFrom-Json

  & "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
    -Tool local-knowledge `
    -ToolArguments @(
      "company", "run-job", "--company", $CompanyId,
      [string]$Queued.job_id
    )
}
```

Đây là re-source và ingest mới; không copy `.ckb\` từ máy cũ. Website được
crawl lại theo allowlist. Claims lấy từ Git vẫn chưa verified cho đến khi bằng
chứng được ingest lại.

### 6. Tạo lại user và quyền

Tạo từng user theo access inventory; password luôn nhập ở dấu nhắc ẩn:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "user-add", "--company", $CompanyId,
    "reviewer1", "--role", "reviewer"
  )
```

Trong portal **Branches**, tạo lại branch local nếu cần, rồi gán từng user vào
đúng branch role theo inventory. Không đoán hoặc tự nâng quyền.

### 7. Kiểm tra chấp nhận

Chạy lại company `health`, rồi:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

Trust project, mở task Codex mới, gọi `knowledge_status`, thử một lần recall
Memory và một câu company có citation verified.

Xem
[checklist có thể in](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/docs/MIGRATION_CHECKLIST.vi.md).
