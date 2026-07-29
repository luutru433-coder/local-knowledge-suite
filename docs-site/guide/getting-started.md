# Cài đặt nhanh

## 1. Chuẩn bị

Bạn cần:

- Windows 10 hoặc 11;
- PowerShell 5.1 trở lên;
- Codex Desktop hoặc CLI;
- Git;
- `uv` trên `PATH`; và
- Python 3.12 để `uv` tải hoặc sử dụng ở lần chạy đầu.

Node.js không cần thiết khi chỉ sử dụng plugin. LM Studio chỉ cần khi bạn ingest
và phân tích nguồn công ty. Tesseract là tùy chọn cho PDF scan.

Nếu Windows chặn script, chỉ mở quyền cho terminal hiện tại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

Quyền này mất khi đóng terminal.

## 2. Cài đúng release từ GitHub

```powershell
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.0
codex plugin add local-knowledge-suite@john-idk
```

Khởi động lại Codex và mở task mới. Skill và MCP được nạp ở ranh giới task mới,
không phải giữa một task đang chạy.

Khi cần đổi version, dùng quy trình
[update/rollback global theo tag chính xác](/guide/install-modes); không ghi đè
file từ hai release.

## 3. Tạo project Memory-only

Mở project trong Codex và nói:

```text
Dùng $manage-local-knowledge để khởi tạo project hiện tại ở chế độ
memory-only, rồi kiểm tra trạng thái.
```

Đây là cách đơn giản nhất và không cần biết đường dẫn plugin. Nếu muốn chạy CLI
trực tiếp, tìm và kiểm tra đường dẫn cài đặt:

```powershell
$Plugin = (codex plugin list --json | ConvertFrom-Json).installed |
  Where-Object { $_.pluginId -eq "local-knowledge-suite@john-idk" } |
  Select-Object -First 1

if (-not $Plugin) { throw "Local Knowledge Suite is not installed." }
$PluginRoot = [IO.Path]::GetFullPath([string]$Plugin.source.path)
$Launcher = Join-Path $PluginRoot "scripts\Invoke-LocalKnowledge.ps1"
if (-not (Test-Path -LiteralPath $Launcher)) {
  throw "Installed Local Knowledge Suite launcher was not found."
}

$ProjectRoot = (Resolve-Path ".").Path

& $Launcher `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init",
    "--root", $ProjectRoot,
    "--profile", "memory-only",
    "--install-mode", "global"
  )

& $Launcher `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

`memory-only` là mặc định của v1. `company_id` để trống hợp lệ với profile này.

## 4. Commit danh tính project

Trong repo ứng dụng của người dùng, không phải repo source Local Knowledge
Suite:

```powershell
git add .local-knowledge/project.toml .gitignore
git diff --cached -- .local-knowledge/project.toml .gitignore
git commit -m "chore: initialize local knowledge workspace"
```

Manifest giữ `project_id` ổn định khi clone. Nếu thiếu nó, Memory snapshot của
project cũ sẽ bị từ chối trên máy mới.

V1 không đổi binding của project đã khởi tạo. Nếu project cần Company
Knowledge, hãy đăng ký company trước và chọn `combined` trong lần bootstrap đầu.

## 5. Thử ghi nhớ và tìm lại

```text
Hãy nhớ trong project này: mọi API public phải có ví dụ request và response.
```

Plugin sẽ tìm ghi nhớ trùng hoặc mâu thuẫn, lưu một thông tin nhỏ, distill ngay
và kiểm tra không còn event chờ.

Sau đó hỏi:

```text
Các quy ước API nào đã được ghi nhớ cho project này?
```

## 6. Kiểm tra thành công

`knowledge_status` hoặc `project doctor` phải cho thấy:

- runtime `1.0.0`;
- project schema `2`;
- profile `memory-only`;
- Memory khỏe và không còn event chờ;
- không yêu cầu company; và
- không có cảnh báo migration.

Tiếp theo: [Skill, MCP và ba loại dữ liệu](/guide/concepts).
