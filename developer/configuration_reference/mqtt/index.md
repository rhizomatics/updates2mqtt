# MQTT

The `mqtt` block. See [Interface Reference](https://updates2mqtt.rhizomatics.org.uk/developer/interface_reference/index.md) for the topics published.

## MqttConfig

MQTT broker connection, the `mqtt` block

### host

```python
host: str = '${oc.env:MQTT_HOST,localhost}'
```

Broker host name or IP address, from `MQTT_HOST`

### user

```python
user: str = f'${{oc.env:MQTT_USER,{MISSING}}}'
```

Broker user name, from `MQTT_USER`, the one mandatory setting

### password

```python
password: str | None = "${oc.env:MQTT_PASS,''}"
```

Broker password, from `MQTT_PASS`

### port

```python
port: int = '${oc.decode:${oc.env:MQTT_PORT,1883}}'
```

Broker port, from `MQTT_PORT`

### topic_root

```python
topic_root: str = 'updates2mqtt'
```

First level of every topic Updates2MQTT publishes, other than Home Assistant discovery and healthcheck

### protocol

```python
protocol: str = '${oc.env:MQTT_VERSION,3.11}'
```

MQTT protocol version, `3.1`, `3.11` or `5`, from `MQTT_VERSION`

### transport

```python
transport: str = "${oc.env:MQTT_TRANSPORT,'tcp'}"
```

`tcp`, `websockets` or `unix`, from `MQTT_TRANSPORT`

### connect_timeout

```python
connect_timeout: float = 20
```

Seconds to wait for the broker to accept a connection

### keepalive

```python
keepalive: int = 30
```

Seconds between MQTT keepalive pings

### tls_mode

```python
tls_mode: TlsMode = '${oc.env:MQTT_TLS_MODE,off}'
```

TLS for the broker connection, from `MQTT_TLS_MODE`

### ca_certs

```python
ca_certs: str | None = "${oc.env:MQTT_CA_CERTS,''}"
```

CA certificate bundle file to verify the broker, from `MQTT_CA_CERTS`

### client_cert

```python
client_cert: str | None = "${oc.env:MQTT_CLIENT_CERT,''}"
```

Client certificate file for mutual TLS, from `MQTT_CLIENT_CERT`

### client_key

```python
client_key: str | None = "${oc.env:MQTT_CLIENT_KEY,''}"
```

Client private key file for mutual TLS, from `MQTT_CLIENT_KEY`

### client_key_password

```python
client_key_password: str | None = (
    "${oc.env:MQTT_CLIENT_KEY_PASS,''}"
)
```

Password for the client private key, from `MQTT_CLIENT_KEY_PASS`

### cert_reqs

```python
cert_reqs: VerifyMode = (
    "${oc.env:MQTT_CERT_REQUIRED,CERT_REQUIRED}"
)
```

Broker certificate verification, `CERT_REQUIRED`, `CERT_OPTIONAL` or `CERT_NONE`, from `MQTT_CERT_REQUIRED`

## TlsMode

MQTT broker TLS, matched case insensitively

### ON

```python
ON = auto()
```

TLS with certificate verification

### OFF

```python
OFF = auto()
```

Plain TCP

### INSECURE

```python
INSECURE = auto()
```

TLS without verifying the broker’s certificate or host name
