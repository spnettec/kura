/*
 * Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.testing.osgi;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import org.osgi.framework.Bundle;
import org.osgi.framework.wiring.BundleWiring;

/** Export the resolver's actual provider choices without starting application bundles. */
public final class WiringInventory {
    private WiringInventory() { }
    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 3) {
            throw new IllegalArgumentException("Usage: WiringInventory <jar-paths.txt> <output.tsv> <framework-storage>");
        }
        try (var runtime = new EquinoxRuntime(Path.of(arguments[2]))) {
            var bundles = new ArrayList<Bundle>();
            for (String line : Files.readAllLines(Path.of(arguments[0]))) {
                if (!line.isBlank()) { bundles.add(runtime.install(Path.of(line))); }
            }
            runtime.resolve(bundles);
            var output = new StringBuilder("consumer\tprovider\tnamespace\tname\n");
            for (Bundle bundle : bundles) {
                var wiring = bundle.adapt(BundleWiring.class);
                for (var wire : wiring.getRequiredWires(null)) {
                    String namespace = wire.getCapability().getNamespace();
                    output.append(bundle.getSymbolicName()).append('\t')
                            .append(wire.getProviderWiring().getBundle().getSymbolicName()).append('\t')
                            .append(namespace).append('\t')
                            .append(wire.getCapability().getAttributes().get(namespace)).append('\n');
                }
            }
            Files.writeString(Path.of(arguments[1]), output);
        }
    }
}
