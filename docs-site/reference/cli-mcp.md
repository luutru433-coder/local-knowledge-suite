# Tham chiếu CLI và MCP

Người dùng bình thường có thể yêu cầu Codex gọi MCP mà không cần đường dẫn.
Khi tự chạy CLI, tìm `$PluginRoot` theo
[Cài đặt nhanh](/guide/getting-started).

## Launcher

Các ví dụ gọi runtime đã khóa dependency:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "status", "--root", $ProjectRoot)
```

`$ProjectRoot`, `$CompanyRoot` và output snapshot phải là đường dẫn Windows
tuyệt đối.

## Project

```text
project init --root ROOT
  [--company COMPANY_ID]
  [--profile memory-only|combined|company-only]
  [--install-mode global|vendored]

project status --root ROOT
project doctor --root ROOT
project restore --root ROOT
migrate --root ROOT [--dry-run|--apply]
```

Mặc định v1: `memory-only`, không company, `global`. `combined` và
`company-only` bắt buộc company đã đăng ký. Schema hiện tại là `2`.

## Memory snapshot

```text
memory export --root ROOT --output PATH
  [--git-visibility private|public]
  [--include-sensitive --acknowledge-sensitive]
  [--allow-public]

memory import --root ROOT --input PATH [--replace]
```

`private` là git visibility mặc định. Public luôn cần `--allow-public`.
Sensitive luôn cần acknowledgement. Import mặc định cần vault trống;
`--replace` tạo backup.

## Company

```text
company init --root ROOT --name NAME [--id ID] [--admin USER]
company register --root ROOT [--admin USER]
company unregister --root ROOT
  [--purge-credential-key --confirm-company COMPANY_ID]
company list
company serve --company ID [--host 127.0.0.1] [--port 8000]

company source-add --company ID file|folder|website URI
  [--title TITLE] [--allow-domain DOMAIN] [--branch BRANCH]
company ingest --company ID SOURCE_ID
company run-job --company ID JOB_ID
company worker --company ID [--once]
company search --company ID QUERY [--limit N] [--branch BRANCH]
company health|validate|git-status|sync|push --company ID
```

Mật khẩu admin được nhập tương tác. Không đưa secret vào argument.
`unregister` chỉ xóa mapping đã verify và giữ nguyên repo cùng local data.
Hai purge flag phải đi cùng nhau; xem [Gỡ cài đặt](/guide/uninstall).

Trong v1, `company serve` và `ckb serve` chỉ bind vào loopback. `localhost`
được chuẩn hóa thành `127.0.0.1`; wildcard, IP LAN, hostname và IP từ xa đều
bị từ chối. HTTP Host cũng phải là `localhost` hoặc địa chỉ loopback dạng số,
để chặn DNS rebinding. Portal đóng gói chạy same-origin nên CORS tắt mặc định;
`CKB_CORS_ORIGINS` chỉ là opt-in theo process cho development origin loopback
chính xác và không được lưu vào config. CLI `ckb` trực tiếp cũng bắt buộc
`--root` tuyệt đối, manifest
schema hiện tại và registry phải trỏ đúng company vào chính root đó. Lệnh
không dùng cwd hoặc `CKB_ROOT`; `ckb init` không tạo repo chưa được quản lý.

## Bốn MCP tool

### `bootstrap_workspace`

```text
bootstrap_workspace(
  root,
  company_id=None,
  profile="memory-only",
  install_mode="global"
)
```

Khởi tạo idempotent. Không tạo company ngầm, không đổi danh tính project đã có.

### `knowledge_status`

```text
knowledge_status(root)
```

Trả compatibility, schema, registration, store health, pending Memory, migration
và trạng thái snapshot. Tool này không phá hủy dữ liệu và có thể gọi lặp lại,
nhưng không được khai báo là chỉ đọc vì có thể tạo rồi xóa khóa cục bộ tạm thời.

### `recall_context`

```text
recall_context(
  query,
  root,
  limit=8,
  include_skills=True,
  include_memory=True,
  include_company=True,
  include_sensitive_memory=False
)
```

Kết quả giữ ba phần riêng. Tắt phần không liên quan để giảm dữ liệu. Tool này
không phá hủy dữ liệu và có thể gọi lặp lại, nhưng không được khai báo là chỉ
đọc: nó có thể xử lý Memory event đã capture nhưng còn chờ, đồng thời tạo lại
hoặc cache index dẫn xuất.

### `capture_memory`

```text
capture_memory(
  root,
  kind,
  title,
  text,
  memory_key,
  event_id=None,
  tags=None,
  importance=0.7,
  pinned=False,
  supersedes=None
)
```

Lưu một signal nhỏ. Correction chỉ dùng ID active chính xác trong
`supersedes`. Thành công cần `distilled: true` và pending bằng 0.
