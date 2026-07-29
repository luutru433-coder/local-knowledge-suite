# Một công ty, nhiều project

## Mô hình

```text
Project website ─┐
Project hỗ trợ  ─┼─ company_id: northstar-bicycle-labs
Project nội bộ  ─┘             │
                               └─ Company Knowledge chung

Mỗi project ───────────────────── .memorizer riêng
```

Windows registry ánh xạ một `company_id` ổn định đến đường dẫn company
repository trên máy hiện tại. Vì vậy company có thể nằm ở ổ đĩa khác và nhiều
project vẫn tìm đúng kho. Registry còn lưu quyền cục bộ riêng cho đúng project
ID và đường dẫn tuyệt đối; chỉ biết company ID không tạo ra quyền truy cập.

Các lệnh dưới đây dùng `$PluginRoot` đã được tìm theo
[Cài đặt nhanh](/guide/getting-started).

## Quy trình thêm project

1. Chạy `company list` và lấy đúng `company_id`.
2. Dùng đường dẫn tuyệt đối của project.
3. Chọn `combined` hoặc `company-only`.
4. Chạy `project doctor`.
5. Trust project trong Codex và mở task mới.

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init",
    "--root", "D:\Projects\northstar-store",
    "--company", "northstar-bicycle-labs",
    "--profile", "combined",
    "--install-mode", "global"
  )
```

Lặp lại cho project khác với cùng company ID. Project ID và Memory vẫn khác.
`project init` cấp quyền cho đúng đường dẫn đó. Sau khi di chuyển hoặc clone,
chạy `project restore` để chủ động đăng ký lại project trên máy mới.

## Phạm vi chia sẻ

Các project cùng `company_id` dùng chung qua ranh giới company:

- canonical `knowledge/`;
- claim đã review;
- citation và lịch sử Git; và
- search company sau khi nguồn được xác minh trên máy.

`.ckb/`, database, job state và `.local-sources/` cũng thuộc **company**, không
thuộc một project. Nhiều project của cùng company có thể dùng chúng gián tiếp
qua company ID đã đăng ký, nhưng không được copy hoặc expose các thư mục đó vào
repo project.

Những thứ vẫn tách riêng:

- `.memorizer/` của project;
- project ID và project manifest;
- credential cùng registry chỉ nằm ở phạm vi máy/company; và
- mọi dữ liệu, source hoặc kết quả của hai company ID khác nhau.

## Ví dụ thực tế

Project hỗ trợ hỏi: “Chính sách đổi xe là gì?” Kết quả phải dùng citation công
ty. Project website nhớ “component nút dùng tên `PrimaryButton`”; đây là Memory
của website và không xuất hiện trong project hỗ trợ.

Nếu muốn một quy ước thật sự dùng ở mọi project, đưa nó vào nguồn công ty,
ingest, review và cite. Không copy Memory thủ công để giả lập dữ liệu chung.
