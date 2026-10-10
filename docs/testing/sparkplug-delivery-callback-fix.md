# Sparkplug delivery callback null-message repair (2026-10-10)

A real SCR/filesystem TLS run delivered the QoS 1 application payload to the observer,
then lost its MQTT connection. The listener captured Paho's `MqttException (0)` caused
by `SparkplugDataTransport.deliveryComplete()` dereferencing a null message. The two
NDEATH/32104 errors in the earlier passing TLS run were secondary symptoms: that test
only waited for observer delivery, so its connection-state assertion could race the
client callback. The earlier report remains historical evidence, not proof of delivery
confirmation or graceful shutdown.

[Paho 1.2.5's token contract](https://github.com/eclipse-paho/paho.mqtt.java/blob/v1.2.5/org.eclipse.paho.client.mqttv3/src/main/java/org/eclipse/paho/client/mqttv3/IMqttDeliveryToken.java)
allows `getMessage()` to return null after delivery. The audited
[upstream Kura source](https://github.com/eclipse-kura/kura/blob/e500a68d7b3f4a970aca3e13c038947269278827/kura/org.eclipse.kura.cloudconnection.sparkplug.mqtt.provider/src/main/java/org/eclipse/kura/cloudconnection/sparkplug/mqtt/transport/SparkplugDataTransport.java)
contains the same unconditional dereference. Local ordinary MqttDataTransport already
handles this condition. This is independent of YOFC factory PID/name/description rules.

The Sparkplug callback now reads the message once and accepts a cleared message for
confirmation, retaining the QoS 0 suppression when the message is present. The existing
message ID and session ID are preserved. No API, handwritten OSGi metadata, virtual
thread, configuration, cloud naming or dependency version changes are included.

A deterministic null-message regression fails on the previous production code; the
QoS 0 regression still requires no listener confirmation. The real TLS fixture now
waits for the matching DataTransportToken confirmation before checking connectivity,
records connection-loss causes, and observes QoS 0 non-retained NDEATH on graceful
disconnect (distinct from the QoS 1 last will). These checks run for mutual TLS and the
initial valid connection in the revocation scenario.

See [validation evidence](sparkplug-delivery-callback-validation-20261010.json) for
commits, exact counts, checksums and the archived before/after logs. The unrelated
upstream interrupted-reconnect behavior difference was observed during comparison but
is not changed or declared verified by this repair. WSS, file-backed DataService
restart durability and remaining IDEA acceptance are separate work.

## 2026-10-11 后续 Sparkplug 中断修复

此前未验证的连接等待中断差异已单独复现并修复；模块 155/155、真实容器
13/13、IDEA Run 3/3 通过，见 [新证据](sparkplug-interrupted-reconnect-validation-20261011.md)。
原记录与完整 CI 数字保留其固定提交范围，不将后续修复记为完整门禁重跑。
