/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.ByteArrayInputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Properties;

/** Offline reading of the two property files used by the fixed package launcher. */
public final class SnapshotStorePolicy {
    private SnapshotStorePolicy() { }

    public static void main(String[] args) {
        try {
            if (args.length != 2) throw new IllegalArgumentException();
            byte[] defaults = read(Path.of(args[0]));
            byte[] custom = read(Path.of(args[1]));
            Properties properties = new Properties();
            properties.load(new ByteArrayInputStream(defaults));
            properties.load(new ByteArrayInputStream(custom));
            if (!"/opt/eclipse/kura/user/snapshots".equals(properties.getProperty("kura.snapshots"))) {
                throw new IllegalArgumentException();
            }
            boolean encrypted = Boolean.parseBoolean(properties.getProperty("kura.snapshots.encrypt", "true"));
            var digest = MessageDigest.getInstance("SHA-256");
            String original = HexFormat.of().formatHex(digest.digest(defaults));
            String overrides = HexFormat.of().formatHex(digest.digest(custom));
            System.out.println((encrypted ? "aes-gcm" : "plain") + " " + original + " " + overrides);
        } catch (Exception ignored) {
            System.err.println("Ordinary snapshot policy unavailable");
            System.exit(2);
        }
    }

    private static byte[] read(Path path) throws Exception {
        if (!path.isAbsolute() || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException();
        }
        try (var input = Files.newInputStream(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] result = input.readNBytes((128 << 10) + 1);
            if (result.length > (128 << 10)) throw new IllegalArgumentException();
            return result;
        }
    }
}
