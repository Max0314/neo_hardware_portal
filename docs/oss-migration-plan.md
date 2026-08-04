# OSS 接入前置与迁移关卡

当前栈仍使用本地 Docker 卷。此文档只定义 OSS 上线前的准备和切换关卡；**配置
OSS 变量本身不会启用 OSS，也不会移动或删除任何数据**。

## 范围

第一批迁移对象是二进制文件，不包括数据库：

| 本地位置 | 内容 | OSS 目标前缀 |
| --- | --- | --- |
| `htmlsystm_data` | 公告正文、元数据、历史版本及兼容文件 | `announcements/` |
| `htmlsystm_uploads` | 管理系统上传文件 | `uploads/` |
| `ai_chatroom_data` | 聊天附件、知识库源文件 | `neo-files/` |
| `mysql_data` | 业务数据库 | **不迁移到 OSS**；迁往共享数据库 |

`chatroom.db`、指标 SQLite 和向量索引同样不是 OSS 对象；它们需要单独迁入共享
数据库或向量服务后才能取消本地数据卷。

## 配置契约

在服务器私有 `.env` 中准备以下变量，切勿提交 AccessKey：

```dotenv
STORAGE_BACKEND=local
OSS_ENDPOINT=https://oss-cn-<region>-internal.aliyuncs.com
OSS_REGION=cn-<region>
OSS_BUCKET=<private-bucket>
OSS_PREFIX=neo-hardware
OSS_CREDENTIAL_MODE=ram_role
```

存储桶必须保持私有。服务端经 RAM 角色或短期 STS 凭据访问对象；浏览器下载继续
经业务接口鉴权，或由服务端按用户权限签发短时下载 URL。不要把永久 AK、签名 URL
或桶设为公共读写。

运行下面的只读检查确认配置完整：

```bash
bash migration/check-oss-readiness.sh --require-oss
```

该脚本不会联网、上传、删除或修改 Compose。

## 切换流程

1. 关闭写入窗口，执行完整 MySQL 和四个数据卷备份；记录备份哈希和时间。
2. 为三个文件目录生成对象清单：相对路径、字节数、SHA-256、MIME 类型和归属公告/用户。
3. 创建 RAM 最小权限：仅允许指定 bucket 与 `OSS_PREFIX` 下的 `GetObject`、`PutObject`、`HeadObject`、分片上传所需权限；禁止 `DeleteBucket` 与无前缀的写权限。
4. 在测试桶进行一次全量复制，并逐对象比对数量、大小与 SHA-256。失败对象不得跳过。
5. 部署“OSS 写入 + 本地回退读取”的代码，先灰度写入少量新附件；下载、历史版本、权限校验和审计均需通过。
6. 复制生产历史对象并复核；只有全部对象可从 OSS 读取后，才切换为 OSS 优先读取。
7. 保留本地卷和可恢复备份至少一个业务观察周期；确认无回退读取后，再获得单独授权清理。

## 回滚

任何校验失败都把 `STORAGE_BACKEND` 保持为 `local`，并从已验证的本地卷读取。
切换后如出现下载、权限或完整性异常，立即回退到本地优先读取；不得在未验证对象清单
前删除本地文件或 OSS 对象。

阿里云 OSS Python SDK V2 需要 Python 3.8+，本项目的 `htmlsystm` 镜像为 Python
3.11，满足该前提。正式接入时使用官方 SDK 的环境凭据/角色凭据，不在代码中保存密钥。
