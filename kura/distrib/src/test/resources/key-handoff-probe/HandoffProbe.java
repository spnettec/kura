package org.eclipse.kura.tests.handoff;

import java.io.DataInputStream;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.Channels;
import java.nio.channels.SocketChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.PosixFilePermissions;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;

/** Disposable test bundle. Never included in a distribution or customer profile. */
public final class HandoffProbe implements BundleActivator {
    private Thread worker;
    @Override public void start(BundleContext context) {
        this.worker = new Thread(() -> {
            Path directory = Path.of("/opt/eclipse/kura/data/key-handoff-probe");
            try {
                for (String name : new String[] {"create", "token"}) {
                    Path input = directory.resolve(name + ".request.json");
                    long deadline = System.nanoTime() + 120_000_000_000L;
                    while (!Files.isRegularFile(input) && System.nanoTime() < deadline) { Thread.sleep(50); }
                    if (!Files.isRegularFile(input)) { throw new IllegalStateException("Missing owned fixture input"); }
                    byte[] data = Files.readAllBytes(input);
                    if (data.length == 0 || data.length > 65536) { throw new IllegalStateException("Invalid fixture input"); }
                    byte[] response;
                    try (SocketChannel channel = SocketChannel.open(StandardProtocolFamily.UNIX)) {
                        channel.connect(UnixDomainSocketAddress.of("/run/kura-key-service/control.sock"));
                        ByteBuffer frame = ByteBuffer.allocate(4 + data.length).putInt(data.length).put(data);
                        frame.flip(); while (frame.hasRemaining()) { channel.write(frame); }
                        channel.shutdownOutput();
                        DataInputStream stream = new DataInputStream(Channels.newInputStream(channel));
                        int length = stream.readInt();
                        if (length <= 0 || length > 65536) { throw new IllegalStateException("Invalid fixture frame"); }
                        response = stream.readNBytes(length);
                        if (response.length != length || stream.read() != -1) { throw new IllegalStateException("Truncated fixture frame"); }
                    }
                    Path output = directory.resolve(name + ".response.json");
                    Path temporary = directory.resolve(name + ".output");
                    Files.createFile(temporary, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                    Files.write(temporary, response, StandardOpenOption.WRITE);
                    Files.move(temporary, output, StandardCopyOption.ATOMIC_MOVE);
                }
            } catch (Throwable failure) {
                try { Files.writeString(directory.resolve("error.txt"), "Owned native peer probe failed", StandardOpenOption.CREATE_NEW); }
                catch (Exception ignored) { /* No payload or credential is logged. */ }
            }
        }, "owned-handoff-probe");
        this.worker.setDaemon(true); this.worker.start();
    }
    @Override public void stop(BundleContext context) { this.worker.interrupt(); }
}
