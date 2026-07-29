// SPDX-License-Identifier: MIT
// Copyright (c) 2026 John-IDK

import { defineConfig } from "vitepress";

const viSidebar = [
  {
    text: "Bắt đầu",
    items: [
      { text: "Cài đặt nhanh", link: "/guide/getting-started" },
      { text: "Skill, MCP và dữ liệu", link: "/guide/concepts" },
      { text: "Global và vendored", link: "/guide/install-modes" }
    ]
  },
  {
    text: "Sử dụng",
    items: [
      { text: "Kiến thức công ty", link: "/guide/company" },
      { text: "Nhiều project", link: "/guide/multi-project" },
      { text: "Chuyển Memory", link: "/guide/memory-snapshots" },
      { text: "Chuyển máy Windows", link: "/guide/migration" }
    ]
  },
  {
    text: "Trợ giúp",
    items: [
      { text: "Sửa lỗi", link: "/guide/troubleshooting" },
      { text: "Gỡ cài đặt", link: "/guide/uninstall" },
      { text: "CLI và MCP", link: "/reference/cli-mcp" },
      { text: "Riêng tư và bảo mật", link: "/reference/privacy-security" },
      { text: "Phân phối và thương mại", link: "/guide/distribution" },
      { text: "Phát triển", link: "/development" }
    ]
  }
];

const enSidebar = [
  {
    text: "Start",
    items: [
      { text: "Quick installation", link: "/en/guide/getting-started" },
      { text: "Skills, MCP, and data", link: "/en/guide/concepts" },
      { text: "Global and vendored", link: "/en/guide/install-modes" }
    ]
  },
  {
    text: "Use",
    items: [
      { text: "Company knowledge", link: "/en/guide/company" },
      { text: "Multiple projects", link: "/en/guide/multi-project" },
      { text: "Move Memory", link: "/en/guide/memory-snapshots" },
      { text: "Move to a new PC", link: "/en/guide/migration" }
    ]
  },
  {
    text: "Help",
    items: [
      { text: "Troubleshooting", link: "/en/guide/troubleshooting" },
      { text: "Uninstall", link: "/en/guide/uninstall" },
      { text: "CLI and MCP", link: "/en/reference/cli-mcp" },
      { text: "Privacy and security", link: "/en/reference/privacy-security" },
      { text: "Distribution and commercial use", link: "/en/guide/distribution" },
      { text: "Development", link: "/en/development" }
    ]
  }
];

const sharedThemeConfig = {
  logo: "/logo.svg",
  search: {
    provider: "local" as const,
    options: {
      locales: {
        root: {
          translations: {
            button: { buttonText: "Tìm kiếm", buttonAriaLabel: "Tìm kiếm" },
            modal: {
              noResultsText: "Không tìm thấy kết quả",
              resetButtonTitle: "Xóa tìm kiếm",
              footer: {
                selectText: "để chọn",
                navigateText: "để di chuyển",
                closeText: "để đóng"
              }
            }
          }
        }
      }
    }
  },
  socialLinks: [
    { icon: "github" as const, link: "https://github.com/luutru433-coder/local-knowledge-suite" }
  ]
};

export default defineConfig({
  title: "Local Knowledge Suite",
  description: "Project Memory and cited company knowledge for Codex",
  lang: "vi-VN",
  base: "/local-knowledge-suite/",
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ["meta", { name: "theme-color", content: "#10231f" }],
    ["meta", { name: "color-scheme", content: "light dark" }]
  ],
  locales: {
    root: {
      label: "Tiếng Việt",
      lang: "vi-VN",
      title: "Local Knowledge Suite",
      description: "Memory theo project và kiến thức công ty có trích dẫn",
      themeConfig: {
        ...sharedThemeConfig,
        nav: [
          { text: "Hướng dẫn", link: "/guide/getting-started" },
          { text: "Tham chiếu", link: "/reference/cli-mcp" },
          { text: "GitHub", link: "https://github.com/luutru433-coder/local-knowledge-suite" }
        ],
        sidebar: viSidebar,
        editLink: {
          pattern: "https://github.com/luutru433-coder/local-knowledge-suite/edit/main/docs-site/:path",
          text: "Sửa trang này trên GitHub"
        },
        footer: {
          message: "Phát hành theo MIT License.",
          copyright: "Copyright © 2026 John-IDK"
        },
        docFooter: { prev: "Trang trước", next: "Trang sau" },
        lastUpdated: { text: "Cập nhật lần cuối" },
        outline: { label: "Trong trang" }
      }
    },
    en: {
      label: "English",
      lang: "en-US",
      link: "/en/",
      title: "Local Knowledge Suite",
      description: "Project Memory and cited company knowledge",
      themeConfig: {
        ...sharedThemeConfig,
        nav: [
          { text: "Guide", link: "/en/guide/getting-started" },
          { text: "Reference", link: "/en/reference/cli-mcp" },
          { text: "GitHub", link: "https://github.com/luutru433-coder/local-knowledge-suite" }
        ],
        sidebar: enSidebar,
        editLink: {
          pattern: "https://github.com/luutru433-coder/local-knowledge-suite/edit/main/docs-site/:path",
          text: "Edit this page on GitHub"
        },
        footer: {
          message: "Released under the MIT License.",
          copyright: "Copyright © 2026 John-IDK"
        },
        docFooter: { prev: "Previous page", next: "Next page" },
        lastUpdated: { text: "Last updated" },
        outline: { label: "On this page" }
      }
    }
  },
  markdown: {
    lineNumbers: true
  }
});
