# Docker 数据持久化调整（2026-05-14）

## 背景

排查登录失败时发现当前 SeekDB 业务库为空：`users`、`knowledge_bases`、
`documents`、`knowledge_chunks_v2`、`chat_sessions` 均为 0。日志显示登录接口先
返回 401，随后触发 Redis 登录失败限流 429。

本次排查确认 `seekdb` 进程实际使用 `--base-dir=/var/lib/oceanbase`，旧 Compose
已将 named volume `ragproject3_seekdb-data` 挂载到该目录，后端重启/API 重建不会
主动清空数据库。为降低后续因 Compose project 名变化、误创建新 named volume 或
误用 volume 参数造成的数据漂移风险，改为项目目录固定 bind mount。

## 当前持久化目录

Compose 默认使用以下宿主机目录：

| 数据 | 宿主机目录 | 容器目录 |
| --- | --- | --- |
| SeekDB/OceanBase 数据 | `./data/seekdb` | `/var/lib/oceanbase` |
| Redis AOF 数据 | `./data/redis` | `/data` |
| 后端上传/导出文件 | `./uploads` | `/app/backend/uploads` |

这些目录已加入 `.gitignore`，只作为运行时数据保存，不应提交到 Git。

## 环境变量

可通过 `.env` 覆盖目录：

```env
SEEKDB_DATA_DIR=./data/seekdb
REDIS_DATA_DIR=./data/redis
BACKEND_UPLOADS_DIR=./uploads
```

## 已执行迁移

停止后端、Redis、SeekDB 服务后，将旧 named volume 内容复制到固定目录：

- `ragproject3_seekdb-data` → `./data/seekdb`
- `ragproject3_redis-data` → `./data/redis`
- `ragproject3_uploads-data` → `./uploads`

随后执行 `docker compose up -d`，容器已切换为 bind mount。旧 named volume 未删除，
可作为临时回退来源保留。

## 验证

- `docker compose config --quiet` 通过。
- `seekdb` mount：`/home/ubuntu/jiang/ragproject3/data/seekdb` → `/var/lib/oceanbase`。
- `redis` mount：`/home/ubuntu/jiang/ragproject3/data/redis` → `/data`。
- `api` mount：`/home/ubuntu/jiang/ragproject3/uploads` → `/app/backend/uploads`。
- `GET /healthz` 返回 `{"status":"ok"}`。

## 运维注意

- 不要执行会删除 volume 或运行时目录的命令，例如 `docker compose down -v`。
- 备份时优先备份 `data/seekdb`、`data/redis`、`uploads`。
- 需要迁移机器时，应先停服务，再复制上述目录，最后启动 Compose。
