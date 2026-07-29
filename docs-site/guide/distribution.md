# Phân phối và sử dụng thương mại

::: info Tóm tắt kỹ thuật, không phải tư vấn pháp lý
Hãy nhờ chuyên gia pháp lý kiểm tra sản phẩm, dependency, thương hiệu, dữ liệu
khách hàng và quy định tại nơi bạn kinh doanh.
:::

## MIT cho phép gì?

[MIT License do OSI công bố](https://opensource.org/license/mit) cho phép dùng,
copy, sửa, merge, publish, phân phối, cấp phép lại và bán phần mềm. Điều kiện
cốt lõi là bản quyền và nội dung MIT permission notice phải xuất hiện trong mọi
bản sao hoặc phần đáng kể của phần mềm.

Vì vậy bạn có thể:

- dùng Local Knowledge Suite trong công ty;
- bán dịch vụ cài đặt, tùy biến, đào tạo hoặc hỗ trợ;
- đóng gói một sản phẩm trả phí dựa trên fork; và
- phân phối source hoặc binary.

MIT không biến dependency thành MIT. Phải giữ và phân phối đúng license/notice
của từng dependency trong `THIRD_PARTY_NOTICES.md`, SBOM và release archive.

ZIP release chính thức là **full source bundle tự chứa và có thể build**: gồm
plugin, runtime, web/portal, docs, tool release, test, CI và lockfile được phép
phân phối. Sau khi giải nén có thể cài plugin từ bundle; đây không phải gói
install-only. Vẫn phải kiểm tra SHA-256, SBOM và notice đi kèm.

SHA-256 giúp phát hiện file khác với checksum bạn đã nhận. Gate của annotated
tag kiểm tra commit được gắn tag có nằm trong lịch sử `main` được bảo vệ hay
không. Hai kiểm tra này không phải chữ ký mật mã và cũng không phải chứng thực
độc lập. Hãy lấy tag, file release và checksum từ repository GitHub chính thức,
đáng tin cậy.

## Checklist trước khi phân phối

1. Chạy toàn bộ gate trong `docs/RELEASE_CHECKLIST.md`.
2. Khóa version, build đúng commit và kiểm tra clean-machine trên Windows.
3. Phát hành ZIP, SHA-256, SBOM và third-party notices.
4. Giữ copyright `2026 John-IDK`, file MIT và notice của code gốc.
5. Ghi rõ phần nào bạn đã sửa và version fork.
6. Không đóng gói source công ty, Memory, credential, registry, `.ckb/`,
   `.local-sources/` hoặc project manifest thật.
7. Dùng dữ liệu giả cho screenshot, demo và tài liệu bán hàng.

## Fork và rebrand

Nếu tạo sản phẩm riêng:

- đổi tên package/plugin, marketplace ID, icon, repository, Pages URL và thông
  tin maintainer để người dùng không nhầm với upstream;
- vẫn giữ copyright/MIT notice của phần code gốc và notice dependency;
- không nói John-IDK hoặc upstream đã chứng nhận, hỗ trợ hoặc vận hành fork;
- tự duy trì update, vulnerability handling, privacy docs và migration; và
- kiểm tra lại mọi URL, checksum, SBOM, install/uninstall guide.

## Support, SLA và hosted service

Upstream v1 chỉ có GitHub Issues, không có SLA, hỗ trợ riêng, hosted service,
billing hoặc license key. Nếu bạn bán dịch vụ, hãy tự công bố rõ:

- ai là bên cung cấp;
- support channel và thời gian phản hồi;
- phạm vi SLA, backup và disaster recovery;
- nơi dữ liệu được lưu/gửi;
- privacy, security, retention và incident process; và
- điều khoản giá, hoàn tiền, chấm dứt.

Không dùng tài liệu upstream để ngầm tạo một cam kết mà maintainer chưa đưa ra.

## Bảo vệ dữ liệu khách hàng

Mỗi khách hàng/company cần repository, source store, credential namespace và
quyền truy cập riêng. Company Git nên private. Memory snapshot là plaintext và
chỉ được chia sẻ sau review. Bản upstream v1 chỉ gọi LM Studio qua loopback cục
bộ. Nếu một fork bổ sung model từ xa hoặc cloud service, không gửi source khách
hàng tới đó khi hợp đồng, privacy notice, access control và lựa chọn rõ ràng
của khách hàng chưa cho phép.
