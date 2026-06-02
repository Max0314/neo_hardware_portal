# 自托管静态资源

构建时由 `npm run sync-vendor`（或 `vite build` 自动调用）从 `node_modules` 复制：

- `xlsx.full.min.js` ← `xlsx`
- `fontawesome/css`、`fontawesome/webfonts` ← `@fortawesome/fontawesome-free`

首次开发请执行：`npm install && npm run sync-vendor`
