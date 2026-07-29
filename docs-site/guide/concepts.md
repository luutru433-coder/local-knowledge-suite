# Skill, MCP và dữ liệu

## Skill là gì?

Skill là hướng dẫn làm việc cho Codex. Nó giống checklist của nhân viên:

- kiểm tra gì trước;
- gọi công cụ nào;
- kết quả nào đủ an toàn để dùng; và
- khi nào phải dừng, báo lỗi hoặc hỏi người dùng.

Plugin có ba skill:

| Skill | Việc chính |
| --- | --- |
| `manage-local-knowledge` | Chọn đúng luồng, khởi tạo, kiểm tra và tìm lại. |
| `memorizer` | Ghi nhớ, sửa, tìm và bảo trì Memory của một project. |
| `company-knowledge-base` | Ingest, review, tìm và xuất bản kiến thức công ty có trích dẫn. |

Skill không phải dữ liệu công ty và cũng không phải lịch sử cuộc trò chuyện.

## MCP là gì?

MCP là cách Codex gọi những hàm ổn định của plugin. Hãy tưởng tượng bốn nút:

1. `bootstrap_workspace`: tạo cấu trúc project nếu chưa có;
2. `knowledge_status`: kiểm tra có khỏe và tương thích không;
3. `recall_context`: tìm thông tin theo từng nhóm;
4. `capture_memory`: ghi một Memory bền vững.

So với nhập thủ công, MCP:

- giảm lỗi gõ đường dẫn, profile và định dạng;
- tự kiểm tra project/company có đúng không;
- trả kết quả có trường rõ ràng để Codex không trộn nguồn;
- chống ghi trùng bằng ID ổn định; và
- kiểm tra dữ liệu nhạy cảm, distillation và citation gate.

MCP không tự hiểu một tài liệu sai, không thay người review, và không làm Git
trở thành bằng chứng nguồn.

## Ba lớp không được trộn

| Lớp | Chứa gì | Phạm vi |
| --- | --- | --- |
| Skill | Quy trình và quy tắc | Plugin |
| Memory | Sở thích, quyết định, quy ước | Một project |
| Company Knowledge | Sự thật công ty có bằng chứng | Một công ty, nhiều project |

Ví dụ:

- “Project này dùng REST” là Memory.
- “Bảo hành xe là 24 tháng” phải đến từ Company Knowledge có trích dẫn.
- “Tìm trước khi ghi” là quy tắc trong skill.

Không dùng Memory để chứng minh chính sách công ty. Không dùng nội dung skill
để thay dữ liệu đã mất.

## Ba profile

- `memory-only`: chỉ Memory; không cần company và là mặc định.
- `combined`: Memory riêng + Company Knowledge; bắt buộc `company_id`.
- `company-only`: chỉ Company Knowledge; bắt buộc `company_id`.

Không sửa profile hoặc `company_id` bằng tay để đổi danh tính. Dùng migration
hoặc khởi tạo đúng ngay từ đầu.
