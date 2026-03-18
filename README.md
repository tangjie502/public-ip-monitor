# Public IP Monitor

一个适合部署到家用 NAS 的 Docker 项目，用于定时检测公网 IP 是否变动；发生变动时通过 SMTP 邮件或消息推送助手通知，并提供网页查看历史变动日志。SMTP 和消息推送都可直接在页面配置并发送测试消息。

## 功能

- 定时轮询公网 IP 查询服务，自动容错，默认使用 `http://cip.cc`
- 首次启动记录当前公网 IP，后续检测到变化时发送通知
- SQLite / MySQL 持久化 IP 变动记录
- Web 页面展示当前公网 IP、最近检查状态和变动日志
- 公网变动日志支持分页查看，并可一键导出全部 CSV
- 页面内配置 SMTP 和消息推送助手，并可发送测试通知
- Docker / Docker Compose 一键部署

## 技术栈

- FastAPI
- SQLite / MySQL
- Jinja2
- Docker Compose

## 快速开始

1. 默认的 `docker-compose.yml` 只启动 `public-ip-monitor`，用于连接外部 MySQL。
   先基于 `.env.example` 创建 `.env`，填写你的外部 MySQL 地址和账号：

   ```bash
   cp .env.example .env
   ```

2. 如需修改基础配置，可编辑 `docker-compose.yml` 里的 `environment`，例如：

   ```yaml
   environment:
     BASE_URL: http://你的NAS地址:8000
     TIMEZONE_LABEL: Asia/Shanghai
     MYSQL_HOST: mysql
     MYSQL_PORT: 3306
   ```

   例如你的 `.env` 可以这样写：

   ```env
   MYSQL_HOST=192.168.1.100
   MYSQL_PORT=3306
   MYSQL_DATABASE=public_ip_monitor
   MYSQL_USER=public_ip_monitor
   MYSQL_PASSWORD=your_password
   MYSQL_ROOT_PASSWORD=unused_when_using_external_mysql
   ```

3. 启动服务：

   ```bash
   docker compose up -d --build
   ```

4. 打开页面：

   - 日志页面：`http://你的NAS地址:8000/`
   - 健康检查：`http://你的NAS地址:8000/healthz`
   - 状态接口：`http://你的NAS地址:8000/api/status`

5. 进入页面后，可在“邮件配置”和“消息推送助手”区域分别填写参数并发送测试通知。
6. 需要导出日志时，点击日志区域右上角“导出全部 CSV”。

## 数据库配置

当前仓库中的 `docker-compose.yml` 和 `docker-compose.nas.yml` 默认都用于连接外部 MySQL，不会自动启动内置 MySQL。

如果你想改回 SQLite，清空 `DATABASE_URL`，并使用 `DATABASE_PATH`，例如：

```yaml
DATABASE_URL: ""
DATABASE_PATH: /data/public_ip_monitor.db
```

推荐优先使用拆分后的 MySQL 参数：

```yaml
MYSQL_HOST: 你的MySQL地址
MYSQL_PORT: 3306
MYSQL_DATABASE: public_ip_monitor
MYSQL_USER: your_user
MYSQL_PASSWORD: your_password
```

如需连接外部 MySQL，也可以直接设置 `DATABASE_URL`：

```yaml
DATABASE_URL: mysql://username:password@mysql-host:3306/public_ip_monitor
```

当 `DATABASE_URL` 非空时，系统会优先使用它；否则会根据 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD` 自动拼接 MySQL 连接串。两者都没有时，才回退到 `DATABASE_PATH` 对应的 SQLite。
如果你想临时启用仓库内置 MySQL，可显式带上 profile：

```bash
docker compose --profile local-db up -d --build
```

## NAS 直接拉镜像部署

如果 NAS 不方便上传源码，可直接使用镜像版 Compose。当前示例也保留了一个可选的内置 MySQL profile：

```yaml
services:
  mysql:
    image: mysql:8.4
    container_name: public-ip-monitor-mysql
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: ${MYSQL_DATABASE:-public_ip_monitor}
      MYSQL_USER: ${MYSQL_USER:-public_ip_monitor}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-change_me}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-change_root_password}
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
    volumes:
      - ./mysql-data:/var/lib/mysql

  public-ip-monitor:
    image: tuomasi502/public-ip-monitor:latest
    container_name: public-ip-monitor
    restart: unless-stopped
    environment:
      BASE_URL: http://你的NAS地址:8000
      TIMEZONE_LABEL: Asia/Shanghai
      MYSQL_HOST: ${MYSQL_HOST:-mysql}
      MYSQL_PORT: ${MYSQL_PORT:-3306}
      DATABASE_URL: mysql://${MYSQL_USER:-public_ip_monitor}:${MYSQL_PASSWORD:-change_me}@${MYSQL_HOST:-mysql}:${MYSQL_PORT:-3306}/${MYSQL_DATABASE:-public_ip_monitor}
      DATABASE_PATH: /data/public_ip_monitor.db
      CHECK_INTERVAL_SECONDS: 300
      REQUEST_TIMEOUT_SECONDS: 10
      STARTUP_CHECK_ENABLED: "true"
      PUBLIC_IP_SERVICES: http://cip.cc
      SMTP_HOST: smtp.example.com
      SMTP_PORT: 587
      SMTP_USERNAME: your_mail_account@example.com
      SMTP_PASSWORD: your_smtp_password_or_token
      SMTP_STARTTLS: "true"
      SMTP_SSL: "false"
      MAIL_FROM: your_mail_account@example.com
      MAIL_TO: receiver@example.com
      MAIL_SUBJECT_PREFIX: "[Public IP Monitor]"
      MESSAGE_PUSH_ENABLED: "false"
      MESSAGE_PUSH_USER_ID: your_user_id
      MESSAGE_PUSH_USER_KEY: your_user_key
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
```

仓库里也提供了现成文件 [docker-compose.nas.yml](/Users/tangjie/public-ip-monitor/docker-compose.nas.yml)。
首次启动时，如果数据库里还没有邮件或推送配置，容器会自动把这些环境变量写入初始化配置；后续你在页面里修改后，重启容器不会被覆盖。

## 行为说明

- `CHECK_INTERVAL_SECONDS` 控制轮询周期，默认 `300` 秒
- 第一次成功检测只会落库，不发送通知
- 从第二次开始，只有公网 IP 与上一次不同才发送通知
- 通知发送失败不会阻止变动记录写入，页面会显示失败原因
- 使用 SQLite 时，只要保留 `./data` 卷，容器重建后记录仍会保留
- 使用默认 Compose 的 MySQL 时，只要保留 `./mysql-data` 卷，容器重建后记录仍会保留

## NAS 部署建议

- 将项目目录放到 NAS 可持久化路径
- 使用 SQLite 时，通过 `./data` 卷保留数据库
- 使用默认 Compose 的 MySQL 时，通过 `./mysql-data` 卷保留数据库
- 如果使用 MySQL，建议单独创建数据库，例如 `public_ip_monitor`
- 如果 SMTP 服务要求 SSL，设置 `SMTP_SSL=true` 且 `SMTP_STARTTLS=false`
- 如果使用消息推送助手，只需要填写 `MESSAGE_PUSH_USER_ID` 和 `MESSAGE_PUSH_USER_KEY`
- 推送地址固定为 `https://messagepush.luckfast.com/send/`，系统会自动拼接 `用户 ID / 用户 Key`，并追加 `title`、`subtitle`、`message`
- 建议给容器配置固定时区标识，仅用于页面展示；数据库时间统一保存为 UTC ISO 时间

## 目录结构

```text
public-ip-monitor/
├── app/
│   ├── config.py
│   ├── db.py
│   ├── main.py
│   ├── services.py
│   ├── static/style.css
│   └── templates/index.html
├── data/
├── .env.example
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```
