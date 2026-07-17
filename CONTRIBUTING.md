# 贡献指南 · Contributing

感谢你对本项目的关注!欢迎通过 Issue 和 Pull Request 参与改进。

## 🔒 安全第一(最重要)

**请勿在任何提交、Issue、PR、日志或截图中包含真实敏感数据**,包括但不限于:
- 账号、密码
- Cookie、access_token、device_token、refresh_token
- 代理地址与凭据
- 数据库文件(`*.db`)、`.env`、导出的账号 JSON

提交前请确认这些文件已被 `.gitignore` 忽略。若不慎泄露,请立即轮换相关凭据。

## 🐛 提交 Issue

- 先搜索是否已有相同问题。
- 清晰描述:复现步骤、期望结果、实际结果、运行环境(OS / Python / Node 版本)。
- 贴日志时**务必脱敏**。

## 🔧 提交 Pull Request

1. Fork 本仓库并基于 `main` 创建特性分支:`git checkout -b feat/your-feature`。
2. 保持改动聚焦单一主题,避免无关的大范围格式化。
3. 提交信息建议遵循约定式提交:`feat:` / `fix:` / `docs:` / `refactor:` / `chore:`。
4. 提交前请自测:
   - 后端:`python -m uvicorn app.main:app` 可正常启动;
   - 前端:`npx vue-tsc -b` 类型检查通过、`npm run dev` 可运行。
5. 在 PR 描述中说明**动机、改动内容与测试方式**。

## 💻 开发约定

- **后端**:遵循 FastAPI + SQLAlchemy 2.0 风格;数据库结构变更请在 `db/init_db.py` 的迁移中补齐。
- **前端**:TypeScript 严格模式,组件使用 `<script setup>`;接口封装集中在 `src/api/`。
- 注释解释「为什么」,而非复述代码「做了什么」。

## 📄 协议

提交贡献即表示你同意你的代码以本项目的 [MIT License](./LICENSE) 授权发布,并已阅读 [免责声明](./DISCLAIMER.md)。
