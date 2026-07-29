# Phát triển và build

Người dùng release không cần Node.js. Maintainer cần:

- Windows;
- Python 3.12 và `uv`;
- Node 22;
- pnpm 11.9.0 do repository pin; và
- Git.

## Vì sao dùng pnpm?

Repository có portal React và website VitePress. pnpm phù hợp vì:

1. một workspace và lockfile khóa cả hai package;
2. content-addressed store không lưu nhiều bản giống nhau;
3. cài đặt nghiêm ngặt giúp phát hiện dependency khai báo thiếu;
4. `--frozen-lockfile` làm CI dừng nếu manifest lệch lock; và
5. `--filter` build/test đúng package mà không đổi thư mục thủ công.

npm vẫn có thể chạy JavaScript nói chung, nhưng không phải package manager được
hỗ trợ của repository này. Không tạo `package-lock.json`.

## Lệnh chính

```powershell
pnpm install --frozen-lockfile
pnpm --filter @local-knowledge-suite/docs build
pnpm --filter @local-knowledge-suite/portal build

uv sync --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12
uv run --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12 python -m pytest tests
```

Portal release phải được build từ source rồi đóng gói vào runtime. CI so sánh
artifact để tránh phát hành asset cũ.

## Quy tắc đóng góp

- Dữ liệu test/doc/screenshot phải hoàn toàn giả.
- Thay đổi public behavior phải cập nhật VI và EN.
- Không thêm dependency `latest`.
- Không làm yếu source boundary, secret gate, citation gate hoặc migration.
- Chạy skill validator, manifest validator, runtime/portable tests, MCP
  handshake, docs link/build và license audit trước pull request.

Xem [CONTRIBUTING.md](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/CONTRIBUTING.md)
và [release checklist](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/docs/RELEASE_CHECKLIST.md).
