# Chuyển Memory bằng snapshot

Memory vault mặc định là dữ liệu cục bộ, bị Git bỏ qua. Snapshot cho phép chuyển
một phần nguồn Memory sang máy khác bằng quy trình có kiểm soát.

Các lệnh dưới đây dùng `$PluginRoot` đã được tìm theo
[Cài đặt nhanh](/guide/getting-started).

Trên máy cũ, gán và resolve hai đường dẫn trước:

```powershell
$ProjectRoot = (Resolve-Path "D:\Projects\northstar-support").Path
$SnapshotPath = Join-Path $ProjectRoot ".local-knowledge\memory-snapshot"
```

::: danger Snapshot là văn bản thường
Snapshot **không được mã hóa**. Người đọc file hoặc Git history có thể đọc nội
dung. Luôn review trước khi commit hoặc chia sẻ.
:::

## Export vào repo private

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "export",
    "--root", $ProjectRoot,
    "--output", $SnapshotPath,
    "--git-visibility", "private"
  )
```

Snapshot xác định được gồm:

- `snapshot.json` với schema và SHA-256;
- `memory/config.json`; và
- `memory/notes/*.md`.

Nó không chứa daily journal, SQLite/index, cache, lock, `MEMORY.md` hoặc entity
view. Những phần đó được dựng lại sau import.

Fingerprint trong manifest bao phủ schema, format, project ID, metadata và danh
sách file chuẩn hóa. Đây là kiểm tra tính toàn vẹn không dùng khóa, không phải
bằng chứng mật mã về nguồn gốc hay tính xác thực: người sửa được snapshot cũng
có thể tính lại checksum. Vì vậy vẫn phải dùng kênh chuyển tin cậy hoặc Git
history đã review.

## Chuyển snapshot qua Git của project

Mở từng file trong snapshot và bảo đảm không có secret, dữ liệu công ty hoặc
thông tin cá nhân ngoài ý định. Sau đó kiểm tra chính xác diff:

```powershell
git -C $ProjectRoot status --short
git -C $ProjectRoot add .local-knowledge/memory-snapshot
git -C $ProjectRoot diff --cached -- .local-knowledge/memory-snapshot
```

Nếu review phát hiện nội dung không nên commit, bỏ stage rồi sửa/export lại:

```powershell
git -C $ProjectRoot restore --staged .local-knowledge/memory-snapshot
```

Chỉ sau khi phần diff đã stage là đúng:

```powershell
git -C $ProjectRoot commit -m "chore(memory): add reviewed project snapshot"
git -C $ProjectRoot push
```

Sau khi review, PowerShell 7 có thể nối `git commit ... && git push`;
PowerShell 5.1 phải chạy từng dòng như trên. Chỉ làm việc này trong repo project
của người dùng. Repo
sản phẩm Local Knowledge Suite tự ignore
`.local-knowledge/memory-snapshot/`, vì vậy release không bao giờ đóng gói
Memory thật.

## Sensitive Memory

Sensitive Memory bị loại mặc định. Chỉ thêm khi thật sự cần:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "export",
    "--root", $ProjectRoot,
    "--output", $SnapshotPath,
    "--git-visibility", "private",
    "--include-sensitive",
    "--acknowledge-sensitive"
  )
```

Hai flag phải đi cùng nhau. Không dùng cách này cho mật khẩu, token, private key
hoặc recovery phrase; các giá trị đó không được lưu vào Memory ngay từ đầu.

## Repo public

Export với ý định commit vào repo public bị chặn nếu thiếu xác nhận:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "export",
    "--root", $ProjectRoot,
    "--output", $SnapshotPath,
    "--git-visibility", "public",
    "--allow-public"
  )
```

`--allow-public` không làm dữ liệu an toàn hơn; nó chỉ chứng minh người chạy đã
xác nhận rủi ro. Review file và Git diff vẫn bắt buộc.

## Import trên máy mới

Trên máy mới, clone hoặc pull đúng project để giữ cùng `project_id`:

```powershell
$ProjectRepositoryUrl = "https://github.com/your-org/northstar-support.git"
$ProjectRoot = "D:\Projects\northstar-support"
git clone $ProjectRepositoryUrl $ProjectRoot
# Nếu clone đã có, dùng: git -C $ProjectRoot pull
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$SnapshotPath = Join-Path $ProjectRoot ".local-knowledge\memory-snapshot"
```

Sau đó import:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "import",
    "--root", $ProjectRoot,
    "--input", $SnapshotPath
  )
```

Mặc định import chỉ chấp nhận vault trống và snapshot đúng project ID, checksum
hợp lệ. Nếu dùng `--replace`, runtime tạo backup local trước khi thay. V1 không
merge hai snapshot.

Sau import, chạy `project doctor` và `knowledge_status`. Kiểm tra
`present`, `valid`, `freshness`, `item_count` và `includes_sensitive`.
