/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.testutil.requesthandler;

import static org.junit.jupiter.api.Assertions.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import com.sun.net.httpserver.HttpServer;
import com.eclipsesource.json.Json;
import org.eclipse.kura.core.testutil.json.JsonProjection;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.core.testutil.requesthandler.Transport.Response;
import org.junit.jupiter.api.*;

@Timeout(10)
class RequestFixturesTest {
    private HttpServer server;
    private ExecutorService worker;
    private RestTransport transport;
    private String prefix;

    @BeforeEach
    void startServer() throws Exception {
        this.server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        this.worker = Executors.newVirtualThreadPerTaskExecutor();
        this.server.setExecutor(this.worker);
        this.server.createContext("/services/test/echo", exchange -> {
            String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("X-Method", exchange.getRequestMethod());
            exchange.getResponseHeaders().add("X-Auth", Optional.ofNullable(exchange.getRequestHeaders().getFirst("Authorization")).orElse("none"));
            exchange.getResponseHeaders().add("X-Custom", Optional.ofNullable(exchange.getRequestHeaders().getFirst("X-Custom")).orElse("none"));
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length == 0 ? -1 : bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        this.server.createContext("/services/test/error", exchange -> {
            byte[] body = "不存在".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(404, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        this.server.createContext("/services/test/redirect", exchange -> {
            exchange.getResponseHeaders().add("Location", "/services/test/echo");
            exchange.sendResponseHeaders(302, -1);
            exchange.close();
        });
        this.server.createContext("/services/test/cookie", exchange -> {
            String supplied = Optional.ofNullable(exchange.getRequestHeaders().getFirst("Cookie")).orElse("none");
            exchange.getResponseHeaders().add("Set-Cookie", "JSESSIONID=" + exchange.getRequestURI().getQuery() + "; Path=/services");
            byte[] body = supplied.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        this.server.start();
        this.prefix = "http://127.0.0.1:" + this.server.getAddress().getPort() + "/services/";
        this.transport = new RestTransport(this.prefix, "test");
        this.transport.init();
    }

    @AfterEach
    void stopServer() {
        try { if (this.transport != null) { this.transport.close(); } }
        finally {
            if (this.server != null) { this.server.stop(0); }
            if (this.worker != null) { this.worker.close(); assertTrue(this.worker.isTerminated()); }
        }
    }

    @Test
    void roundTripsUtf8DeleteBodyCredentialsAndCaseInsensitiveHeaders() {
        this.transport.setBasicCredentials(Optional.of("用户:密碼"));
        this.transport.setHeader("X-Custom", "before");
        this.transport.setHeader("x-custom", "after");
        Response response = this.transport.runRequest("/echo", new MethodSpec("DELETE", "DEL"), "{\"value\":\"测量-µ\"}");
        assertEquals(200, response.getStatus());
        assertEquals(Optional.of("{\"value\":\"测量-µ\"}"), response.getBody());
        assertEquals(List.of("DELETE"), response.getHeader("x-method"));
        assertEquals(List.of("after"), response.getHeader("X-CUSTOM"));
        assertEquals(List.of("Basic " + Base64.getEncoder().encodeToString("用户:密碼".getBytes(StandardCharsets.UTF_8))), response.getHeader("x-auth"));
        this.transport.removeHeader("X-CUSTOM");
        this.transport.setBasicCredentials(Optional.empty());
        response = this.transport.runRequest("/echo", new MethodSpec("GET"));
        assertEquals(Optional.empty(), response.getBody());
        assertEquals(List.of("none"), response.getHeader("X-Auth"));
        assertEquals(List.of("none"), response.getHeader("X-Custom"));
    }

    @Test
    void preservesErrorBodyAndDoesNotFollowRedirects() {
        Response error = this.transport.runRequest("/error", new MethodSpec("GET"));
        assertEquals(404, error.getStatus());
        assertEquals(Optional.of("不存在"), error.getBody());
        Response redirect = this.transport.runRequest("/redirect", new MethodSpec("GET"));
        assertEquals(302, redirect.getStatus());
        assertEquals(List.of("/services/test/echo"), redirect.getHeader("Location"));
        assertEquals(List.of(), redirect.getHeader("Absent"));
    }

    @Test
    void isolatesCookiesAndCanReplayCapturedCookie() {
        try (Scenario scenario = new Scenario(this.transport)) {
            scenario.whenRequestIsPerformed(new MethodSpec("GET"), "/cookie?first");
            scenario.thenResponseHasCookie("JSESSIONID");
            scenario.givenSnapshotOfCurrentCookies();
            scenario.givenCookieInSnapshot("JSESSIONID");
            scenario.whenRequestIsPerformed(new MethodSpec("GET"), "/cookie?second");
            assertTrue(scenario.expectResponse().getBody().orElseThrow().contains("JSESSIONID=first"));
            scenario.thenCurrentCookieDiffersFromPreviousSnapshot("JSESSIONID");
            scenario.whenCookieIsRestoredFromSnapshot("JSESSIONID");
            scenario.whenRequestIsPerformed(new MethodSpec("GET"), "/cookie?third");
            assertTrue(scenario.expectResponse().getBody().orElseThrow().contains("JSESSIONID=first"));
            try (RestTransport separate = new RestTransport(this.prefix, "test")) {
                assertEquals(Optional.of("none"), separate.runRequest("/cookie?other", new MethodSpec("GET")).getBody());
            }
            this.transport.getCookieManager().getCookieStore().removeAll();
            assertThrows(AssertionError.class, () -> scenario.thenCurrentCookieDiffersFromPreviousSnapshot("JSESSIONID"));
        }
        assertTrue(this.transport.getCookieManager().getCookieStore().getCookies().isEmpty());
    }

    @Test
    void successAssertionRejectsRedirectAndRetainsEmptyAndJsonAssertions() {
        try (Scenario scenario = new Scenario(this.transport)) {
            scenario.whenRequestIsPerformed(new MethodSpec("GET"), "/redirect");
            assertThrows(AssertionError.class, scenario::thenRequestSucceeds);
            scenario.whenRequestIsPerformed(new MethodSpec("POST"), "/echo", "{\"value\":1}");
            scenario.thenRequestSucceeds();
            scenario.thenResponseCodeIs(200);
            scenario.thenResponseBodyEqualsJson("{ \"value\": 1 }");
            scenario.thenResponseBodyIsNotEmpty();
            scenario.whenRequestIsPerformed(new MethodSpec("GET"), "/echo");
            scenario.thenResponseBodyIsEmpty();
        }
    }

    @Test
    void readTimeoutFailsInsteadOfProceedingAndPortWaitsAreBounded() throws Exception {
        CountDownLatch release = new CountDownLatch(1);
        this.server.createContext("/services/test/slow", exchange -> {
            try { release.await(2, TimeUnit.SECONDS); }
            catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            finally { exchange.close(); }
        });
        this.transport.setTimeoutMillis(100);
        try {
            IllegalStateException error = assertThrows(IllegalStateException.class,
                    () -> this.transport.runRequest("/slow", new MethodSpec("GET")));
            assertInstanceOf(SocketTimeoutException.class, error.getCause());
        } finally { release.countDown(); }
        int port = this.server.getAddress().getPort();
        RestTransport.waitPortOpen("127.0.0.1", port, 1, TimeUnit.SECONDS);
        assertThrows(IllegalStateException.class,
                () -> RestTransport.waitPortClosed("127.0.0.1", port, 50, TimeUnit.MILLISECONDS));
        this.server.stop(0);
        RestTransport.waitPortClosed("127.0.0.1", port, 1, TimeUnit.SECONDS);
        assertThrows(IllegalArgumentException.class, () -> this.transport.setTimeoutMillis(0));
    }

    @Test
    void jsonProjectionComposesAndFindsMatchingArrayMembers() {
        var json = Json.parse("{\"items\":[{\"id\":1},false,{\"id\":2}]}");
        var path = JsonProjection.self().field("items").anyArrayItem(JsonProjection.self().field("id").matching(Json.value(2)));
        assertEquals(Json.value(2), path.apply(json));
        assertEquals(".items[*].id(=2)", path.toString());
        assertEquals(Json.value(1), JsonProjection.self().field("items").arrayItem(0).field("id").apply(json));
        assertNull(JsonProjection.self().field("items").arrayItem(4).apply(json));
        assertNull(JsonProjection.self().field("items").anyArrayItem(JsonProjection.self().matching(Json.NULL)).apply(json));
        assertThrows(IllegalArgumentException.class, () -> new MethodSpec("DELETE"));
        assertEquals("DEL", new MethodSpec("DELETE", "DEL").getRequestHandlerMethod());
    }

    private static class Scenario extends AbstractRequestHandlerTest {
        Scenario(Transport transport) { super(transport); }
    }
}
