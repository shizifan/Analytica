# Analytica Docker 离线部署指南

## 前置条件

- **操作系统**: 麒麟 Server V10 (aarch64) 或其他 Linux arm64 发行版
- **Docker Engine**: >= 20.10
- **Docker Compose**: v2 (docker compose 插件)
- **磁盘空间**: >= 2GB (镜像 + MySQL 数据)
- **内存**: >= 4GB (推荐)

## 部署步骤

### 1. 传输部署包

将 `analytica-docker-YYYYMMDD.tar.gz` 传输到目标服务器：

```bash
scp analytica-docker-YYYYMMDD.tar.gz user@server:/opt/
```

### 2. 解压

```bash
cd /opt
tar xzf analytica-docker-YYYYMMDD.tar.gz
cd analytica-docker-YYYYMMDD
```

### 3. 配置环境变量

编辑 `.env` 文件，根据实际环境调整以下配置：

```bash
vi .env
```

重要配置项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码 | `analytica_2026` |
| `QWEN_API_KEY` | 大模型 API Key | 需替换 |
| `QWEN_API_BASE` | 大模型 API 地址 | `https://opensseapi.cmft.com/...` |
| `PROD_API_BASE` | 生产数据 API 网关 (测试用) | `https://10.29.212.24:81` |
| `MOCK_SERVER_URL` | Mock Server 地址 | `http://localhost:18080` |
| `ANALYTICA_PORT` | 应用端口 | `8000` |
| `WORKERS` | Uvicorn 工作进程数 | `2` |

### 4. 一键部署

```bash
bash deploy.sh
```

脚本会自动完成：
1. 加载 Docker 镜像 (analytica + MySQL)
2. 检查 .env 配置
3. 启动 docker compose 服务
4. 等待健康检查通过

### 5. 验证

```bash
curl http://localhost:8000/health
# 应返回: {"status":"ok","service":"analytica"}
```

## 常用运维命令

```bash
# 查看服务状态
docker compose ps

# 查看应用日志
docker compose logs -f app

# 查看 MySQL 日志
docker compose logs -f db

# 停止服务
docker compose down

# 停止服务并删除数据（慎用）
docker compose down -v

# 重启应用（不重启 MySQL）
docker compose restart app
```

## 数据备份与恢复

### 备份 MySQL

```bash
docker compose exec db mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" analytica > backup_$(date +%Y%m%d).sql
```

### 恢复 MySQL

```bash
docker compose exec -T db mysql -u root -p"$MYSQL_ROOT_PASSWORD" analytica < backup_YYYYMMDD.sql
```

## 常见问题

### Q: 应用启动失败，提示连接 MySQL 超时

MySQL 首次启动需要初始化数据（约 20-30 秒），应用会自动重试。如果持续失败：

```bash
# 检查 MySQL 状态
docker compose logs db

# 确认 MySQL 健康
docker compose ps  # db 服务应显示 (healthy)
```

### Q: 端口 8000 被占用

修改 `.env` 中的 `ANALYTICA_PORT`：

```env
ANALYTICA_PORT=8080
```

然后重启：`docker compose up -d`

### Q: 如何升级应用

1. 获取新的部署包
2. 加载新镜像: `docker load -i images/analytica-app.tar.gz`
3. 重启应用: `docker compose up -d app`

MySQL 数据保存在 named volume 中，升级应用不会丢失数据。

### Q: 磁盘空间不足

```bash
# 查看 Docker 磁盘使用
docker system df

# 清理无用镜像（不影响运行中的容器）
docker image prune
```
