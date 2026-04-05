![updates2mqtt](../images/updates2mqtt-dark-256x256.png){ align=left }

# updates2mqtt

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics)

[![PyPI - Version](https://img.shields.io/pypi/v/updates2mqtt)](https://pypi.org/project/updates2mqtt/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/rhizomatics/updates2mqtt)
[![Coverage](https://raw.githubusercontent.com/rhizomatics/updates2mqtt/refs/heads/badges/badges/coverage.svg)](https://updates2mqtt.rhizomatics.org.uk/developer/coverage/)
![Tests](https://raw.githubusercontent.com/rhizomatics/updates2mqtt/refs/heads/badges/badges/tests.svg)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/rhizomatics/updates2mqtt/main.svg)](https://results.pre-commit.ci/latest/github/rhizomatics/updates2mqtt/main)
[![Publish Python 🐍 distribution 📦 to PyPI and TestPyPI](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml)
[![Github Deploy](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml/badge.svg?branch=main)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml)
[![CodeQL](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql)
[![Dependabot Updates](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates)


<br/>
<br/>


## 摘要

让 Home Assistant 告知您容器的 Docker 镜像有新的更新。

![Home Assistant 更新页面示例](../images/ha_update_detail.png "Home Assistant Updates")![Home Assistant 发行说明示例](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

阅读发行说明，并可选择点击*更新*以触发 Docker *pull*（或可选的 *build*）和*更新*。

![Home Assistant 更新对话框示例](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## 描述

Updates2MQTT 定期检查是否有新版本的组件可用，并将新版本信息发布到 MQTT。支持 HomeAssistant 自动发现，因此所有更新都可以在与 Home Assistant 自身组件和插件相同的位置查看。

目前仅支持 Docker 容器，可通过镜像仓库检查（使用 v1 Docker API 或 OCI v2 API）或源码 git 仓库（参见[本地构建](local_builds.md)）进行检查，并对 Docker、Github Container Registry、Gitlab、Codeberg、Microsoft Container Registry、Quay 和 LinuxServer Registry 进行了专门处理，对大多数其他仓库具有自适应行为。设计是模块化的，因此可以添加其他更新来源，至少用于通知。下一个预计支持的是基于 Debian 系统的 **apt**。

组件也可以更新，可以自动更新，也可以通过 MQTT 触发，例如点击 HomeAssistant 更新对话框中的*安装*按钮。可以指定图标和发行说明以获得更好的 HA 体验。详情请参见 [Home Assistant 集成](home_assistant.md)。

要开始使用，请阅读[安装](installation.md)和[配置](configuration/index.md)页面。

快速体验，请尝试：

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

或不使用 Docker，使用 [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

它还附带一个基本的命令行工具，可对单个运行中的容器执行分析，或从远程仓库获取清单、JSON blob 和标签列表（已验证可与 GitHub、GitLab、Codeberg、Quay、LSCR 和 Microsoft MCR 配合使用）。

## 发行支持

目前仅支持 Docker 容器，但计划支持其他来源，可能会优先考虑 `apt`。

| 生态系统  | 支持          | 备注                                                                                           |
|----------|---------------|-----------------------------------------------------------------------------------------------|
| Docker   | Scan、Fetch   | Fetch 仅为 ``docker pull``。仅支持 ``docker-compose`` 基于镜像的容器重启。                   |

## 心跳

可选地将心跳 JSON 负载定期发布到可配置的 MQTT 主题，默认为 `healthcheck/{node_name}/updates2mqtt`。包含 Updates2MQTT 的当前版本、节点名称、时间戳和一些基本统计信息。

## 健康检查

Docker 镜像中包含一个 `healthcheck.sh` 脚本，如果容器环境变量 `MQTT_HOST`、`MQTT_PORT`、`MQTT_USER` 和 `MQTT_PASS` 已设置，则可将其用作 Docker 健康检查。它使用提供 `mosquitto_sub` 命令订阅主题的 `mosquitto-clients` Linux 包。

!!! tip

    使用 `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` 检查健康检查是否正常工作（如果没有安装 jsonquery，可以省略 `| jq`，但有了它更容易阅读）

另一种方法是直接在 Docker Compose 中使用重启器服务来强制重启，在这种情况下每天一次：

```yaml title="示例 Compose 服务"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## 目标容器

虽然 `updates2mqtt` 会发现并监控 Docker 守护进程下运行的所有容器，但有一些选项可以调整它对这些容器的工作方式。

这通过向容器添加环境变量或 Docker 标签来实现，通常在 `.env` 文件中，或作为 `docker-compose.yaml` 中的 `environment` 选项。

### 自动更新

如果 Docker 容器应立即更新，无需任何确认或触发（例如来自 HomeAssistant 更新对话框），则在目标容器中将环境变量 `UPD2MQTT_UPDATE` 设置为 `Auto`（默认为 `Passive`）。如果希望在不发布到 MQTT 且不让 Home Assistant 看见的情况下更新，则使用 `Silent`。

```yaml title="示例 Compose 片段"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

自动更新也适用于已定义 `git_repo_path` 的本地构建——如果有可拉取的远程提交，则将执行 `git pull`、`docker compose build` 和 `docker compose up`。


## 相关项目

借助 MQTT 进行自托管的其他有用应用：

- [psmqtt](https://github.com/eschava/psmqtt) - 通过 MQTT 报告系统健康状况和指标

在 [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt) 查找更多

如需功能更强大的 Docker 专注型更新管理器，请尝试 [What's Up Docker](https://getwud.github.io/wud/)

## 开发

该组件依赖多个开源包：

- [docker-py](https://docker-py.readthedocs.io/en/stable/) 用于访问 Docker API 的 Python SDK
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) MQTT 客户端
- [OmegaConf](https://omegaconf.readthedocs.io) 用于配置和验证
- [structlog](https://www.structlog.org/en/stable/) 用于结构化日志记录，[rich](https://rich.readthedocs.io/en/stable/) 用于更好的异常报告
- [hishel](https://hishel.com/) 用于缓存元数据
- [httpx](https://www.python-httpx.org) 用于获取元数据
- Astral [uv](https://docs.astral.sh/uv/) 和 [ruff](https://docs.astral.sh/ruff/) 工具用于开发和构建
- [pytest](https://docs.pytest.org/en/stable/) 和支持插件用于自动化测试
- [usingversion](https://pypi.org/project/usingversion/) 用于记录当前版本信息

## 面向 Home Assistant 的 Rhizomatics 开源项目

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - 使用实体按钮、人员检测、日历、太阳及更多条件自动布防和撤防 Home Assistant 报警控制面板
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - 适用于 Home Assistant 的 OpenTelemetry (OTLP) 和 Syslog 事件采集
- [Supernotify](https://supernotify.rhizomatics.org.uk) - 统一通知，实现简便的多渠道消息推送，包括强大的门铃和安防摄像头集成。


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - 通过文件系统（NAS/FTP）将 ANPR/ALPR 车牌识别摄像头集成到 MQTT，支持可选图像分析和英国 DVLA 集成。
