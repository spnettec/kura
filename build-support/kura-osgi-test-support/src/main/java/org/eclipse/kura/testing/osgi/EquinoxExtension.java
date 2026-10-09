/*
 * Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.testing.osgi;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;

import org.junit.jupiter.api.extension.AfterEachCallback;
import org.junit.jupiter.api.extension.BeforeEachCallback;
import org.junit.jupiter.api.extension.ExtensionContext;
import org.junit.jupiter.api.extension.ParameterContext;
import org.junit.jupiter.api.extension.ParameterResolver;

/** Isolate every test; retain framework storage and diagnostics when a test fails. */
public final class EquinoxExtension implements BeforeEachCallback, AfterEachCallback, ParameterResolver {
    private static final ExtensionContext.Namespace NAMESPACE = ExtensionContext.Namespace.create(EquinoxExtension.class);

    @Override
    public void beforeEach(ExtensionContext context) throws Exception {
        Path root = Path.of(System.getProperty("kura.it.output", "target/osgi-it")).toAbsolutePath();
        Files.createDirectories(root);
        Path directory = Files.createTempDirectory(root, context.getRequiredTestMethod().getName() + "-");
        context.getStore(NAMESPACE).put("directory", directory);
        context.getStore(NAMESPACE).put("runtime", new EquinoxRuntime(directory));
    }

    @Override
    public boolean supportsParameter(ParameterContext parameter, ExtensionContext context) {
        return parameter.getParameter().getType() == EquinoxRuntime.class;
    }

    @Override
    public Object resolveParameter(ParameterContext parameter, ExtensionContext context) {
        return context.getStore(NAMESPACE).get("runtime", EquinoxRuntime.class);
    }

    @Override
    public void afterEach(ExtensionContext context) throws Exception {
        EquinoxRuntime runtime = context.getStore(NAMESPACE).get("runtime", EquinoxRuntime.class);
        if (runtime == null) { return; }
        boolean failed = context.getExecutionException().isPresent();
        try {
            if (failed) { runtime.diagnose("test-failure"); }
        } finally {
            runtime.close();
        }
        if (!failed) {
            Path directory = context.getStore(NAMESPACE).get("directory", Path.class);
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) { Files.delete(path); }
            }
        }
    }
}
