# Checklist chuyển sang máy Windows mới

## Trước khi chuyển

- [ ] Project ứng dụng đã commit và push
      `.local-knowledge/project.toml` cùng các dòng `.gitignore` được quản lý.
- [ ] Với project vendored, đã commit thêm `tools/local-knowledge-suite/`,
      `.local-knowledge/vendor-lock.json`, `.codex/config.toml` và cả ba thư mục
      `.agents/skills/` được quản lý.
- [ ] Company manifest và `knowledge/` đã push vào remote private.
- [ ] Không có `.ckb/`, `.memorizer/`, `.local-sources/` hoặc secret trong Git.
- [ ] Nếu cần Memory, đã export snapshot, review từng file và kiểm tra checksum.
- [ ] Đã ghi profile của từng project; `memory-only` sẽ bỏ qua toàn bộ bước
      company.
- [ ] Tài liệu nguồn company có backup riêng và còn quyền sử dụng.
- [ ] Source inventory riêng tư có đủ `kind`, `path`, `title`, `allow-domain`,
      `branch`; file/folder dùng path tương đối dưới `.local-sources/`.
- [ ] Access inventory có username, global role và branch-role membership,
      không có password/token.
- [ ] Đã ghi lại release plugin cần cài, ví dụ `v1.0.0`.

## Máy mới

- [ ] Cài Windows updates, Git, Codex, `uv` và Python 3.12.
- [ ] Cài marketplace `luutru433-coder/local-knowledge-suite` theo đúng tag.
- [ ] Cài plugin `local-knowledge-suite@john-idk`.
- [ ] Restart Codex.
- [ ] Gán `$ProjectRoot`, clone từng project.
- [ ] Đọc profile của project trước khi restore.
- [ ] Với `memory-only`, chạy `project restore`, import Memory snapshot nếu có,
      rồi chạy `-Action Verify` nếu dùng vendored mode.
- [ ] Verify vendored xác nhận đủ ba bản sao skill thật trong `.agents/skills/`;
      không có file bị thiếu, sửa, thừa hoặc symlink.
- [ ] Project `memory-only` bỏ qua tất cả mục company còn lại.
- [ ] Với `combined`/`company-only`, **chưa chạy `project restore`**: gán
      `$CompanyRoot` và `$CompanyId`, clone company repository private rồi chạy
      `company register` trước.
- [ ] Tạo password local mới; không copy Credential Manager.
- [ ] Chỉ sau khi `company register` thành công, chạy `project restore`, import
      Memory snapshot nếu có, rồi chạy `-Action Verify` nếu dùng vendored mode.
- [ ] Thay placeholder trong `.ckb/config.json` bằng URL và exact chat/embedding
      model ID.
- [ ] Nhập lại LM Studio bearer token và private-Git credential qua portal
      Settings khi cần.
- [ ] Chạy company `health` trước source-add/ingest.
- [ ] Khôi phục source theo đúng relative path, chạy source-add/ingest/job mới
      cho từng inventory entry và crawl website lại theo allowlist.
- [ ] Tạo lại user/global role và branch-role membership từ access inventory.
- [ ] Chạy lại company `health`.
- [ ] Chạy `project doctor`.
- [ ] Trust project và mở task Codex mới.

## Chấp nhận

- [ ] `knowledge_status` báo runtime 1.0.0 và schema 2 tương thích.
- [ ] Memory không còn event chờ.
- [ ] Snapshot status hợp lệ và số item đúng.
- [ ] Project Memory-only không yêu cầu company.
- [ ] Project combined/company-only tìm đúng company ID.
- [ ] Company database/chat model sẵn sàng; embedding/OCR đúng theo nguồn.
- [ ] User và branch role khớp access inventory.
- [ ] Recall Memory thử nghiệm đúng project.
- [ ] Company answer thử nghiệm có citation verified và excerpt chính xác.
- [ ] `git status` không lộ dữ liệu máy hoặc dữ liệu thật ngoài ý định.
