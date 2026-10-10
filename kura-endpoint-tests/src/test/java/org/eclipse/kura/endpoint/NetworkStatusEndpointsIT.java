/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.endpoint;

import org.eclipse.kura.cloudconnection.message.KuraMessage;
import org.eclipse.kura.core.testutil.requesthandler.Transport;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.rest.network.status.provider.test.NetworkStatusRestServiceImplTest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.TestInstance;

/** Existing local network DTO scenarios over sockets; the NetworkStatusService boundary is controlled. */
class NetworkStatusEndpointsIT extends EndpointTestBase {
    @Nested
    @TestInstance(TestInstance.Lifecycle.PER_METHOD)
    class Http extends StatusScenarios {
        @Override
        TransportType transportType() { return TransportType.REST; }
    }

    @Nested
    @TestInstance(TestInstance.Lifecycle.PER_METHOD)
    class Mqtt extends StatusScenarios {
        @Override
        TransportType transportType() { return TransportType.MQTT; }
    }

    abstract class StatusScenarios extends NetworkStatusRestServiceImplTest {
        abstract TransportType transportType();

        @BeforeEach
        void registerTransport() {
            this.endpoint.setUserAdmin(http.identityFixture().userAdmin);
            this.endpoint.setRequestHandlerRegistry(cloud);
            http.resource(this.endpoint);
            useTransport(transportType(), "NET-STATUS-V1", "networkStatus/v1");
        }

        @AfterEach
        void unregisterTransport() {
            this.endpoint.unsetRequestHandlerRegistry(cloud);
        }

        @Override
        protected KuraMessage performRequest(MethodSpec method, String path, String body) {
            String mqttMethod = method.aliases().length == 0 ? method.method() : method.aliases()[0];
            return requestKuraMessage(new Transport.MethodSpec(method.method(), mqttMethod), path, body);
        }
    }
}
