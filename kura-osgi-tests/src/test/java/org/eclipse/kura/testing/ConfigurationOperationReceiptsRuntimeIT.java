/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.testing;

import static org.junit.jupiter.api.Assertions.*;
import java.lang.reflect.Method;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.eclipse.kura.testing.osgi.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.Bundle;

/** Real packaged Core/SCR; no CM, ConfigurationService, Crypto or business service starts. */
@ExtendWith(EquinoxExtension.class)
@Timeout(value=30,unit=TimeUnit.SECONDS)
class ConfigurationOperationReceiptsRuntimeIT {
    static final String RECEIPTS="org.eclipse.kura.configuration.ConfigurationOperationReceiptService";
    static final String CORE="org.eclipse.kura.core.configuration";
    @TempDir Path data;

    @org.junit.jupiter.api.BeforeEach
    void retainedEvidenceDirectory() throws Exception {
        String output=System.getProperty("kura.receipt.evidence");
        if(output!=null) {
            Path parent=Path.of(output);if(!parent.isAbsolute())throw new IllegalArgumentException("absolute evidence path required");
            Files.createDirectories(parent);data=Files.createTempDirectory(parent,"packaged-receipt-ds-");
        }
    }

    @Test void receiptDsIsAvailableWithoutConfigurationServiceAndReadsAnUnfinishedIntent(EquinoxRuntime runtime) throws Exception {
        assertThrows(ClassNotFoundException.class,()->Class.forName(RECEIPTS));
        var bundles=new ArrayList<Bundle>();
        for(String directory:List.of("target/it-bundles","target/config-it-bundles")) {
            try(var paths=Files.list(Path.of(directory))) {
                for(Path jar:paths.filter(p->p.toString().endsWith(".jar")).sorted().toList()) {
                    // These providers and legacy scenarios are intentionally absent from this receipt-only fixture.
                    if(Set.of("org.eclipse.kura.core.crypto.jar","kura-configuration-test-fixtures.jar",
                            "org.eclipse.equinox.cm.jar").contains(jar.getFileName().toString()))continue;
                    bundles.add(runtime.install(jar));
                }
            }
        }
        runtime.resolve(bundles);
        Bundle core=runtime.bundle(CORE);
        assertEquals("org.eclipse.kura.api",runtime.packageProvider(CORE,"org.eclipse.kura.configuration"));
        String id="op-"+UUID.randomUUID();
        // Deliberately create an interrupted journal protocol fixture, not a successful CM/business action.
        unfinishedIntent(core,id);
        try(var system=runtime.register("org.eclipse.kura.api","org.eclipse.kura.system.SystemService",(proxy,method,args)->
                switch(method.getName()) {
                    case "hashCode" -> System.identityHashCode(proxy);
                    case "equals" -> proxy==args[0];
                    case "toString" -> "private receipt test system paths";
                    case "getKuraDataDirectory" -> data.toString();
                    default -> null;
                },Map.of())) {
            runtime.start(List.of(runtime.bundle("org.apache.felix.scr"),core));
            assertFalse(runtime.hasService("org.osgi.service.cm.ConfigurationAdmin",null));
            assertFalse(runtime.hasService("org.eclipse.kura.configuration.ConfigurationService",null));
            assertFalse(runtime.hasService("org.eclipse.kura.crypto.CryptoService",null));
            try(var receipt=runtime.service(RECEIPTS,null,Duration.ofSeconds(5))) {
                assertEquals(CORE,receipt.provider().getSymbolicName());
                Object unknown=receipt.call("getOperationReceipt",id);
                assertEquals("UNKNOWN",unknown.getClass().getMethod("state").invoke(unknown).toString());
                assertEquals(Map.of("receipt.created","receipt.factory"),unknown.getClass().getMethod("createdFactories").invoke(unknown));
                assertEquals(false,unknown.getClass().getMethod("businessHealthVerified").invoke(unknown));
                String absent="op-"+UUID.randomUUID();
                Object missing=receipt.call("getOperationReceipt",absent);
                assertEquals("NOT_FOUND",missing.getClass().getMethod("state").invoke(missing).toString());
                Object cancelled=receipt.call("cancelUnreservedOperation",absent);
                assertEquals("CANCELLED",cancelled.getClass().getMethod("state").invoke(cancelled).toString());
                Object stillUnknown=receipt.call("getOperationReceipt",id);
                assertEquals("UNKNOWN",stillUnknown.getClass().getMethod("state").invoke(stillUnknown).toString());
            }
            assertFalse(Files.exists(data.resolve("snapshots")),"receipt lookup cannot open or write snapshots");
            assertFalse(runtime.hasService("org.eclipse.kura.configuration.ConfigurationService",null));
        } catch(Exception|Error failure) { runtime.diagnose("receipt-independent-ds-failure");throw failure; }
    }

    private void unfinishedIntent(Bundle core,String id) throws Exception {
        Class<?> creation=core.loadClass("org.eclipse.kura.configuration.ConfigurationRevisionService$Creation");
        Object item=creation.getConstructor(String.class,String.class,Map.class).newInstance("receipt.factory","receipt.created",Map.of("password","not-journaled"));
        Class<?> plan=core.loadClass(CORE+".RecordedConfigurationPlan");
        var constructor=plan.getDeclaredConstructors()[0];constructor.setAccessible(true);
        Object detached=constructor.newInstance(List.of(),List.of(item),Set.of(),Map.of(),null);
        Class<?> journal=core.loadClass(CORE+".ConfigurationIntentJournal");
        Method open=journal.getDeclaredMethod("open",Path.class);open.setAccessible(true);
        Object store=open.invoke(null,data.resolve("configuration-dispatch-journal-v1"));
        try {
            Method reserve=journal.getDeclaredMethod("clientOperation",String.class,plan);reserve.setAccessible(true);
            Object operation=reserve.invoke(store,id,detached);
            try {
                Method permit=journal.getDeclaredMethod("requireOrdinaryWrite");permit.setAccessible(true);permit.invoke(store);
                Method begin=journal.getDeclaredMethod("begin",String.class,Set.class);begin.setAccessible(true);
                Object ticket=begin.invoke(store,"plan",Set.of("receipt.created"));
                ((AutoCloseable)ticket).close();
            } finally { ((AutoCloseable)operation).close(); }
        } finally { ((AutoCloseable)store).close(); }
    }
}
