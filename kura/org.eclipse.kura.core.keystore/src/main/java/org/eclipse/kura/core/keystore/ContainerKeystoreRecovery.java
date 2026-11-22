/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.keystore;

import java.nio.file.Path;

/** Invoked by the stopped-instance launcher under the provider identity. */
final class ContainerKeystoreRecovery {
    public static void main(String[] args) {
        try {
            if (args.length != 5 || !Path.of(args[2]).isAbsolute() || args[1].isEmpty()
                    || !args[4].matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException();
            }
            KeystoreFile.existing(Path.of(args[3])).separateRecoveryLinks(Path.of(args[0]).toRealPath(),
                    Path.of(args[2]), args[1], args[4]);
        } catch (Exception failure) {
            System.err.println("Keystore recovery records could not be paired");
            System.exit(1);
        }
    }

    private ContainerKeystoreRecovery() {}
}
