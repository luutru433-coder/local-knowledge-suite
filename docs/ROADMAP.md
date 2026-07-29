# Roadmap

## Current support

Local Knowledge Suite v1 supports native Windows 10 and 11 with PowerShell
5.1+, Python 3.12, and the Windows credential and path model. macOS, Linux, and
WSL are not supported release targets for v1.

## Planned platform work

macOS and Linux support are planned, but there is no promised date or release.
The project will not label either platform supported until these areas have
production tests and documented migration behavior:

- replace Windows Credential Manager assumptions with Keychain/libsecret
  adapters and define safe fallback behavior;
- implement native shell launchers and path/reparse-point equivalents;
- validate permissions, file locking, atomic replacement, process handling, and
  local registry locations;
- add macOS and Linux CI for runtime, MCP, portal, Skills, migration, source
  boundaries, and clean-machine installation; and
- document cross-platform company registration and Memory transfer without
  weakening project/company isolation.

WSL needs a separate design decision because mixed Windows/Linux paths and
credential stores can violate the current boundary assumptions.

Community contributions may help, but this roadmap is directional rather than
a delivery commitment. Track proposals in
[GitHub Issues](https://github.com/luutru433-coder/local-knowledge-suite/issues).

---

## Lộ trình tiếng Việt

Bản v1 chỉ hỗ trợ Windows 10/11 native. macOS, Linux và WSL chưa phải nền tảng
được hỗ trợ.

Dự án có kế hoạch hỗ trợ macOS/Linux trong tương lai nhưng chưa cam kết ngày
phát hành. Trước khi công bố hỗ trợ, cần hoàn thành:

- adapter cho macOS Keychain và Linux secret service;
- launcher, đường dẫn và kiểm tra symlink native;
- kiểm thử permission, file lock, ghi file atomic và process;
- CI đầy đủ trên macOS/Linux; và
- tài liệu chuyển company/Memory giữa các nền tảng mà không làm yếu ranh giới
  dữ liệu.

WSL cần thiết kế riêng vì đường dẫn và credential store trộn giữa Windows và
Linux. Roadmap này là định hướng, không phải cam kết thời gian.
