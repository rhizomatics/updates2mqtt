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


## 概要

Home Assistantがコンテナ用Dockerイメージの新しいアップデートを通知します。

![Home Assistantアップデートページの例](../images/ha_update_detail.png "Home Assistant Updates")![Home Assistantリリースノートの例](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

リリースノートを読み、必要に応じて*アップデート*をクリックしてDockerの*pull*（または*build*）と*更新*を実行します。

![Home Assistantアップデートダイアログの例](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## 説明

Updates2MQTTは定期的にコンポーネントの新バージョンをチェックし、新しいバージョン情報をMQTTに公開します。HomeAssistantの自動検出がサポートされているため、すべてのアップデートをHome Assistant自身のコンポーネントやアドインと同じ場所で確認できます。

現在はDockerコンテナのみがサポートされており、イメージレジストリチェック（v1 Docker APIまたはOCI v2 APIを使用）またはソース用gitリポジトリ（[ローカルビルド](local_builds.md)参照）を通じて確認できます。Docker、Github Container Registry、Gitlab、Codeberg、Microsoft Container Registry、Quay、LinuxServer Registryに対する特定の処理と、その他のほとんどに対する適応的な動作をサポートしています。設計はモジュラーであるため、少なくとも通知については他の更新ソースを追加できます。次に予定されているのはDebianベースシステム向けの**apt**です。

コンポーネントは自動的に、またはMQTT経由でトリガーされてアップデートすることもできます。例えば、HomeAssistantのアップデートダイアログで*インストール*ボタンを押すことで実行できます。より良いHAエクスペリエンスのためにアイコンとリリースノートを指定できます。詳細は[Home Assistantインテグレーション](home_assistant.md)を参照してください。

始めるには、[インストール](installation.md)と[設定](configuration/index.md)のページをお読みください。

クイックスタートには以下をお試しください：

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

またはDockerなしで、[uv](https://docs.astral.sh/uv/)を使用：

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

単一の実行中コンテナの分析を実行したり、リモートレジストリからマニフェスト、JSONブロブ、タグリストを取得する基本的なコマンドラインツールも付属しています（GitHub、GitLab、Codeberg、Quay、LSCR、Microsoft MCRで動作確認済み）。

## リリースサポート

現在はDockerコンテナのみがサポートされていますが、他も計画中で、おそらく`apt`が優先されます。

| エコシステム | サポート      | コメント                                                                                                   |
|-------------|---------------|------------------------------------------------------------------------------------------------------------|
| Docker      | Scan, Fetch   | Fetchは``docker pull``のみ。再起動サポートは``docker-compose``イメージベースのコンテナのみ。              |

## ハートビート

ハートビートJSONペイロードは、設定可能なMQTTトピック（デフォルト：`healthcheck/{node_name}/updates2mqtt`）に定期的にオプションで公開されます。Updates2MQTTの現在のバージョン、ノード名、タイムスタンプ、基本的な統計が含まれます。

## ヘルスチェック

`healthcheck.sh`スクリプトがDockerイメージに含まれており、コンテナの環境変数`MQTT_HOST`、`MQTT_PORT`、`MQTT_USER`、`MQTT_PASS`が設定されている場合、Dockerヘルスチェックとして使用できます。トピックをサブスクライブするための`mosquitto_sub`コマンドを提供する`mosquitto-clients` Linuxパッケージを使用します。

!!! tip

    `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq`を使用してヘルスチェックが機能していることを確認してください（jsonqueryがインストールされていない場合は`| jq`を省略できますが、あった方が読みやすいです）

別のアプローチとして、Docker Composeに直接リスタータサービスを使用して再起動を強制する方法があります（この場合は1日1回）：

```yaml title="Composeサービスの例"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## 対象コンテナ

`updates2mqtt`はDockerデーモン下で実行されているすべてのコンテナを検出して監視しますが、それらのコンテナの動作を調整するためのオプションがあります。

これは、コンテナに環境変数またはDockerラベルを追加することで行います。通常は`.env`ファイル内、または`docker-compose.yaml`内の`environment`オプションとして指定します。

### 自動アップデート

Dockerコンテナを確認やトリガーなしに即座にアップデートする場合（例：HomeAssistantのアップデートダイアログから）、対象コンテナの環境変数`UPD2MQTT_UPDATE`を`Auto`に設定します（デフォルトは`Passive`）。MQTTへの公開やHome Assistantへの表示なしにアップデートする場合は`Silent`を使用します。

```yaml title="Composeスニペットの例"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

自動アップデートは、`git_repo_path`が定義されたローカルビルドにも適用されます。リモートコミットがpull可能な場合、`git pull`、`docker compose build`、`docker compose up`が実行されます。


## 関連プロジェクト

MQTTを活用したセルフホスティングに役立つ他のアプリ：

- [psmqtt](https://github.com/eschava/psmqtt) - MQTT経由でシステムの健全性とメトリクスを報告

[awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)でさらに多くを見つける

より強力なDockerに特化したアップデートマネージャーには[What's Up Docker](https://getwud.github.io/wud/)をお試しください

## 開発

このコンポーネントはいくつかのオープンソースパッケージに依存しています：

- [docker-py](https://docker-py.readthedocs.io/en/stable/) Docker API アクセス用 Python SDK
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) MQTTクライアント
- [OmegaConf](https://omegaconf.readthedocs.io) 設定と検証用
- [structlog](https://www.structlog.org/en/stable/) 構造化ログ用と [rich](https://rich.readthedocs.io/en/stable/) より良い例外レポート用
- [hishel](https://hishel.com/) メタデータのキャッシュ用
- [httpx](https://www.python-httpx.org) メタデータ取得用
- Astral [uv](https://docs.astral.sh/uv/) と [ruff](https://docs.astral.sh/ruff/) 開発とビルド用ツール
- [pytest](https://docs.pytest.org/en/stable/) と自動テスト用サポートアドイン
- [usingversion](https://pypi.org/project/usingversion/) 現在のバージョン情報をログに記録

## Home Assistant向け Rhizomatics オープンソース

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - 物理ボタン、在室検知、カレンダー、太陽情報などを使用してHome Assistantの警報コントロールパネルを自動的にアームおよびディスアーム
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - Home Assistant用のOpenTelemetry（OTLP）およびSyslogイベントキャプチャ
- [Supernotify](https://supernotify.rhizomatics.org.uk) - 強力なチャイムとセキュリティカメラ統合を含む、簡単なマルチチャンネルメッセージング向け統合通知。


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - オプションの画像解析とUK DVLA統合を備えた、ファイルシステム（NAS/FTP）経由でANPR/ALPR車番認識カメラをMQTTに統合。
