# 常见问题与故障排除

---

## 安装问题

### Q: Python 版本不兼容

**症状：** `pip install` 报错或运行时报语法错误

**解决：**
```bash
# 检查 Python 版本
python --version

# 需要 Python 3.11 或 3.12
# 如果版本过低，请升级 Python
```

### Q: Node.js 版本不兼容

**症状：** `npm install` 报错或前端无法启动

**解决：**
```bash
# 检查 Node.js 版本
node --version

# 需要 18 或更高版本
# 如果版本过低，请升级 Node.js
```

### Q: 依赖安装失败

**症状：** `pip install` 或 `npm install` 报错

**解决：**
```bash
# 清除缓存重试
pip cache purge
pip install -e .

# 或
npm cache clean --force
cd apps/web && npm install
```

---

## 启动问题

### Q: 端口被占用

**症状：** `Address already in use` 错误

**解决：**
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# macOS/Linux
lsof -i :8000
kill -9 <PID>
```

### Q: 后端启动失败

**症状：** API 无法访问

**检查：**
1. 查看日志：`data/logs/`
2. 检查 `.env` 配置
3. 检查依赖是否完整

**解决：**
```bash
# 重新安装依赖
pip install -e .

# 手动启动查看错误
uvicorn backend.api.main:app --port 8000
```

### Q: 前端启动失败

**症状：** 页面无法访问

**检查：**
1. 查看终端错误信息
2. 检查 `apps/web/node_modules/` 是否存在

**解决：**
```bash
cd apps/web
npm install
npm run dev
```

---

## 配置问题

### Q: API Key 无效

**症状：** 测试连接失败

**检查：**
1. API Key 是否正确复制
2. 是否有多余空格
3. 账户余额是否充足

**解决：**
1. 重新获取 API Key
2. 确保无空格和换行
3. 测试连接验证

### Q: 数据源不可用

**症状：** 数据源健康页面显示红色

**检查：**
1. 网络连接是否正常
2. API Key 是否配置
3. 是否触发频率限制

**解决：**
1. 检查网络
2. 配置 API Key
3. 等待几分钟重试

---

## 使用问题

### Q: 分析超时

**症状：** 长时间无响应

**原因：**
- LLM API 响应慢
- 网络不稳定
- 并发请求过多

**解决：**
1. 检查网络连接
2. 减少并发分析数量
3. 使用标准模式（更快）

### Q: 分析结果不准确

**症状：** 结论与预期不符

**原因：**
- 数据源数据不完整
- 模型理解偏差
- 股票特殊性

**解决：**
1. 检查数据源是否可用
2. 使用深入模式（更全面）
3. 参考多位专家意见
4. 结合其他信息源验证

### Q: 报告生成失败

**症状：** 点击生成报告无响应

**检查：**
1. 分析是否完成
2. 查看错误提示

**解决：**
1. 等待分析完成
2. 重新运行分析
3. 检查日志

---

## 性能问题

### Q: 响应速度慢

**原因：**
- 使用高质量模型（如 Claude Opus）
- 网络延迟
- 数据源响应慢

**解决：**
1. 使用标准模式
2. 使用低成本模型（如 DeepSeek）
3. 检查网络连接
4. 启用缓存

### Q: 内存占用高

**原因：**
- 缓存数据过多
- 并发分析过多

**解决：**
1. 清除缓存：`data/cache/`
2. 减少并发分析
3. 重启服务

---

## 日志与诊断

### 查看日志

```bash
# 查看后端日志
tail -f data/logs/backend.log

# 查看错误日志
grep -i error data/logs/*.log
```

### 诊断 API

```bash
# 健康检查
curl http://localhost:8000/health

# 数据源状态
curl http://localhost:8000/api/providers/health

# 成本统计
curl http://localhost:8000/api/costs
```

### 导出错误报告

1. 点击左侧 **诊断**
2. 点击 **导出错误报告**
3. 保存报告文件
4. 提交到 GitHub Issues

---

## 重置与恢复

### 重置配置

```bash
# 删除配置文件
rm .env

# 重新初始化
python scripts/init_local.py
```

### 重置数据

```bash
# 备份
python scripts/backup_local.py

# 删除数据目录
rm -rf data/

# 重新初始化
python scripts/init_local.py
```

### 恢复数据

```bash
# 从备份恢复
python scripts/restore_local.py backup/
```

---

## 获取帮助

### GitHub Issues

1. 访问 [GitHub Issues](https://github.com/TIANWEN-cpu/AlphaScope/issues)
2. 搜索已有问题
3. 创建新 Issue

### 提交 Issue 时请包含

1. 操作系统和版本
2. Python 和 Node.js 版本
3. 错误信息或日志
4. 复现步骤
5. 预期行为

---

## 下一步

- [安装指南](01-installation.md) - 重新安装
- [快速开始](02-quickstart.md) - 快速上手
- [模型接入配置](03-model-config.md) - 配置 LLM
