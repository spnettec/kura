/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.endpoint;

import java.util.List;
import java.util.Optional;

import org.eclipse.kura.cloudconnection.message.KuraMessage;
import org.eclipse.kura.core.testutil.requesthandler.Transport;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.rest.network.configuration.provider.test.NetworkConfigurationRestServiceTest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;

/** Real HTTP authentication and the existing local configuration DTO scenarios. */
class NetworkConfigurationEndpointsIT extends EndpointTestBase {
    @Nested
    @TestInstance(TestInstance.Lifecycle.PER_METHOD)
    class Http extends NetworkConfigurationRestServiceTest {
        @BeforeEach
        void registerTransport() {
            this.endpoint.setUserAdmin(http.identityFixture().userAdmin);
            http.resource(this.endpoint);
            useTransport(TransportType.REST, "unused-http-only", "networkConfiguration/v1");
        }

        @Override
        protected KuraMessage performRequest(MethodSpec method, String path, String body) {
            String requestMethod = "DELETE".equals(method.method()) ? "DEL" : method.method();
            return requestKuraMessage(new Transport.MethodSpec(method.method(), requestMethod), path, body);
        }

        @Test
        void shouldReturnUnauthorizedStatusWhenNoRestPermissionIsGiven() throws Exception {
            http.identityFixture().create("network.reader", "Network-Reader-1!", List.of());
            givenBasicCredentials(Optional.empty());
            assertCredentialStatus(401);
        }

        @Test
        void rejectsIncorrectPassword() {
            givenBasicCredentials(Optional.of("endpoint.admin:wrong-password"));
            assertCredentialStatus(401);
        }

        @Test
        void rejectsAuthenticatedIdentityWithoutNetworkPermission() throws Exception {
            http.identityFixture().create("network.reader", "Network-Reader-1!", List.of());
            givenBasicCredentials(Optional.of("network.reader:Network-Reader-1!"));
            assertCredentialStatus(403);
        }

        @Test
        void acceptsNetworkConfigurationPermissionWithoutAdministratorRole() throws Exception {
            http.identityFixture().create("network.reader", "Network-Reader-1!", List.of("rest.network.configuration"));
            givenBasicCredentials(Optional.of("network.reader:Network-Reader-1!"));
            assertCredentialStatus(200);
        }

        private void assertCredentialStatus(int status) {
            NetworkConfigurationEndpointsIT.this.whenRequestIsPerformed(new Transport.MethodSpec("GET"),
                    "/configurableComponents");
            NetworkConfigurationEndpointsIT.this.thenResponseCodeIs(status);
        }
    }
}
