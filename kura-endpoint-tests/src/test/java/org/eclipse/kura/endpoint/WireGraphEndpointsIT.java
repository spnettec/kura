/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.endpoint;

import java.util.Properties;

import org.eclipse.kura.cloudconnection.message.KuraMessage;
import org.eclipse.kura.core.testutil.requesthandler.Transport;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.rest.wire.provider.test.WireGraphRestServiceTest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.TestInstance;

/** The same 49 graph scenarios on each real transport; configuration/SCR remain controlled. */
class WireGraphEndpointsIT extends EndpointTestBase {

    @Override
    protected void configureBrokerProperties(Properties properties) {
        // Driver descriptors exceed Moquette's 8092-byte default after JSON/base64 framing.
        properties.setProperty("netty.mqtt.message_size", Integer.toString(64 * 1024));
    }

    @Nested
    @TestInstance(TestInstance.Lifecycle.PER_METHOD)
    class Http extends GraphScenarios {
        @Override
        TransportType transportType() { return TransportType.REST; }
    }

    @Nested
    @TestInstance(TestInstance.Lifecycle.PER_METHOD)
    class Mqtt extends GraphScenarios {
        @Override
        TransportType transportType() { return TransportType.MQTT; }
    }

    abstract class GraphScenarios extends WireGraphRestServiceTest {
        abstract TransportType transportType();

        @BeforeEach
        void registerTransport() {
            this.endpoint.setUserAdmin(http.identityFixture().userAdmin);
            this.endpoint.setRequestHandlerRegistry(cloud);
            http.resource(this.endpoint);
            useTransport(transportType(), "WIRE-V1", "wire/v1");
        }

        @AfterEach
        void unregisterTransport() {
            if (this.endpoint != null) { this.endpoint.unsetRequestHandlerRegistry(cloud); }
        }

        @Override
        protected KuraMessage performRequest(MethodSpec method, String path, String body) {
            String mqttMethod = method.alternative().length == 0 ? method.method() : method.alternative()[0];
            return requestKuraMessage(new Transport.MethodSpec(method.method(), mqttMethod), path, body);
        }
    }
}
