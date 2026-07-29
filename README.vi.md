# Local Knowledge Suite

[English](README.md) · [Tài liệu tiếng Việt](https://luutru433-coder.github.io/local-knowledge-suite/) · [Bảo mật](SECURITY.md) · [Hỗ trợ](SUPPORT.md)

Local Knowledge Suite là plugin Codex miễn phí, mã nguồn mở dành cho Windows.
Mỗi project có một vùng ghi nhớ riêng. Nếu cần, nhiều project có thể dùng
chung một kho kiến thức công ty có trích dẫn.

## Hiểu bằng từ đơn giản

- **Skill** giống như quy trình làm việc: nó chỉ Codex phải làm theo các bước
  nào và điều gì không được làm.
- **MCP** giống như bốn nút thao tác: Codex gọi chúng để chuẩn bị project, kiểm
  tra trạng thái, tìm lại thông tin và lưu một ghi nhớ.
- **Memory** ghi nhớ sở thích, quyết định và quy ước của đúng một project.
- **Company Knowledge** lưu kiến thức chung của công ty và yêu cầu bằng chứng
  nguồn trước khi dùng để trả lời.

MCP giúp giảm việc bạn phải dán lại thông tin thủ công, giữ đúng đường dẫn và
project, kiểm tra lỗi tự động, và trả kết quả theo cấu trúc ổn định. Nó không tự
biến dữ liệu chưa kiểm chứng thành sự thật.

Plugin chạy cục bộ, không có telemetry hoặc analytics. Bản v1 hỗ trợ Windows.

## Bắt đầu trong 5 phút: chỉ dùng Memory

Bạn cần Windows 10/11, PowerShell 5.1+, Git, Codex và
[`uv`](https://docs.astral.sh/uv/).

Cài marketplace từ đúng bản phát hành trên GitHub:

```powershell
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.0
codex plugin add local-knowledge-suite@john-idk
```

Khởi động lại Codex, mở task mới, vào project rồi yêu cầu:

```text
Dùng $manage-local-knowledge để khởi tạo project này ở chế độ memory-only,
sau đó kiểm tra trạng thái Local Knowledge.
```

Bạn không cần tạo công ty. Profile mặc định của v1 là `memory-only`.

Người dùng bình thường chỉ cần yêu cầu Codex, không cần biết đường dẫn plugin.
Nếu muốn tự chạy CLI, tìm và kiểm tra đường dẫn cài đặt một lần:

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
    "project", "init", "--root", $ProjectRoot,
    "--profile", "memory-only", "--install-mode", "global"
  )
```

Luôn dùng đường dẫn tuyệt đối. Sau khi cài, chạy `project doctor` và mở task
Codex mới để nạp skill và MCP.

Trong repo ứng dụng của người dùng (không phải repo source sản phẩm này), review
và commit danh tính project cùng các dòng ignore được quản lý:

```powershell
git add .local-knowledge/project.toml .gitignore
git diff --cached -- .local-knowledge/project.toml .gitignore
git commit -m "chore: initialize local knowledge workspace"
```

Nếu không commit manifest, máy mới sẽ tạo project ID khác và không import được
Memory snapshot của project cũ.

## Thêm kiến thức công ty

Ví dụ dưới đây dùng công ty giả `Northstar Bicycle Labs`:

```powershell
$CompanyRoot = "D:\Knowledge\Northstar-Bicycle-Labs"
$AdminUser = "admin"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "init", "--root", $CompanyRoot,
    "--name", "Northstar Bicycle Labs", "--admin", $AdminUser
  )
```

Lệnh sẽ trả về `company_id`. Khởi tạo project với profile `combined` để dùng cả
Memory riêng và kiến thức công ty chung. V1 không gắn lại company vào project
Memory-only đã khởi tạo; phải chọn `combined` ngay lần bootstrap đầu. Tài liệu
gốc được phép đọc phải nằm
trong thư mục bị Git bỏ qua `COMPANY_ROOT\.local-sources\`. Chỉ commit manifest
công ty và thư mục `knowledge/`.

## Bốn công cụ MCP

| Công cụ | Hiểu đơn giản |
| --- | --- |
| `bootstrap_workspace` | Chuẩn bị đúng cấu trúc cho một project. |
| `knowledge_status` | Kiểm tra phiên bản, dữ liệu, cảnh báo và việc còn chờ. |
| `recall_context` | Tìm skill, Memory và bằng chứng công ty theo ba nhóm riêng. |
| `capture_memory` | Lưu một ghi nhớ bền vững sau khi loại dữ liệu nhạy cảm. |

`knowledge_status` và `recall_context` không phá hủy dữ liệu và có thể gọi lặp
lại, nhưng không được khai báo là chỉ đọc. Status có thể tạo khóa cục bộ tạm
thời; recall có thể xử lý các Memory event đã capture nhưng còn chờ, rồi tạo
lại hoặc cache index dẫn xuất.

Chỉ dùng câu trả lời công ty khi `evidence_sufficient: true` và trích dẫn đã
được xác minh. Memory không thay thế bằng chứng công ty.

Memory snapshot là plaintext và chỉ được đưa vào repo project của người dùng
sau khi review. Repo sản phẩm này ignore
`.local-knowledge/memory-snapshot/` và không phát hành Memory thật.

## Tài liệu

- [Hướng dẫn tiếng Việt đầy đủ](https://luutru433-coder.github.io/local-knowledge-suite/)
- [English guide](https://luutru433-coder.github.io/local-knowledge-suite/en/)
- [Checklist chuyển máy Windows](docs/MIGRATION_CHECKLIST.vi.md)
- [Kiến trúc](docs/ARCHITECTURE.md)
- [Roadmap nền tảng](docs/ROADMAP.md)
- [Phân phối và sử dụng thương mại](https://luutru433-coder.github.io/local-knowledge-suite/guide/distribution)
- [Checklist phát hành](docs/RELEASE_CHECKLIST.md)

Hướng dẫn bao gồm: cài global/vendored, ingest công ty, dùng chung cho nhiều
project, export/import Memory, quyền riêng tư, bảo mật, sửa lỗi, gỡ cài đặt,
MCP/CLI và cách phát triển với pnpm.

## Vì sao dùng pnpm thay vì npm?

Người sử dụng plugin không cần Node.js. Chỉ người phát triển website/portal mới
cần Node 22 và pnpm 11.9.0. Dự án có hai package JavaScript; pnpm dùng chung một
lockfile, không tải lặp cùng dependency và `--frozen-lockfile` sẽ báo lỗi nếu
file khai báo không khớp bản đã khóa. Nhờ vậy build trên máy mới và CI dễ lặp
lại chính xác hơn.

## Giấy phép

Copyright © 2026 John-IDK. Mã nguồn dùng [MIT License](LICENSE). Dependency
bên thứ ba vẫn giữ giấy phép riêng; xem
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
