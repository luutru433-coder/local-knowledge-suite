# Global và vendored

Hai chế độ dùng cùng dữ liệu và quy tắc. Chúng chỉ khác cách project tìm plugin.

Các lệnh dưới đây dùng `$PluginRoot` đã được tìm theo
[Cài đặt nhanh](/guide/getting-started).

```powershell
$ProjectRoot = (Resolve-Path ".").Path
```

## Global

Plugin được cài một lần cho tài khoản Windows và dùng ở nhiều project.

Chọn global khi:

- bạn làm trên một máy;
- muốn cập nhật plugin ở một nơi; và
- project không cần khóa chính xác snapshot plugin.

Project chỉ cần manifest và dữ liệu riêng. Đây là lựa chọn đơn giản cho hầu hết
người dùng. Review và commit `.local-knowledge/project.toml` cùng các dòng
`.gitignore` được runtime quản lý để giữ nguyên project ID khi clone.

## Update hoặc rollback global theo tag chính xác

Tag release là bất biến. Để chuyển từ `v1.0.0` sang đúng `v1.0.1`, gỡ plugin
đang trỏ vào marketplace trước, thay marketplace ref, rồi cài lại plugin:

```powershell
codex plugin remove local-knowledge-suite@john-idk
codex plugin marketplace remove john-idk
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.1
codex plugin add local-knowledge-suite@john-idk
```

Restart Codex, mở task mới, tìm lại `$PluginRoot`, rồi chạy:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

Để rollback, lặp đúng bốn lệnh đầu nhưng dùng tag đã kiểm thử, ví dụ
`--ref v1.0.0`. Lệnh `codex plugin marketplace upgrade john-idk` chỉ refresh
ref marketplace hiện tại; nó không chuyển một marketplace đang khóa ở tag này
sang tag khác.

Chỉ rollback khi release notes xác nhận schema/manifest còn tương thích.
Runtime cũ sẽ fail closed khi gặp schema mới hơn; không sửa `schema_version`
bằng tay. Nếu không tương thích, khôi phục từ migration backup phù hợp hoặc cài
lại release mới.

## Vendored

Một snapshot plugin có version được copy vào
`PROJECT_ROOT\tools\local-knowledge-suite\`. Project commit snapshot, lock hash
và phần config Codex được đánh dấu.

Khởi tạo:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init", "--root", $ProjectRoot,
    "--profile", "memory-only", "--install-mode", "vendored"
  )

& "$PluginRoot\scripts\Install-LocalKnowledgeVendor.ps1" `
  -Action Install -ProjectRoot $ProjectRoot
```

Sau khi clone:

```powershell
& "$ProjectRoot\tools\local-knowledge-suite\scripts\Install-LocalKnowledgeVendor.ps1" `
  -Action Verify `
  -ProjectRoot $ProjectRoot `
  -PluginRoot "$ProjectRoot\tools\local-knowledge-suite"
```

Chọn vendored khi CI, audit hoặc nhóm cần chắc chắn mọi người chạy đúng cùng
một snapshot.

## File nào được commit?

Vendored mode commit:

- `tools/local-knowledge-suite/`;
- `.agents/skills/manage-local-knowledge/`;
- `.agents/skills/memorizer/`;
- `.agents/skills/company-knowledge-base/`;
- `.local-knowledge/project.toml`;
- `.local-knowledge/vendor-lock.json`; và
- block được quản lý trong `.codex/config.toml`.

Không commit `.memorizer/`, `.ckb/`, `.local-sources/`, credential hoặc machine
registry. Nếu muốn chuyển Memory, dùng snapshot có kiểm soát thay vì commit cả
vault.

## Nâng cấp vendored

```powershell
& "$PluginRoot\scripts\Install-LocalKnowledgeVendor.ps1" `
  -Action Upgrade -ProjectRoot $ProjectRoot
```

Upgrade từ chối file vendor bị sửa, tạo backup local và chỉ thay block config
của plugin. Không sửa thủ công snapshot vendored.

Ba thư mục trong `.agents/skills/` là bản sao thật, không phải symlink. Codex
tự tìm skill của project tại đây; block được quản lý trong
`.codex/config.toml` chỉ cấu hình MCP. `Install` không ghi đè skill có sẵn trùng
tên. `Upgrade` sao lưu cả vendor và ba skill vào
`%LOCALAPPDATA%\LocalKnowledgeSuite\vendor-backups\`, khôi phục tất cả nếu lỗi,
và không thay đổi các skill khác của người dùng.
