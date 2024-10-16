/*******************************************************************************
 * Copyright (c) 2016, 2020 Red Hat Inc and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.camel.xml;

import static java.lang.String.format;
import static org.eclipse.kura.camel.component.Configuration.asBoolean;
import static org.eclipse.kura.camel.component.Configuration.asString;
import static org.eclipse.kura.camel.runner.CamelRunner.createOsgiRegistry;
import static org.eclipse.kura.camel.runner.ScriptRunner.create;
import static org.osgi.framework.FrameworkUtil.getBundle;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

import javax.script.SimpleBindings;

import org.eclipse.kura.camel.bean.PayloadFactory;
import org.eclipse.kura.camel.component.AbstractXmlCamelComponent;
import org.eclipse.kura.camel.component.Configuration;
import org.eclipse.kura.camel.runner.CamelRunner.Builder;
import org.eclipse.kura.camel.runner.ScriptRunner;
import org.eclipse.kura.cloud.CloudService;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Constants;
import org.osgi.framework.FrameworkUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import io.vertx.core.Vertx;
import io.vertx.core.VertxOptions;
import io.vertx.ext.web.client.WebClient;
import io.vertx.ext.web.client.WebClientOptions;

/**
 * A ready to run XML based Apache Camel component
 *
 * @noextend This class is not intended to be extended
 */
public class XmlRouterComponent extends AbstractXmlCamelComponent {

    private static final String TOKEN_PATTERN = "\\s*,\\s*";

    private static final Logger logger = LoggerFactory.getLogger(XmlRouterComponent.class);

    private static final String CLOUD_SERVICE_PREREQS = "cloudService.prereqs";
    private static final String COMPONENT_PREREQS = "component.prereqs";
    private static final String LANGUAGE_PREREQS = "language.prereqs";
    private static final String DISABLE_JMX = "disableJmx";
    private static final String INIT_CODE = "initCode";
    private static final String SCRIPT_ENGINE_NAME = "scriptEngineName";

    private final BundleContext bundleContext;

    private Set<String> requiredComponents = new HashSet<>();
    private Set<String> requiredLanguages = new HashSet<>();

    private Map<String, String> cloudServiceRequirements = new HashMap<>();
    private String initCode = "";
    private String scriptEngineName = "";

    private Vertx vertx;
    private WebClient webClient;

    private boolean disableJmx;

    public XmlRouterComponent() {
        super("xml.data");
        this.bundleContext = FrameworkUtil.getBundle(XmlRouterComponent.class).getBundleContext();
    }

    @Override
    protected void stop() throws Exception {
        super.stop();
        if (webClient != null) {
            webClient.close();
            webClient = null;
        }
    }

    @Override
    protected void customizeBuilder(final Builder builder, final Map<String, Object> properties) {

        super.customizeBuilder(builder, properties);

        // JMX

        final boolean disableJmxTemp = asBoolean(properties, DISABLE_JMX, false);
        builder.disableJmx(disableJmxTemp);

        // parse configuration

        final Set<String> newRequiredComponents = parseRequirements(asString(properties, COMPONENT_PREREQS));
        final Set<String> newRequiredLanguages = parseRequirements(asString(properties, LANGUAGE_PREREQS));

        final Map<String, String> cloudServiceRequirementsTemp = parseCloudServiceRequirements(
                asString(properties, CLOUD_SERVICE_PREREQS));

        final String initCodeTemp = parseInitCode(properties);
        final String scriptEngineNameTemp = parseScriptEngineName(properties);

        // set component requirements

        logger.debug("Setting new component requirements");
        for (final String component : newRequiredComponents) {
            logger.debug("Require component: {}", component);
            builder.requireComponent(component);
        }

        logger.debug("Setting new language requirements");
        for (final String language : newRequiredLanguages) {
            if (!"simple".equals(language)) {
                logger.debug("Require language: {}", language);
                builder.requireLanguage(language);
            }
        }

        // set cloud service requirements

        logger.debug("Setting new cloud service requirements");
        for (final Map.Entry<String, String> entry : cloudServiceRequirementsTemp.entrySet()) {
            final String filter;
            if (entry.getValue().startsWith("(")) {
                filter = entry.getValue();
            } else {
                filter = format("(&(%s=%s)(kura.service.pid=%s))", Constants.OBJECTCLASS, CloudService.class.getName(),
                        entry.getValue());
            }
            builder.cloudService(null, filter, Builder.addAsCloudComponent(entry.getKey()));
        }

        if (vertx == null) {
            vertx = Vertx.vertx(new VertxOptions().setPreferNativeTransport(true));
        }
        final ClassLoader original = Thread.currentThread().getContextClassLoader();
        try {
            Thread.currentThread().setContextClassLoader(XmlRouterComponent.class.getClassLoader());
            if (webClient != null) {
                webClient.close();
            }
            webClient = WebClient.create(vertx, new WebClientOptions().setIdleTimeout(60000));

        } finally {
            Thread.currentThread().setContextClassLoader(original);
        }

        if (!initCodeTemp.isEmpty()) {

            // call init code before context start

            builder.addBeforeStart(camelContext -> {
                if (initCode == null || initCode.isEmpty()) {
                    return;
                }

                try {

                    final ScriptRunner runner = create(XmlRouterComponent.class.getClassLoader(), scriptEngineName,
                            initCode);

                    final SimpleBindings bindings = new SimpleBindings();
                    bindings.put("camelContext", camelContext);
                    bindings.put("logger", logger);

                    bindings.put("webClient", webClient);
                    bindings.put("vertx", vertx);
                    // perform call

                    runner.run(bindings);
                } catch (final Exception e) {
                    logger.warn("Failed to run init code", e);
                }
            });
        }

        // build registry

        final BundleContext ctx = getBundle(XmlRouterComponent.class).getBundleContext();
        final Map<String, Map<Class<?>, Object>> services = new HashMap<>();
        services.put("payloadFactory", Map.of(PayloadFactory.class, new PayloadFactory()));
        services.put("vertx", Map.of(Vertx.class, vertx));
        services.put("webClient", Map.of(WebClient.class, webClient));
        builder.registryFactory(createOsgiRegistry(ctx, services));

        // assign new state

        this.requiredComponents = newRequiredComponents;
        this.requiredLanguages = newRequiredLanguages;
        this.cloudServiceRequirements = cloudServiceRequirementsTemp;
        this.initCode = initCodeTemp;
        this.scriptEngineName = scriptEngineNameTemp;
        this.disableJmx = disableJmxTemp;
    }

    @Override
    protected boolean isRestartNeeded(final Map<String, Object> properties) {
        if (super.isRestartNeeded(properties)) {
            return true;
        }

        final boolean disableJmxTemp = asBoolean(properties, DISABLE_JMX, false);

        final Set<String> newRequiredComponents = parseRequirements(asString(properties, COMPONENT_PREREQS));
        final Set<String> newRequiredLanguages = parseRequirements(asString(properties, LANGUAGE_PREREQS));

        final Map<String, String> cloudServiceRequirementsTemp = parseCloudServiceRequirements(
                asString(properties, CLOUD_SERVICE_PREREQS));

        final String initCodeTemp = parseInitCode(properties);
        final String scriptEngineNameTemp = parseScriptEngineName(properties);

        if (this.disableJmx != disableJmxTemp) {
            logger.debug("Require restart due to '{}' change", DISABLE_JMX);
            return true;
        }

        if (!this.requiredComponents.equals(newRequiredComponents)) {
            logger.debug("Require restart due to '{}' change", COMPONENT_PREREQS);
            return true;
        }

        if (!this.requiredLanguages.equals(newRequiredLanguages)) {
            logger.debug("Require restart due to '{}' change", LANGUAGE_PREREQS);
            return true;
        }

        if (!this.cloudServiceRequirements.equals(cloudServiceRequirementsTemp)) {
            logger.debug("Require restart due to '{}' change", CLOUD_SERVICE_PREREQS);
            return true;
        }

        if (!this.initCode.equals(initCodeTemp)) {
            logger.debug("Require restart due to '{}' change", INIT_CODE);
            return true;
        }

        if (!this.scriptEngineName.equals(scriptEngineNameTemp)) {
            logger.debug("Require restart due to '{}' change", INIT_CODE);
            return true;
        }

        return false;
    }

    private static Map<String, String> parseCloudServiceRequirements(final String value) {
        if (value == null || value.trim().isEmpty()) {
            return Collections.emptyMap();
        }

        final Map<String, String> result = new HashMap<>();

        for (final String tok : value.split(TOKEN_PATTERN)) {
            logger.debug("Testing - '{}'", tok);

            final String[] s = tok.split("=", 2);
            if (s.length != 2) {
                continue;
            }

            logger.debug("CloudService - '{}' -> '{}'", s[0], s[1]);
            result.put(s[0], s[1]);
        }

        return result;
    }

    private static Set<String> parseRequirements(final String value) {
        if (value == null || value.trim().isEmpty()) {
            return Collections.emptySet();
        }

        return new HashSet<>(Arrays.asList(value.split(TOKEN_PATTERN)));
    }

    private static String parseInitCode(final Map<String, Object> properties) {
        return Configuration.asString(properties, INIT_CODE, "");
    }

    private static String parseScriptEngineName(final Map<String, Object> properties) {
        return Configuration.asString(properties, SCRIPT_ENGINE_NAME, "Javascript");
    }

    @Override
    protected BundleContext getBundleContext() {
        return this.bundleContext;
    }

}
