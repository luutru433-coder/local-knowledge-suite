# Riêng tư và bảo mật

## Điều plugin không làm

Local Knowledge Suite không có telemetry, analytics, quảng cáo hoặc dịch vụ
cloud của John-IDK. Runtime không import code từ project đích.

## Khi nào dữ liệu rời máy?

Chỉ khi người dùng cấu hình hoặc yêu cầu:

- push/pull Git remote;
- crawl website công khai;
- export, copy hoặc publish dữ liệu.

Model chỉ được gọi qua LM Studio trên loopback của máy hiện tại. Runtime từ
chối URL model ở Internet/LAN, URL có credential, query hoặc fragment; đồng
thời bỏ qua cấu hình proxy cho lời gọi model. Vì vậy nội dung nguồn không được
gửi tới model endpoint từ xa.

## Secret

Không lưu password, token, private key, recovery code hoặc connection string có
credential vào Memory, Company Knowledge, prompt, file config hoặc Git.
Credential công ty được mã hóa và khóa chính nằm trong Windows Credential
Manager theo company ID.

## Cấp quyền project trên máy

Manifest của project có dùng company chỉ khai báo danh tính, không tự tạo
quyền truy cập. Registry cục bộ phải có đúng bộ `project_id + đường dẫn tuyệt
đối của project + company_id`, được tạo khi chạy rõ ràng `project init` hoặc
`project restore`. Vì vậy chỉ copy hoặc sửa `project.toml` không thể lấy quyền
đọc Company Knowledge. Project bị di chuyển hoặc clone sẽ bị chặn cho tới khi
được restore trên máy đó. Unregister company cũng thu hồi các quyền project
liên quan.

## Dữ liệu Git

Repo sản phẩm có thể public. Repo company nên private. Không commit:

```text
.memorizer/
.ckb/
.local-sources/
web/dist/
registry.json
credential
```

Runtime kiểm tra Git theo path NUL-delimited và không phân biệt hoa/thường trên
Windows. Nếu project track `.memorizer/`, hoặc company repo track state/source
riêng tư ở trên, status/recall/register dừng trước khi dùng dữ liệu đó. Xóa path
khỏi Git history/index và phục hồi state local bằng quy trình migration; chỉ
thêm vào `.gitignore` là chưa đủ với file đã được track.

Memory snapshot là ngoại lệ opt-in và là plaintext. Sensitive bị loại mặc định;
repo public yêu cầu xác nhận riêng. Review từng file.

## Citation gate

Company claim chỉ dùng khi result đủ bằng chứng và từng citation có:

- `verified: true`;
- `source_uri`;
- `locator`; và
- excerpt chính xác hỗ trợ claim.

File bị thay, mất hoặc chuyển hướng làm claim mất tính hợp lệ ngay. Git không
thể tự chứng minh file nguồn vẫn đúng.

## Báo vấn đề

- Lỗi thường: [GitHub Issues](https://github.com/luutru433-coder/local-knowledge-suite/issues)
- Lỗ hổng: [private vulnerability reporting](https://github.com/luutru433-coder/local-knowledge-suite/security/advisories/new)

Không đăng dữ liệu công ty hoặc proof-of-concept nguy hiểm trong issue public.
