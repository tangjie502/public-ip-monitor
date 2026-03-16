# Public IP Monitor

一个适合部署到家用 NAS 的 Docker 项目，用于定时检测公网 IP 是否变动；发生变动时通过 SMTP 邮件通知，并提供网页查看历史变动日志。SMTP 可直接在页面配置并发送测试邮件。

## 功能

- 定时轮询多个公网 IP 查询服务，自动容错
- 首次启动记录当前公网 IP，后续检测到变化时发送邮件
- SQLite 持久化 IP 变动记录
- Web 页面展示当前公网 IP、最近检查状态和变动日志
- 公网变动日志支持分页查看，并可一键导出全部 CSV
- 页面内配置 SMTP，并可测试邮件发送是否正常
- Docker / Docker Compose 一键部署

## 技术栈

- FastAPI
- SQLite
- Jinja2
- Docker Compose

## 快速开始

1. 如需修改基础配置，可编辑 `docker-compose.yml` 里的 `environment`，例如：

   ```yaml
   environment:
     BASE_URL: http://你的NAS地址:8000
     TIMEZONE_LABEL: Asia/Shanghai
   ```

2. 启动服务：

   ```bash
   docker compose up -d --build
   ```

3. 打开页面：

   - 日志页面：`http://你的NAS地址:8000/`
   - 健康检查：`http://你的NAS地址:8000/healthz`
   - 状态接口：`http://你的NAS地址:8000/api/status`

4. 进入页面后，在“邮件配置”区域填写 SMTP 信息并发送测试邮件。
5. 需要导出日志时，点击日志区域右上角“导出全部 CSV”。

## NAS 直接拉镜像部署

如果 NAS 不方便上传源码，可直接使用镜像版 Compose：

```yaml
services:
  public-ip-monitor:
    image: tuomasi502/public-ip-monitor:latest
    container_name: public-ip-monitor
    restart: unless-stopped
    environment:
      BASE_URL: http://你的NAS地址:8000
      TIMEZONE_LABEL: Asia/Shanghai
      DATABASE_PATH: /data/public_ip_monitor.db
      CHECK_INTERVAL_SECONDS: 300
      REQUEST_TIMEOUT_SECONDS: 10
      STARTUP_CHECK_ENABLED: "true"
      PUBLIC_IP_SERVICES: https://api.ipify.org,https://ipv4.icanhazip.com,https://ifconfig.me/ip
      SMTP_HOST: smtp.example.com
      SMTP_PORT: 587
      SMTP_USERNAME: your_mail_account@example.com
      SMTP_PASSWORD: your_smtp_password_or_token
      SMTP_STARTTLS: "true"
      SMTP_SSL: "false"
      MAIL_FROM: your_mail_account@example.com
      MAIL_TO: receiver@example.com
      MAIL_SUBJECT_PREFIX: "[Public IP Monitor]"
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
```

仓库里也提供了现成文件 [docker-compose.nas.yml](/Users/tangjie/public-ip-monitor/docker-compose.nas.yml)。
首次启动时，如果数据库里还没有邮件配置，容器会自动把这些 SMTP 环境变量写入初始化配置；后续你在页面里修改后，重启容器不会被覆盖。

## 行为说明

- `CHECK_INTERVAL_SECONDS` 控制轮询周期，默认 `300` 秒
- 第一次成功检测只会落库，不发邮件
- 从第二次开始，只有公网 IP 与上一次不同才发邮件
- 邮件发送失败不会阻止变动记录写入，页面会显示失败原因
- 日志存储在 SQLite 数据库中；只要保留 `./data` 卷，容器重建后记录仍会保留

## NAS 部署建议

- 将项目目录放到 NAS 可持久化路径
- 通过 `./data` 卷保留数据库
- 如果 SMTP 服务要求 SSL，设置 `SMTP_SSL=true` 且 `SMTP_STARTTLS=false`
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
