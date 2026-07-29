# Gỡ cài đặt

Gỡ plugin, bỏ đăng ký company và xóa dữ liệu là ba việc riêng. Không bước nào
tự động xóa company repository.

Các lệnh dưới đây dùng `$PluginRoot` đã được tìm theo
[Cài đặt nhanh](/guide/getting-started).

## 1. Backup có chủ đích

- Push code project.
- Export Memory snapshot đã review nếu thật sự cần chuyển.
- Push company manifest và `knowledge\` lên remote private.
- Backup source gốc ở nơi được phép.

Không backup bằng cách commit toàn bộ `.memorizer\`, `.ckb\` hoặc
`.local-sources\`.

## 2. Bỏ đăng ký company trước khi gỡ plugin

Làm bước này khi muốn xóa ánh xạ company khỏi tài khoản Windows hiện tại.
`$CompanyRoot` phải là đường dẫn tuyệt đối, còn tồn tại và chứa đúng manifest:

```powershell
$CompanyRoot = (Resolve-Path "D:\Knowledge\Northstar-Bicycle-Labs").Path

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "unregister",
    "--root", $CompanyRoot
  )
```

Runtime kiểm tra root và `company_id` trước khi xóa đúng mapping. Chạy lại là
an toàn nếu mapping đã không còn. Lệnh luôn giữ nguyên repository,
`.ckb\`, `.local-sources\`, `knowledge\`, manifest và khóa credential.

Chỉ khi chủ dữ liệu yêu cầu xóa khóa mã hóa của đúng company:

```powershell
$CompanyId = "northstar-bicycle-labs"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "unregister",
    "--root", $CompanyRoot,
    "--purge-credential-key",
    "--confirm-company", $CompanyId
  )
```

Hai flag phải đi cùng nhau và ID phải khớp manifest. Xóa master key có thể làm
credential đã mã hóa trong `.ckb\` không đọc lại được. Không chỉnh
`registry.json` hoặc Windows Credential Manager bằng tay.

## 3. Xóa dữ liệu local nếu thật sự muốn

Sau khi backup, resolve và kiểm tra từng đường dẫn. Có thể dùng File Explorer để
xóa có chủ đích:

- `$ProjectRoot\.memorizer\`: Memory của đúng một project;
- `$CompanyRoot\.ckb\`: index, user, job và portal state của đúng company;
- `$CompanyRoot\.local-sources\`: source local của đúng company.

Không xóa đệ quy trên home, workspace root, glob rộng hoặc biến chưa resolve.
Canonical `knowledge\` và Git history không phải cache. Chỉ xóa toàn bộ company
repository khi chủ dữ liệu yêu cầu rõ.

## 4. Gỡ plugin

Mở phần Plugins của Codex, chọn `Local Knowledge Suite` từ marketplace
`john-idk`, rồi chọn Uninstall. Restart Codex và mở task mới.

Nếu đã vendored:

1. commit/stash thay đổi đang làm và xác nhận staged diff không có file không
   liên quan;
2. chạy `-Action Verify` để kiểm tra `vendor-lock.json`, runtime và cả ba bản
   sao skill trước khi xóa;
3. bỏ đúng block Local Knowledge Suite được đánh dấu trong
   `.codex\config.toml`;
4. xóa đúng các path được quản lý:
   `tools\local-knowledge-suite\`, `.local-knowledge\vendor-lock.json`,
   `.agents\skills\manage-local-knowledge\`, `.agents\skills\memorizer\` và
   `.agents\skills\company-knowledge-base\`;
5. review staged diff để chắc chắn không xóa file ngoài danh sách, rồi commit
   toàn bộ thay đổi gỡ cài đặt cùng nhau;
6. giữ `.local-knowledge\project.toml` nếu muốn cài lại và restore sau này.

Không xóa phần config Codex không thuộc plugin.
