# AdobeTeam · Adobe 账号批量管理平台

> 基于 **FastAPI + Vue3** 的 Adobe 账号自动化管理平台:批量登录、令牌刷新、号池管理、邮箱验证码收取、积分检测与出图测试一体化。

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white">
  <img alt="Vue3" src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-yellow.svg">
</p>

---

## ⚠️ 重要声明

本项目**仅供个人学习、研究与技术交流使用**,用于探讨 Web 自动化、协议分析与全栈开发。请在使用前务必阅读并同意 [免责声明 DISCLAIMER.md](./DISCLAIMER.md)。

**下载、克隆或使用本项目,即视为你已完整阅读并接受免责声明的全部条款。**

---

## 📋 目录

- [功能特性](#-功能特性)
- [技术栈](#-技术栈)
- [目录结构](#-目录结构)
- [快速开始](#-快速开始)
- [配置说明](#-配置说明)
- [功能使用详解](#-功能使用详解)
- [常见问题](#-常见问题)
- [技术交流](#-技术交流)
- [贡献指南](#-贡献指南)
- [开源协议](#-开源协议)

---

## ✨ 功能特性

### 账号管理
- **批量导入**:支持 `邮箱----密码----ClientID----RefreshToken` 等多种文本/JSON 格式,自动智能解析。
- **母号(管理控制台)**:登录获取管理员权限、检测有效性、管理子账号(成员)。
- **一键拉号**:指定母号自动凑满 N 个已注册子号,支持多母号并发批量拉号,任务进度实时可见。

### 号池(核心)
- **协议登录 / 令牌刷新**:复刻 FF-iOS 原生登录流程,`邮箱 + 密码 + 邮箱验证码` 换取受信任的 `access_token` + `device_token`(约 1 年有效,可免验证码续期)。
- **批量并发**:线程池并发登录/刷新,任务化管理,单账号进度与日志可追溯。
- **积分检测**:查询账号 Firefly 积分与出图权限(entitlement)。
- **出图测试**:直接调用 Firefly 3P 接口验证账号能否正常生成图片。
- **多格式导出**:一键导出为可直接导入下游系统的 JSON / 纯 Cookie / 纯 Token 格式,导出格式可在设置中配置默认值。

### 邮箱与验证码
- **多渠道收信**:支持 Microsoft Graph API、IMAP(XOAUTH2)、以及第三方取信接口(如 MoeMail 等)。
- **OTP 自动提取**:登录流程自动轮询邮箱、提取 6 位验证码。
- **一键创建临时邮箱**:对接 MoeMail 批量生成邮箱并导入。
- **在线测试收件**:单账号一键测试收信配置是否可用。

### 系统能力
- **代理池**:多代理逐行轮换(round-robin),支持 HTTP / SOCKS5,连通性一键检测。
- **可配置**:并发线程数、请求超时、注册地区/语言、默认导出格式等。
- **运行日志**:统一日志中心,按级别/关键字筛选。
- **JWT 鉴权**:后台登录鉴权,支持修改管理员密码。

---

## 🧰 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI · SQLAlchemy 2.0 · SQLite · Pydantic v2 · JWT(python-jose)· curl_cffi |
| 前端 | Vue 3 · Vite · TypeScript · Naive UI · Pinia · Vue Router · Axios |
| 其他 | ThreadPoolExecutor 并发 · Playwright(ARP 捕获,可选) |

---

## 📁 目录结构

```
adobeteam/
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── api/routes/          # 路由:auth / adobe_account / email / pool / setting / log
│   │   ├── core/                # 配置、安全(JWT、密码哈希)
│   │   ├── crud/                # 数据库操作
│   │   ├── db/                  # 会话、建表与迁移
│   │   ├── models/              # ORM 模型
│   │   ├── schemas/             # Pydantic 模型
│   │   ├── services/            # 核心业务:协议登录、Firefly、OTP、代理池等
│   │   └── main.py              # 入口
│   ├── tools/                   # 命令行工具(cookie 转换、积分批量检测等)
│   ├── .env.example             # 环境变量示例
│   └── requirements.txt
├── frontend/                    # Vue3 前端
│   └── src/
│       ├── api/                 # 接口封装
│       ├── stores/              # Pinia 状态
│       ├── router/              # 路由与守卫
│       ├── components/          # 通用组件
│       └── views/               # 页面:登录 / Adobe账号 / 邮箱 / 号池 / 任务 / 设置 / 日志
├── dev-watchdog.ps1             # 本地开发看门狗(自动重启前后端)
├── README.md
├── DISCLAIMER.md                # 免责声明
├── CONTRIBUTING.md              # 贡献指南
└── LICENSE
```

---

## 🚀 快速开始

### 环境要求

- Python **3.10+**
- Node.js **18+**

### 1. 克隆项目

```bash
git clone https://github.com/432539/adobeteam.git
cd adobeteam
```

### 2. 启动后端(端口 8000)

```bash
cd backend
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt

# 复制并按需修改环境变量
copy .env.example .env      # Windows
# cp .env.example .env      # macOS / Linux

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- API 文档:http://127.0.0.1:8000/docs
- 首次启动会自动建表并创建默认管理员。

### 3. 启动前端(端口 5205)

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5205
```

打开 http://localhost:5205,使用默认账号登录。

### 4.（可选）本地看门狗

Windows 下可用看门狗脚本同时守护前后端,任一端口挂掉自动重启:

```powershell
powershell -ExecutionPolicy Bypass -File .\dev-watchdog.ps1
```

### Docker Compose 启动

已提供生产模式的 Docker Compose 配置，包含 FastAPI 后端、Nginx 前端和持久化 SQLite 数据目录。

```bash
# 首次启动或代码更新后重新构建
docker compose up -d --build

# 查看服务日志
docker compose logs -f
```

启动后访问 http://localhost/team/，API 文档访问 http://localhost/team/api/docs。
数据库文件会保存在项目根目录的 `data/app.db`。如果项目原来使用 `backend/app.db`，首次启动时会自动复制到 `data/app.db`，原文件不会删除；之后以 `data/app.db` 为准。Compose 会读取 `backend/.env`，请先按需修改其中的密钥和默认管理员配置。

---

## ⚙️ 配置说明

### 默认管理员

| 用户名 | 密码 |
|--------|------|
| admin | admin123 |

> **生产环境务必修改**:通过 `backend/.env` 覆盖 `SECRET_KEY` 与默认管理员密码,或登录后在「设置 → 修改密码」中更改。

### 环境变量(`backend/.env`)

```ini
SECRET_KEY=please-change-this-to-a-long-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# 默认管理员账号(仅首次初始化生效)
FIRST_ADMIN_USERNAME=admin
FIRST_ADMIN_PASSWORD=admin123
FIRST_ADMIN_NICKNAME=超级管理员
```

### 系统设置(登录后在「设置」页配置)

| 项 | 说明 |
|----|------|
| 启用代理 / 代理地址 | 一行一个代理,外呼时轮换出口 IP;支持 `user:pass@host:port`、`http://...`、`socks5://...` |
| 并发线程数 | 批量登录/刷新的并发度 |
| 请求超时 | 单次请求超时时间(秒) |
| 注册地区 / 语言 | 注册/补全账号使用的国家与 locale(建议 SG,US 易被地区灰度拦截) |
| 导出默认格式 | 号池「导出(按设置)」使用的格式:FF-iOS Token / 纯 Cookie |

---

## 📖 功能使用详解

### 一、导入账号 / 邮箱
在「号池」或「邮箱管理」页点击「导入」,粘贴文本或 JSON。支持格式示例:

```
邮箱----密码----ClientID----RefreshToken
邮箱|密码|RefreshToken|ClientID
```

也支持直接粘贴含 `access_token` / `device_token` / `cookie` 的 JSON 数组,系统自动识别入库。

### 二、批量协议登录 / 刷新令牌
在「号池」选中账号或按筛选条件批量执行「批量协议登录」。系统会:
1. 用邮箱 + 密码走 FF-iOS 登录;
2. 自动收取邮箱验证码(OTP);
3. 换取 `access_token` + `device_token` 并入库;
4. 后续可用 `device_token` 免验证码刷新 `access_token`。

进度可在「拉号任务 / 任务列表」页实时查看,单账号成功/失败原因均有日志。

### 三、积分检测与出图测试
- 「刷新AT并查额度」:刷新令牌并查询积分。
- 「测试出图」:调用 Firefly 3P 接口实际生成一张图片,验证账号可用性与出图权限。

> 注:显示有积分 ≠ 能出第三方模型图。部分账号对 premium 第三方模型(如 nano-banana / gpt-image)无 entitlement 权限,出图会被拦截。

### 四、导出
「号池」页支持导出:
- **导出(按设置)**:按「设置 → 导出默认格式」输出;
- **newbanana(JSON)**:`[{ cookie, name, access_token, device_token, credits, expires_at }]`;
- **纯 Cookie** / **纯 Token**。

### 五、命令行工具(`backend/tools/`)
| 工具 | 用途 |
|------|------|
| `cookie_to_ff_ios_token.py` | 将浏览器 Cookie 转换为 FF-iOS 的 access_token + device_token |
| `batch_check_credits.py` | 批量检测多个文件中账号的积分 / 令牌状态 |
| `okad_to_adobeall.py` | 将导出格式转换为下游系统所需的 adobe-all 格式 |

各工具均支持 `-h` 查看参数。

---

## ❓ 常见问题

- **验证码收不到?** 检查邮箱 OAuth 权限(IMAP/Graph 需授权对应 scope);Microsoft 账号建议配置多渠道取信或第三方取信接口。
- **一直 408 / system under load?** 通常是出图接口的反爬头未通过,或账号无 premium 模型权限,或出口 IP 被限流(尝试切换代理)。
- **US 区注册被拦?** 改用 SG 等地区。
- **前端打不开?** 确认端口未被占用,或使用 `dev-watchdog.ps1` 自动守护。

---

## 💬 技术交流

- **QQ 交流群:19302577**

欢迎加群交流全栈开发、Web 自动化、协议分析等技术话题。提问前请先阅读本文档与免责声明。

---

## 🤝 贡献指南

欢迎 Issue 与 Pull Request。提交前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)。

**请勿在 Issue、PR 或任何提交中包含真实账号、密码、Cookie、Token 等敏感数据。**

---

## 📄 开源协议

本项目基于 [MIT License](./LICENSE) 开源。

使用本项目须遵守 [免责声明](./DISCLAIMER.md);因使用本项目产生的一切后果由使用者自行承担。
